"""Local media operations and resumable, source-timed transcription."""
import hashlib, json, math, os, shutil, subprocess, tempfile, importlib.metadata
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.partial')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def binary(name):
    value = os.environ.get('THE_' + name.upper()) or shutil.which(name)
    if not value: raise ValueError(f'{name} unavailable; configure THE_{name.upper()} or PATH')
    return value


def run(args, capture=False):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode: raise RuntimeError(result.stderr[-6000:])
    return result.stdout if capture else None


def ff(*args):
    return run([binary('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-nostdin', *args])


def fingerprint(path):
    path = Path(path)
    if not path.is_file(): raise ValueError(f'Source unavailable: {path}; relink only after identifying the same source')
    st = path.stat(); h = hashlib.sha256()
    with path.open('rb') as f:
        h.update(f.read(1024 * 1024))
        if st.st_size > 1024 * 1024:
            f.seek(max(0, st.st_size - 1024 * 1024)); h.update(f.read(1024 * 1024))
    return {'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'sample_sha256': h.hexdigest()}


def probe(path):
    fp = fingerprint(path)
    m = json.loads(run([binary('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path], True))
    streams = m.get('streams', []); v = next((s for s in streams if s['codec_type'] == 'video'), None)
    a = next((s for s in streams if s['codec_type'] == 'audio'), None)
    duration = float(m.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0: raise ValueError(f'Invalid duration: {path}')
    rotation = 0
    if v:
        rotation = int(float(v.get('tags', {}).get('rotate', 0)))
        for side in v.get('side_data_list', []): rotation = int(side.get('rotation', rotation))
    return {'fingerprint': fp, 'duration': duration, 'video': v, 'audio': a, 'rotation': rotation}


def space(path, estimate):
    free = shutil.disk_usage(path).free
    if free < estimate: raise ValueError(f'Insufficient disk: need estimated {estimate/1e9:.2f} GB, free {free/1e9:.2f} GB')


def sources(project):
    result = {}
    for s in read(project / 'project.json')['sources']:
        p = Path(s['path'])
        if not p.is_absolute(): p = (project / p).resolve()
        fp = fingerprint(p)
        if fp != s['metadata']['fingerprint']:
            raise ValueError(f'Source changed: {s["id"]}; inspect and explicitly re-initialize/relink, do not reuse stale cache')
        result[s['id']] = {**s, 'path': str(p)}
    return result


def prepare(project, source_id, proxy=False):
    s = sources(project)[source_id]; m = s['metadata']
    if not m['audio']: raise ValueError('No audio stream; choose another audio source or explicitly plan a silent-video workflow')
    cache = project / 'cache' / 'prepare' / key([m['fingerprint'], proxy, 1]); cache.mkdir(parents=True, exist_ok=True)
    outputs = {}
    if proxy:
        if not m['video']: raise ValueError('No video for proxy')
        dest = cache / 'proxy.mp4'; part = cache / 'proxy.partial.mp4'
        if not dest.exists():
            space(cache, int(m['duration'] * 200000 + 100e6))
            ff('-y', '-i', s['path'], '-vf', 'scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=15', '-c:v', 'libx264', '-preset', 'fast', '-crf', '28', '-c:a', 'aac', '-b:a', '64k', part)
            part.replace(dest)
        outputs['proxy'] = str(dest)
    save(cache / 'prepared.json', {'source_id': source_id, 'outputs': outputs})
    return outputs


def chunk_windows(duration, chunk, overlap):
    if not all(math.isfinite(x) for x in [duration,chunk,overlap]) or duration <= 0 or chunk <= 0 or overlap < 0 or overlap >= chunk: raise ValueError('Require 0 <= overlap < chunk')
    start = 0.0
    while start < duration:
        end = min(duration, start + chunk)
        yield {'core_start': start, 'core_end': end, 'start': max(0, start-overlap/2), 'end': min(duration, end+overlap/2)}
        start = end


def owned_segments(segments, window):
    rows = []
    for seg in segments:
        words = []
        for w in seg['words']:
            a, b = w['start'] + window['start'], w['end'] + window['start']
            if window['core_start'] <= (a+b)/2 < window['core_end']:
                words.append({**w, 'start': a, 'end': b})
        if words: rows.append({'start': words[0]['start'], 'end': words[-1]['end'], 'text': ''.join(w['word'] for w in words).strip(), 'words': words})
    return rows


def transcribe(project, source_id, model, model_dir, language='zh', chunk=600, overlap=2, prompt='', limit=None, max_chunks=None, offline=True):
    from faster_whisper import WhisperModel
    s = sources(project)[source_id]; m = s['metadata']
    if limit is not None and (not math.isfinite(limit) or limit <= 0): raise ValueError('limit must be positive')
    if max_chunks is not None and max_chunks < 1: raise ValueError('max-new-chunks must be >=1')
    if not m['audio']: raise ValueError(f'{source_id} has no audio')
    duration = min(m['duration'], limit) if limit else m['duration']
    options = {'source': m['fingerprint'], 'model': model, 'model_dir': str(Path(model_dir).resolve()), 'language': language, 'chunk': chunk, 'overlap': overlap, 'prompt': prompt, 'duration': duration, 'engine': importlib.metadata.version('faster-whisper'), 'version': 1}
    cache = project / 'cache' / 'transcribe' / source_id / key(options); cache.mkdir(parents=True, exist_ok=True)
    save(cache / 'options.json', options)
    engine = None; rows = []; completed = 0
    windows = list(chunk_windows(duration, chunk, overlap))
    for i, window in enumerate(windows):
        dest = cache / f'{i:05}.json'
        if not dest.exists():
            if max_chunks is not None and completed >= max_chunks: break
            if engine is None:
                engine = WhisperModel(model, device='cpu', compute_type='int8', download_root=model_dir, local_files_only=offline)
            space(cache, int((window['end']-window['start'])*32000 + 100e6))
            wav = cache / f'{i:05}.wav'
            ff('-y', '-ss', window['start'], '-i', s['path'], '-t', window['end']-window['start'], '-vn', '-ar', '16000', '-ac', '1', wav)
            segments, info = engine.transcribe(str(wav), language=language, initial_prompt=prompt, word_timestamps=True, vad_filter=True)
            raw = [{'start': x.start, 'end': x.end, 'text': x.text, 'words': [{'start': w.start, 'end': w.end, 'word': w.word, 'probability': w.probability} for w in (x.words or [])]} for x in segments]
            save(dest, {'window': window, 'segments': raw, 'language': info.language})
            completed += 1
        data = read(dest); rows.extend(owned_segments(data['segments'], window))
        print(f'chunk {i+1}/{len(windows)} ready', flush=True)
    complete = all((cache / f'{i:05}.json').exists() for i in range(len(windows)))
    merged = {'source_id': source_id, 'source_path': s['path'], 'options': options, 'complete': complete, 'scope': 'sample' if duration < m['duration'] else 'full', 'segments': rows, 'status': 'machine'}
    save(cache / 'merged.json', merged)
    return {'transcript': str(cache / 'merged.json'), 'complete': complete, 'new_chunks': completed, 'scope': merged['scope']}
