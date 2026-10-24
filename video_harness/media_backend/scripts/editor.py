#!/usr/bin/env python3
"""Local talking-head workflow. Run --help for commands; never uploads media."""
import argparse, json, math, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from media import read, save, key, run, ff, probe, sources, space, binary, transcribe, prepare

SKILL = Path(__file__).resolve().parents[1]
STATUSES = {'machine', 'compared', 'user_confirmed', 'needs_review'}


def status(project, stage, details):
    path=project/'state.json'; state=read(path) if path.exists() else {}
    state[stage]={'updated_unix':time.time(),**details};save(path,state)


def stamp(t):
    n=round(t*1000);h,n=divmod(n,3600000);m,n=divmod(n,60000);s,n=divmod(n,1000);return f'{h:02}:{m:02}:{s:02},{n:03}'


def doctor(a):
    from importlib import metadata
    report={'python':sys.version.split()[0], 'executables':{},'packages':{}}
    for name in ['ffmpeg','ffprobe']:
        try:report['executables'][name]=run([binary(name),'-version'],True).splitlines()[0]
        except Exception as e:report['executables'][name]={'error':str(e)}
    for name in ['faster-whisper','Pillow']:
        try:report['packages'][name]=metadata.version(name)
        except metadata.PackageNotFoundError:report['packages'][name]='missing'
    try:
        from graphics import font_path
        report['font']=font_path({})
        from PIL import ImageFont
        ImageFont.truetype(report['font'],24)
    except Exception as e:report['font']={'error':str(e)}
    report['model_dir']=a.model_dir
    report['model_directory_exists']=Path(a.model_dir).is_dir() if a.model_dir else False
    report['model_ready']='not_checked'
    report['ready']=all(isinstance(v,str) for v in report['executables'].values()) and report['packages']['Pillow']!='missing' and isinstance(report['font'],str)
    if getattr(a,'transcription',False):
        try:
            import faster_whisper
            report['transcription_import']='passed'
        except Exception as e:
            report['transcription_import']={'error':str(e)}
            report['ready']=False
    try:report['ass_available']=' ass ' in run([binary('ffmpeg'),'-hide_banner','-filters'],True)
    except Exception:report['ass_available']=False
    return report


def initialize(a):
    p=Path(a.project).resolve()
    if p.exists() and any(p.iterdir()):raise ValueError('Project directory must be new/empty')
    assets=[]
    for i,path in enumerate(a.inputs,1):
        path=Path(path).resolve();assets.append({'id':f'S{i:03}','path':str(path),'metadata':probe(path)})
    p.mkdir(parents=True,exist_ok=True)
    save(p/'project.json',{'version':1,'sources':assets})
    save(p/'plan.json',{'version':1,'width':1080,'height':1920,'fps':30,'title':'','chapters':[],'clips':[{'id':f'E{i:03}','source_id':s['id'],'start':0,'end':s['metadata']['duration'],'framing':'fit'} for i,s in enumerate(assets,1)]})
    save(p/'captions.json',{'version':1,'captions':[]})
    save(p/'style.json',read(SKILL/'assets/style-default.json'))
    status(p,'init',{'complete':True});return {'project':str(p),'sources':[s['id'] for s in assets]}


def timeline_signature(plan):
    return key([plan['fps'],[(c['id'],c['source_id'],c['start'],c['end']) for c in plan['clips']]])


