"""Local, revision-bound editorial workflow. No model or cloud calls."""
from __future__ import annotations
import contextlib
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

VERSION = '0.1.0'

class HarnessError(ValueError):
    pass

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def fingerprint(path):
    path = Path(path)
    stat = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as f:
        h.update(f.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            f.seek(max(0, stat.st_size - 1024 * 1024))
            h.update(f.read(1024 * 1024))
    return dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns, sample_sha256=h.hexdigest())

@contextlib.contextmanager
def lock(project):
    # flock releases automatically after an interrupted render, unlike sentinel locks.
    import fcntl
    with (Path(project) / '.lock').open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise HarnessError('项目正在被另一操作使用，请稍后重试') from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def event(p, action, **details):
    with (p / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(at=now(), action=action, **details), ensure_ascii=False) + '\n')

def config(p):
    c = read(Path(p) / 'harness.json')
    if c.get('schema_version') != 1:
        raise HarnessError('不支持的项目版本')
    return c

def backend_hash(p):
    c = config(p)
    runner = Path(c['backend'])
    if not runner.is_file():
        raise HarnessError('找不到媒体后端；请配置 talking-head-editor/scripts/run.py')
    files = {x.name: file_hash(x) for x in sorted(runner.parent.glob('*.py'))}
    runtime = Path(c['runtime']) if c.get('runtime') else None
    files['runtime'] = file_hash(runtime) if runtime and runtime.is_file() else None
    # Binary/font replacement at the same configured path must invalidate a build.
    if runtime and runtime.is_file():
        rc = read(runtime)
        files['tools'] = {k: fingerprint(rc[k]) for k in ['python', 'ffmpeg', 'ffprobe', 'font'] if rc.get(k)}
    return digest(files)

def origin(p):
    p = Path(p)
    c = config(p)
    names = ['project.json', 'plan.json', 'captions.json', 'style.json']
    values = {n: read(p / 'original' / n) for n in names}
    if digest(values) != c['original_hash']:
        raise HarnessError('原始工程快照被修改；不能沿用确认或编译')
    for s in values['project.json']['sources']:
        if fingerprint(s['path']) != s['metadata']['fingerprint']:
            raise HarnessError('源文件发生变化或不可用：' + s['id'])
    return values

def validate_story(p, story):
    o = origin(p)
    originals = {r['id']: r for r in o['captions.json']['captions']}
    rows = story['units']
    if len(rows) != len(originals) or {r['id'] for r in rows} != set(originals):
        raise HarnessError('句 ID 必须与原稿一致；删除使用 keep=false，不删除记录')
    if [r['id'] for r in rows] != list(originals):
        raise HarnessError('v0.1 不支持重排句子；请调整源选段并重新导入')
    for r in rows:
        base = originals[r['id']]
        if r['source'] != base['source'] or r['original_text'] != base.get('spoken_text', base['text']):
            raise HarnessError('禁止修改原话或源锚点：' + r['id'])
        if type(r['keep']) is not bool or not isinstance(r['text'], str) or not r['text'].strip():
            raise HarnessError('无效的删留/字幕：' + r['id'])
        if not isinstance(r['speaker'], str) or len(r['speaker']) > 80:
            raise HarnessError('无效说话人')
    return o

def validate_original(o):
    plan = o['plan.json']
    fps = plan['fps']
    if not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise HarnessError('无效帧率')
    src = {s['id']: s for s in o['project.json']['sources']}
    clips = {}
    for c in plan['clips']:
        if c['id'] in clips or c['source_id'] not in src:
            raise HarnessError('重复片段 ID 或未知素材')
        if not 0 <= c['start'] < c['end'] <= src[c['source_id']]['metadata']['duration']:
            raise HarnessError('选段越过素材边界')
        clips[c['id']] = c
    if not clips:
        raise HarnessError('选段为空')
    ids, previous = set(), {}
    for r in o['captions.json']['captions']:
        a = r.get('source', {})
        c = clips.get(a.get('edit_id'))
        if r['id'] in ids or not c or a.get('source_id') != c['source_id']:
            raise HarnessError('字幕 ID 重复或缺少有效源锚点')
        if not c['start'] <= a['start'] < a['end'] <= c['end'] + .001:
            raise HarnessError('字幕源锚点越界：' + r['id'])
        if a['start'] < previous.get(c['id'], -1):
            raise HarnessError('字幕源锚点重叠或乱序')
        previous[c['id']] = a['end']
        ids.add(r['id'])

def import_editor(destination, source, backend, runtime=None, source_map=None):
    p, source = Path(destination).resolve(), Path(source).resolve()
    if p.exists():
        raise HarnessError('目标目录已存在；使用 status/resume，不覆盖')
    if p == source or source in p.parents:
        raise HarnessError('工作流项目不能创建在原工程内')
    o = {n: read(source / n) for n in ['project.json', 'plan.json', 'captions.json', 'style.json']}
    for s in o['project.json']['sources']:
        path = Path((source_map or {}).get(s['id'], s['path']))
        s['path'] = str((source / path).resolve() if not path.is_absolute() else path.resolve())
        if fingerprint(s['path']) != s['metadata']['fingerprint']:
            raise HarnessError('源身份不匹配：' + s['path'])
    validate_original(o)
    p.mkdir(parents=True)
    for n, v in o.items():
        save(p / 'original' / n, v)
    save(p / 'harness.json', dict(schema_version=1, created_at=now(), imported_from=str(source),
         original_hash=digest(o), backend=str(Path(backend).resolve()),
         runtime=str(Path(runtime).resolve()) if runtime else None))
    title = o['plan.json'].get('title', '待确认选题')
    save(p / 'topic.json', dict(title=title, audience='', promise='', rationale='', must_keep=[], exclusions=[], candidates=[]))
    units = []
    for r in o['captions.json']['captions']:
        speaker = r.get('speaker', '')
        text = r['text']
        if speaker and text.startswith('【' + speaker + '】'):
            text = text[len(speaker) + 2:]
        units.append(dict(id=r['id'], source=r['source'], original_text=r.get('spoken_text', r['text']),
                          text=text, speaker=speaker, keep=True, review_status=r.get('status', 'needs_review')))
    save(p / 'story.json', dict(units=units))
    save(p / 'style.json', o['style.json'])
    save(p / 'copy.json', dict(title=title, description='', tags=[], cover_lines=['表达', '让你重新认识自己'],
                               cover_size=[900, 1200], platform='未指定，比例为设计稿'))
    save(p / 'approvals.json', {})
    event(p, 'import', source=str(source), approvals_inherited=False, verified_relocations=source_map or {})
    review_markdown(p)
    return status(p)

def gate_hash(p, gate):
    o = origin(p)
    topic = read(p / 'topic.json')
    if gate == 'topic':
        return digest([config(p)['original_hash'], topic])
    story = read(p / 'story.json')
    validate_story(p, story)
    if gate == 'script':
        return digest([gate_hash(p, 'topic'), story])
    if gate == 'film':
        r = current_render(p)
        return digest([r['input_hash'], r['video_sha256'], r['verification_sha256']])
    raise HarnessError('未知确认节点')

def approval_valid(p, gate):
    try:
        a = read(p / 'approvals.json').get(gate)
        valid = bool(a and a['hash'] == gate_hash(p, gate))
        if gate == 'script':
            valid = valid and approval_valid(p, 'topic')
        if gate == 'film':
            valid = valid and approval_valid(p, 'script')
        return valid
    except (OSError, ValueError, KeyError):
        return False

def approve(p, gate, expected, evidence, channel='chat'):
    p = Path(p)
    if not evidence.strip():
        raise HarnessError('必须提供用户针对当前版本的确认原话')
    with lock(p):
        current = gate_hash(p, gate)
        if current != expected:
            raise HarnessError('版本冲突：当前内容已改变，请重新展示后确认')
        dependency = {'script': 'topic', 'film': 'script'}.get(gate)
        if dependency and not approval_valid(p, dependency):
            raise HarnessError('前一阶段尚未确认：' + dependency)
        a = read(p / 'approvals.json')
        a[gate] = dict(hash=current, at=now(), evidence=evidence, channel=channel)
        save(p / 'approvals.json', a)
        event(p, 'approve', gate=gate, hash=current, channel=channel)
    return status(p)

def edit(p, changes, expected):
    p = Path(p)
    with lock(p):
        if gate_hash(p, 'script') != expected:
            raise HarnessError('版本冲突，未写入；请刷新后修改')
        story = read(p / 'story.json')
        rows = {r['id']: r for r in story['units']}
        for change in changes:
            if change.get('id') not in rows or set(change) - {'id', 'text', 'speaker', 'keep'}:
                raise HarnessError('只允许修改已存在句子的字幕、说话人与删留')
            rows[change['id']].update({k: v for k, v in change.items() if k != 'id'})
        validate_story(p, story)
        save(p / 'history' / (uuid.uuid4().hex + '.json'), read(p / 'story.json'))
        save(p / 'story.json', story)
        event(p, 'edit', ids=[c['id'] for c in changes])
        review_markdown(p)
    return status(p)