def load_project(project):
    p=Path(project).resolve();src=sources(p);plan=read(p/'plan.json');style=read(p/'style.json');caption_data=read(p/'captions.json');caps=caption_data['captions']
    w,h,fps=plan['width'],plan['height'],plan['fps']
    if caption_data.get('timeline_signature') and caption_data['timeline_signature'] != timeline_signature(plan):raise ValueError('Edit timeline changed; remap source-anchored captions before rendering')
    if not isinstance(w,int) or not isinstance(h,int) or min(w,h)<64 or w%2 or h%2:raise ValueError('Use positive even output dimensions >=64')
    if not isinstance(fps,(int,float)) or not math.isfinite(fps) or not 1<=fps<=120:raise ValueError('Invalid fps')
    pos=0;seen=set()
    for clip in plan['clips']:
        if clip['id'] in seen:raise ValueError('Duplicate clip ID')
        seen.add(clip['id']);s=src[clip['source_id']];m=s['metadata']
        if not m['video'] or not m['audio']:raise ValueError(f'{s["id"]}: video and audio required; explicitly resolve missing streams')
        if not 0<=clip['start']<clip['end']<=m['duration']+.001:raise ValueError('Clip outside source duration')
        count=round((clip['end']-clip['start'])*fps)
        if count<1:raise ValueError('Clip shorter than one output frame')
        clip.update(frames=count,timeline_start=pos/fps,timeline_end=(pos+count)/fps);pos+=count
        if clip.get('framing','fit') not in ['fit','crop']:raise ValueError('framing must be fit or crop')
        if clip.get('framing')=='crop':
            x,y,cw,ch=clip['crop'];vw,vh=m['video']['width'],m['video']['height']
            if abs(m['rotation'])%180==90:vw,vh=vh,vw
            if any(not isinstance(v,int) or v%2 for v in [x,y,cw,ch]) or min(x,y)<0 or min(cw,ch)<=0 or x+cw>vw or y+ch>vh:raise ValueError('Crop must be explicit even pixels within rotated display dimensions')
    if not plan['clips']:raise ValueError('Empty edit plan')
    previous=0;ids=set()
    for c in caps:
        if c['id'] in ids:raise ValueError('Duplicate caption ID')
        ids.add(c['id'])
        if not previous<=c['start']<c['end']<=pos/fps+.001:raise ValueError(f'Invalid/overlapping caption: {c["id"]}')
        if c.get('status') not in STATUSES:raise ValueError('Caption status must be machine/compared/user_confirmed/needs_review')
        if not c['text'].strip():raise ValueError('Empty caption')
        previous=c['end']
    prior=-1
    for c in plan.get('chapters',[]):
        if not prior<c['start']<pos/fps:raise ValueError('Chapter times must increase and remain within body')
        prior=c['start']
    for field in ['font_size','title_size','chapter_size']:
        if not isinstance(style[field],(int,float)) or not 10<=style[field]<=200:raise ValueError('Invalid font size')
    for value in style['colors'].values():
        if not isinstance(value,str) or len(value)!=7 or not value.startswith('#'):raise ValueError('Colors must use #RRGGBB')
        int(value[1:],16)
    if any(v not in style['colors'] for v in style.get('keywords',{}).values()):raise ValueError('Unknown keyword color')
    for field,lo,hi in [('contrast',.5,2),('brightness',-.5,.5),('saturation',0,2),('gamma',.5,2)]:
        value=style['grade'][field]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('Invalid grade parameter')
    for field,lo,hi in [('highpass',0,200),('lufs',-40,-8),('true_peak',-12,0)]:
        value=style['audio'][field]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('Invalid audio parameter')
    end=style.get('endcard',{})
    if len(end.get('points',[]))>3:raise ValueError('Endcard supports at most three short points')
    if not 0<=end.get('seconds',4)<=15:raise ValueError('Endcard duration outside 0..15 seconds')
    return p,src,plan,caps,style


def exports(p,caps,graphics,dest):
    dest.mkdir(parents=True,exist_ok=True)
    (dest/'subtitles.srt').write_text('\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["end"])}\n'+ '\n'.join(graphics.wrapped[c['id']]) for i,c in enumerate(caps,1))+'\n',encoding='utf-8')
    md='# 字幕校对表\n\n按编号、原句或成片时间提出修改；修改后需重新渲染硬字幕。\n\n| 编号 | 开始 | 结束 | 文字 | 状态 |\n|---|---|---|---|---|\n'
    for c in caps:md+='| '+' | '.join([c['id'],stamp(c['start']),stamp(c['end']),c['text'].replace('|','／').replace('\n',' / '),c['status']])+' |\n'
    (dest/'caption-review.md').write_text(md,encoding='utf-8')