def compile_inputs(p):
    o = origin(p)
    story = read(p / 'story.json')
    validate_story(p, story)
    return digest([VERSION, o, read(p / 'topic.json'), story, read(p / 'style.json'), backend_hash(p)])

def compile_project(p):
    """Subtract deleted source intervals, retaining all other sound/pauses."""
    p = Path(p)
    signature = compile_inputs(p)
    dest = p / 'builds' / signature[:20]
    o = origin(p)
    plan = copy.deepcopy(o['plan.json'])
    plan['title'] = read(p / 'topic.json')['title']
    rows = read(p / 'story.json')['units']
    fps = plan['fps']
    pieces = []
    mappings = []
    position = 0
    old_position = 0
    for clip in plan['clips']:
        related = [r for r in rows if r['source']['edit_id'] == clip['id']]
        cuts = sorted((r['source']['start'], r['source']['end']) for r in related if not r['keep'])
        spans, cursor = [], clip['start']
        for start, end in cuts:
            # Cut boundaries snap outward relative to source clip frame grid.
            start = clip['start'] + math.floor((start - clip['start']) * fps + 1e-7) / fps
            end = min(clip['end'], clip['start'] + math.ceil((end - clip['start']) * fps - 1e-7) / fps)
            if start > cursor:
                spans.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < clip['end']:
            spans.append((cursor, clip['end']))
        for index, (start, end) in enumerate(spans):
            frames = round((end - start) * fps)
            if frames < 1:
                continue
            part = {**clip, 'id': clip['id'] + '-P' + str(index + 1), 'start': start, 'end': end}
            for k in ['frames', 'timeline_start', 'timeline_end']:
                part.pop(k, None)
            pieces.append(part)
            mappings.append(dict(edit=clip['id'], new_id=part['id'], start=start, end=end,
                                 output=position/fps, output_end=(position+frames)/fps,
                                 old=old_position/fps + start - clip['start']))
            position += frames
        old_position += round((clip['end'] - clip['start']) * fps)
    if not pieces:
        raise HarnessError('没有保留的视频片段')
    caps = []
    for r in rows:
        if not r['keep']:
            continue
        a = r['source']
        matches = [m for m in mappings if m['edit'] == a['edit_id'] and m['start'] <= a['start'] + .001 and m['end'] >= a['end'] - .001]
        if len(matches) != 1:
            raise HarnessError('删句边界影响邻句，需要回听调整：' + r['id'])
        m = matches[0]
        start = max(m['output'], round((m['output'] + a['start'] - m['start']) * fps) / fps)
        end = min(m['output_end'], round((m['output'] + a['end'] - m['start']) * fps) / fps)
        caps.append(dict(id=r['id'], start=start, end=end, text=('【'+r['speaker']+'】' if r['speaker'] else '')+r['text'],
                         spoken_text=r['original_text'], speaker=r['speaker'], status=r['review_status'],
                         source={**a, 'edit_id': m['new_id']}))
    caps.sort(key=lambda c: c['start'])
    chapters = []
    for chapter in plan.get('chapters', []):
        t = chapter['start']
        for m in mappings:
            old_end = m['old'] + m['end'] - m['start']
            if t < old_end:
                mapped = m['output'] + max(0, t - m['old'])
                mapped = min(mapped, m['output_end'] - 1 / fps)
                if not chapters or mapped > chapters[-1]['start']:
                    chapters.append(dict(start=round(mapped, 3), title=chapter['title']))
                break
    plan.update(clips=pieces, chapters=chapters)
    timeline = [fps, [(c['id'], c['source_id'], c['start'], c['end']) for c in pieces]]
    timeline_signature = digest(timeline)[:20]
    payload = {'project.json': o['project.json'], 'plan.json': plan,
               'captions.json': dict(version=1, timeline_signature=timeline_signature, captions=caps),
               'style.json': read(p / 'style.json')}
    if dest.exists():
        for name, data in payload.items():
            if read(dest / name) != data:
                raise HarnessError('编译输出被修改，请保留现场并使用新项目版本')
    else:
        for name, data in payload.items():
            save(dest / name, data)
    return dict(project=str(dest), input_hash=signature, body_duration=position/fps,
                captions=len(caps), deleted=[r['id'] for r in rows if not r['keep']])