def map_captions(a):
    p,src,plan,_,style=load_project(a.project)
    old=read(p/'captions.json')
    if old['captions']:raise ValueError('Existing captions preserved; do not remap over user corrections. Use a new project/version for changed edits')
    transcripts={}
    for path in a.transcripts:
        data=read(path)
        if not data.get('complete'):raise ValueError('Incomplete transcript; resume or explicitly select a completed sample')
        sid=data['source_id']
        if data['options']['source'] != src[sid]['metadata']['fingerprint']:raise ValueError('Transcript/source mismatch')
        transcripts[sid]=data
    rows=[]
    for clip in plan['clips']:
        data=transcripts[clip['source_id']]
        if clip['end']>data['options']['duration']+.001:raise ValueError('Selected clip exceeds transcribed range')
        for seg in data['segments']:
            if seg['end']<=clip['start'] or seg['start']>=clip['end']:continue
            words=[w for w in seg.get('words',[]) if clip['start'] <= (w['start']+w['end'])/2 < clip['end']]
            if not words:continue
            start=max(clip['start'],words[0]['start']);end=min(clip['end'],words[-1]['end'])
            # Keep source anchors and let editor split long utterances before render.
            offset=clip['timeline_start']-clip['start']
            rows.append({'id':f'C{len(rows)+1:04}','start':start+offset,'end':min(clip['timeline_end'],end+offset),'text':''.join(w['word'] for w in words).strip(),'status':'machine','source':{'source_id':clip['source_id'],'start':start,'end':end,'edit_id':clip['id']}})
    save(p/'captions.json',{'version':1,'timeline_signature':timeline_signature(plan),'captions':rows});return {'captions':len(rows),'next':'Review wording, split long utterances at word timestamps, then preview'}


def patch_caption(a):
    p=Path(a.project).resolve();path=p/'captions.json';original=read(path);candidate=json.loads(json.dumps(original));c=next((c for c in candidate['captions'] if c['id']==a.id),None)
    if c is None:raise ValueError('Caption ID not found')
    before=dict(c)
    if a.text is not None:c['text']=a.text
    if a.start is not None:c['start']=a.start
    if a.end is not None:c['end']=a.end
    if a.status is not None:c['status']=a.status
    # Validate without changing the source master on failure.
    ordered=candidate['captions'];last=0
    _,_,plan,_,_=load_project(p);duration=plan['clips'][-1]['timeline_end']
    for row in ordered:
        if not last<=row['start']<row['end']<=duration or not row['text'].strip():raise ValueError('Correction creates empty/overlapping/out-of-range caption')
        last=row['end']
    history=p/'history';history.mkdir(exist_ok=True);save(history/f'captions-{time.time_ns()}.json',original)
    save(path,candidate);save(history/f'change-{time.time_ns()}.json',{'id':a.id,'before':before,'after':c})
    return {'changed':a.id,'next':'preview/render; no transcription needed'}


def base_video(p,src,plan):
    fps,w,h=plan['fps'],plan['width'],plan['height'];clips=[]
    for c in plan['clips']:
        s=src[c['source_id']];finger=key([{k:v for k,v in c.items() if k not in ['timeline_start','timeline_end']},s['metadata']['fingerprint'],w,h,fps,2])
        cache=p/'cache'/'clips'/finger;cache.mkdir(parents=True,exist_ok=True);dest=cache/'clip.mp4'
        if not dest.exists():
            duration=c['frames']/fps;space(cache,int(duration*w*h*.7+50e6));part=cache/'clip.partial.mp4'
            crop='crop='+':'.join(map(str,[c['crop'][2],c['crop'][3],c['crop'][0],c['crop'][1]]))+',' if c.get('framing')=='crop' else ''
            vf=crop+f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS,fps={fps}:start_time=0,tpad=stop_mode=clone:stop_duration=1'
            ff('-y','-ss',c['start'],'-i',s['path'],'-map','0:v:0','-map','0:a:0','-vf',vf,'-af',f'aresample=48000,asetpts=PTS-STARTPTS,apad,atrim=duration={duration}', '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ac','2','-t',duration,part)
            meta=probe(part)
            if int(meta['video'].get('nb_frames',0))!=c['frames']:raise RuntimeError('Unexpected normalized clip frame count')
            part.replace(dest)
        clips.append(dest)
    cache=p/'cache'/'base'/key([str(x) for x in clips]);cache.mkdir(parents=True,exist_ok=True);dest=cache/'base.mp4'
    if not dest.exists():
        # Controlled names avoid shell/concat escaping for arbitrary user paths.
        for i,path in enumerate(clips):
            link=cache/f'clip-{i:05}.mp4'
            if not link.exists():link.symlink_to(path)
        manifest=cache/'concat.txt';manifest.write_text(''.join(f"file 'clip-{i:05}.mp4'\n" for i in range(len(clips))))
        part=cache/'base.partial.mp4'
        ff('-y','-f','concat','-safe','1','-i',manifest,'-c:v','copy','-af','aresample=async=1:first_pts=0','-c:a','aac','-b:a','192k','-t',plan['clips'][-1]['timeline_end'],part);part.replace(dest)
    return dest


def graphics_for(p,plan,caps,style):
    from graphics import Graphics
    g=Graphics(plan,caps,style)
    # Validate all chapters and closing before expensive encoding.
    for t in [0,*[c['start']+.5 for c in plan.get('chapters',[])],g.duration+.5]:g.layer(t)
    return g


def preview(a):
    from PIL import Image
    p,src,plan,caps,style=load_project(a.project);g=graphics_for(p,plan,caps,style);base=base_video(p,src,plan)
    body=plan['clips'][-1]['timeline_end'];end=style['endcard']['seconds'] if style['endcard']['enabled'] else 0
    if not 0<=a.time<body+end:raise ValueError('Preview timestamp outside output')
    dest=p/'previews'/f'{time.time_ns()}';dest.mkdir(parents=True)
    grade=style['grade'];vf=f'eq=contrast={grade["contrast"]}:brightness={grade["brightness"]}:saturation={grade["saturation"]}:gamma={grade["gamma"]}'
    ff('-y','-ss',min(a.time,max(0,body-1/plan['fps'])),'-i',base,'-frames:v','1','-vf',vf,dest/'base.png')
    im=Image.alpha_composite(Image.open(dest/'base.png').convert('RGBA'),g.layer(a.time));im.save(dest/'preview.png');exports(p,caps,g,dest)
    return {'preview':str(dest/'preview.png'),'backend':'Pillow design preview; inspect final frames for ASS path'}