def current_render(p):
    p = Path(p)
    r = read(p / 'render.json')
    if r['input_hash'] != compile_inputs(p):
        raise HarnessError('成片过期，需要重新渲染')
    if file_hash(Path(r['export']) / 'video.mp4') != r['video_sha256']:
        raise HarnessError('成片文件已改变')
    if file_hash(Path(r['export']) / 'verification.json') != r['verification_sha256']:
        raise HarnessError('验证记录已改变')
    for name, expected in r.get('export_hashes', {}).items():
        if file_hash(Path(r['export']) / name) != expected:
            raise HarnessError('成片配套文件已改变：' + name)
    return r

def run_backend(p, arguments, log):
    c = config(p)
    env = os.environ.copy()
    if c.get('runtime'):
        env['THE_RUNTIME_CONFIG'] = c['runtime']
    with Path(log).open('w') as f:
        result = subprocess.run([sys.executable, c['backend'], *arguments], stdout=f, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        raise HarnessError('媒体后端失败，请查看日志：' + str(log))

def render(p, draft=False):
    p = Path(p)
    with lock(p):
        if not draft and not approval_valid(p, 'script'):
            raise HarnessError('正式渲染前请确认当前剪辑稿；审阅用可显式选择 --draft')
        built = compile_project(p)
        try:
            r = current_render(p)
            return dict(**r, reused=True)
        except (OSError, ValueError, KeyError):
            pass
        job = p / 'jobs' / uuid.uuid4().hex
        job.mkdir(parents=True)
        save(job / 'status.json', dict(state='running', started_at=now(), input_hash=built['input_hash']))
        try:
            run_backend(p, ['render', '--project', built['project']], job / 'render.log')
            state = read(Path(built['project']) / 'state.json')
            export = state.get('render', {}).get('export')
            if not export:
                raise HarnessError('后端未返回导出目录：' + json.dumps(state))
            run_backend(p, ['verify', '--export', export], job / 'verify.log')
            v = read(Path(export) / 'verification.json')
            if v.get('decode') != 'passed':
                raise HarnessError('导出解码验证未通过')
            if compile_inputs(p) != built['input_hash']:
                raise HarnessError('渲染时输入发生变化，结果保留但不登记为当前成片')
            r = dict(export=export, input_hash=built['input_hash'], created_at=now(), draft=draft,
                     video_sha256=file_hash(Path(export)/'video.mp4'),
                     verification_sha256=file_hash(Path(export)/'verification.json'), job=str(job),
                     export_hashes={name: file_hash(Path(export)/name) for name in ['subtitles.srt','plan.json','captions.json','style.json']})
            save(p / 'render.json', r)
            save(job / 'status.json', dict(state='complete', export=export))
            event(p, 'render', draft=draft, input_hash=built['input_hash'])
            return r
        except BaseException as e:
            save(job / 'status.json', dict(state='failed', error=str(e)))
            raise

def review_markdown(p):
    p = Path(p)
    topic = read(p / 'topic.json')
    rows = read(p / 'story.json')['units']
    lines = ['# ' + topic['title'], '', '待用户确认；识别疑点需回听。纠错不改变声音，删句会同步删除音视频。', '']
    for r in rows:
        a = r['source']
        lines += [f"- {'保留' if r['keep'] else '删除'} **{r['id']} · {r['speaker']}** [{a['start']:.2f}–{a['end']:.2f}s]：{r['text']}"]
    (p / 'review.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(p / 'review.md')

def status(p):
    p = Path(p)
    origin(p)
    validate_story(p, read(p / 'story.json'))
    gates = {}
    for gate in ['topic', 'script', 'film']:
        try:
            h = gate_hash(p, gate)
        except (OSError, ValueError, KeyError):
            h = None
        gates[gate] = dict(hash=h, approved=approval_valid(p, gate))
    pending = next((g for g in gates if not gates[g]['approved']), None)
    rows = read(p / 'story.json')['units']
    return dict(project=str(p), title=read(p / 'topic.json')['title'], gates=gates,
                next=pending or 'package', kept=sum(r['keep'] for r in rows),
                needs_review=[r['id'] for r in rows if r['keep'] and r['review_status'] in ['needs_review', 'machine']],
                semantic_review='not_asserted', published=False)