def render(a):
    p,src,plan,caps,style=load_project(a.project);g=graphics_for(p,plan,caps,style)
    if not caps and not a.allow_no_captions:raise ValueError('No captions; review transcript first or explicitly use --allow-no-captions')
    filters=run([binary('ffmpeg'),'-hide_banner','-filters'],True);has_ass=' ass ' in filters
    backend=('ass' if has_ass else 'pillow') if a.backend=='auto' else a.backend
    if backend=='ass' and not has_ass:raise ValueError('ASS filter unavailable; choose Pillow or configure THE_FFMPEG')
    base=base_video(p,src,plan);body=g.duration;end=style['endcard']['seconds'] if style['endcard']['enabled'] else 0
    fps=plan['fps'];frames=round((body+end)*fps);duration=frames/fps
    signature=key([key([Path(__file__).read_text(),Path(__file__).with_name('graphics.py').read_text()]),plan,caps,style,backend,Path(g.fontfile).stat().st_mtime_ns,run([binary('ffmpeg'),'-version'],True).splitlines()[0],4])
    cache=p/'cache'/'render'/signature;cache.mkdir(parents=True,exist_ok=True);space(cache,int(duration*plan['width']*plan['height']*1.5+100e6))
    graphics=cache/'graphics.mov'
    if not graphics.exists():
        gf=15;part=cache/'graphics.partial.mov'
        proc=subprocess.Popen([binary('ffmpeg'),'-v','error','-y','-f','rawvideo','-pix_fmt','rgba','-s',f'{g.w}x{g.h}','-r',str(gf),'-i','-','-an','-c:v','qtrle','-pix_fmt','argb',str(part)],stdin=subprocess.PIPE)
        try:
            for i in range(math.ceil(duration*gf)):
                proc.stdin.write(g.layer(i/gf,captions=backend=='pillow').tobytes())
                if i%(gf*30)==0:print(f'graphics {i/gf:.0f}/{duration:.1f}s',flush=True)
            proc.stdin.close()
            if proc.wait():raise RuntimeError('Graphics encode failed')
        except BaseException:
            proc.terminate();proc.wait();raise
        part.replace(graphics)
    # Copy graphics inputs into a controlled cwd, avoiding ASS path quoting pitfalls.
    subtitle_filter=''
    if backend=='ass':
        (cache/'subtitles.ass').write_text(g.ass(),encoding='utf-8');fonts=cache/'fonts';fonts.mkdir(exist_ok=True)
        fontdest=fonts/('font'+Path(g.fontfile).suffix)
        if not fontdest.exists():shutil.copyfile(g.fontfile,fontdest)
        subtitle_filter=',ass=subtitles.ass:fontsdir=fonts'
    audio='anull'
    if style.get('audio',{}).get('normalize',True):
        ac=style['audio'];measure=cache/'loudness.json'
        if not measure.exists():
            result=subprocess.run([binary('ffmpeg'),'-hide_banner','-nostdin','-i',str(base),'-vn','-af',f'highpass=f={ac["highpass"]},loudnorm=I={ac["lufs"]}:TP={ac["true_peak"]}:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr[-3000:])
            tail=result.stderr[result.stderr.rfind('{'):];data=json.JSONDecoder().raw_decode(tail)[0];save(measure,data)
        m=read(measure)
        if all(math.isfinite(float(m[k])) for k in ['input_i','input_tp','input_lra','input_thresh','target_offset']):
            audio=f'highpass=f={ac["highpass"]},loudnorm=I={ac["lufs"]}:TP={ac["true_peak"]}:LRA=11:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}:measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true'
        else:audio=f'highpass=f={ac["highpass"]}'
    grade=style['grade'];vf=f'fps={fps},eq=contrast={grade["contrast"]}:brightness={grade["brightness"]}:saturation={grade["saturation"]}:gamma={grade["gamma"]},tpad=stop_mode=clone:stop_duration={end+1},trim=duration={duration},setpts=PTS-STARTPTS'
    final=cache/'final.mp4'
    if not final.exists():
        part=cache/'final.partial.mp4';graph=f'[0:v]{vf}[base];[base][1:v]overlay=0:0{subtitle_filter},fps={fps},tpad=stop_mode=clone:stop_duration=1,trim=end_frame={frames},setpts=N/({fps}*TB)[v];[0:a]{audio},aresample=48000,apad,atrim=duration={duration}[a]'
        args=[binary('ffmpeg'),'-v','error','-nostdin','-y','-i',str(base),'-i',str(graphics),'-filter_complex',graph,'-map','[v]','-map','[a]','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-r',str(fps),'-frames:v',str(frames),'-t',str(duration),'-movflags','+faststart',str(part)]
        result=subprocess.run(args,cwd=cache,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr[-6000:])
        part.replace(final)
    version=p/'exports'/f'{time.strftime("%Y%m%d-%H%M%S")}-{time.time_ns()%1000000:06}-{signature[:6]}'
    version.mkdir(parents=True);shutil.copy2(final,version/'video.mp4');exports(p,caps,g,version)
    for name,value in [('plan.json',plan),('captions.json',{'version':1,'captions':caps}),('style.json',style)]:save(version/name,value)
    save(version/'manifest.json',{'backend':backend,'body_duration':body,'duration':duration,'expected_frames':frames,'signature':signature,'project':str(p),'source_fingerprints':{k:s['metadata']['fingerprint'] for k,s in src.items()},'font_file':g.fontfile})
    status(p,'render',{'complete':True,'export':str(version),'signature':signature})
    return {'export':str(version),'video':str(version/'video.mp4'),'backend':backend,'next':'verify and inspect representative final frames; caption truth still requires listening/user confirmation'}


def verify(a):
    p=Path(a.export).resolve();manifest=read(p/'manifest.json');m=probe(p/'video.mp4');plan=read(p/'plan.json');caps=read(p/'captions.json')['captions']
    if not m['audio'] or not m['video']:raise ValueError('Missing output stream')
    if abs(m['duration']-manifest['duration'])>1/plan['fps']+.025:raise ValueError('Unexpected output duration')
    if int(m['video'].get('nb_frames',0))!=manifest['expected_frames']:raise ValueError(f'Unexpected output frame count: {m["video"].get("nb_frames")} vs {manifest["expected_frames"]}')
    ff('-i',p/'video.mp4','-f','null','-')
    sound=subprocess.run([binary('ffmpeg'),'-hide_banner','-i',str(p/'video.mp4'),'-vn','-af','loudnorm=print_format=json','-f','null','-'],capture_output=True,text=True)
    if sound.returncode:raise RuntimeError(sound.stderr[-3000:])
    meter=json.JSONDecoder().raw_decode(sound.stderr[sound.stderr.rfind('{'):])[0]
    warnings=[]
    for c in caps:
        chars=len(c['text'].replace('\n',''));seconds=c['end']-c['start']
        if seconds<.83 or chars/seconds>11:warnings.append({'id':c['id'],'duration':seconds,'chars_per_second':round(chars/seconds,2),'reason':'Review reading speed; do not shorten speech automatically'})
    report={'decode':'passed','duration':m['duration'],'frames':int(m['video']['nb_frames']),'integrated_lufs':meter['input_i'],'true_peak_dbtp':meter['input_tp'],'caption_warnings':warnings,'needs_review':[c['id'] for c in caps if c['status'] in ['machine','needs_review']],'human_audio_review':'not_asserted','visual_review':'not_asserted'}
    save(p/'verification.json',report);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='cmd',required=True)
    d=sub.add_parser('doctor');d.add_argument('--model-dir',default=os.environ.get('THE_MODEL_DIR'));d.add_argument('--transcription',action='store_true');d.set_defaults(func=doctor)
    i=sub.add_parser('init');i.add_argument('--project',required=True);i.add_argument('inputs',nargs='+');i.set_defaults(func=initialize)
    for name in ['prepare','transcribe','map-captions','patch-caption','preview','render']:
        a=sub.add_parser(name);a.add_argument('--project',required=True)
        if name in ['prepare','transcribe']:a.add_argument('--source',required=True)
        if name=='prepare':
            a.add_argument('--proxy',action='store_true');a.set_defaults(func=lambda a:prepare(Path(a.project).resolve(),a.source,a.proxy))
        if name=='transcribe':
            a.add_argument('--model',default='small');a.add_argument('--model-dir',default=os.environ.get('THE_MODEL_DIR',str(Path.home()/'.cache/video-harness/models')));a.add_argument('--language',default='zh');a.add_argument('--chunk',type=float,default=600);a.add_argument('--overlap',type=float,default=2);a.add_argument('--prompt',default='简体中文。');a.add_argument('--limit',type=float);a.add_argument('--max-new-chunks',type=int);a.add_argument('--allow-download',action='store_true');a.set_defaults(func=lambda a:transcribe(Path(a.project).resolve(),a.source,a.model,a.model_dir,a.language,a.chunk,a.overlap,a.prompt,a.limit,a.max_new_chunks,not a.allow_download))
        if name=='map-captions':a.add_argument('transcripts',nargs='+');a.set_defaults(func=map_captions)
        if name=='patch-caption':
            a.add_argument('--id',required=True);a.add_argument('--text');a.add_argument('--start',type=float);a.add_argument('--end',type=float);a.add_argument('--status',choices=sorted(STATUSES));a.set_defaults(func=patch_caption)
        if name=='preview':a.add_argument('--time',type=float,required=True);a.set_defaults(func=preview)
        if name=='render':a.add_argument('--backend',choices=['auto','ass','pillow'],default='auto');a.add_argument('--allow-no-captions',action='store_true');a.set_defaults(func=render)
    v=sub.add_parser('verify');v.add_argument('--export',required=True);v.set_defaults(func=verify)
    a=parser.parse_args()
    try:
        result=a.func(a)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if a.cmd=='doctor' and not result['ready']: sys.exit(1)
    except (ValueError,RuntimeError,KeyError,FileNotFoundError) as e:
        print(json.dumps({'error':str(e),'command':a.cmd},ensure_ascii=False),file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
