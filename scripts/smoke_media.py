#!/usr/bin/env python3
"""Real FFmpeg/backend smoke test using generated media, never human footage."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_harness import core as c
from video_harness.package import package


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--backend',default=None);p.add_argument('--runtime',default=str(c.default_runtime()));p.add_argument('--output',required=True)
    a=p.parse_args();root=Path(a.output).resolve()
    if root.exists():raise ValueError('Use a new output directory')
    root.mkdir(parents=True);runtime=c.read(a.runtime)
    source=root/'synthetic.mp4'
    subprocess.run([runtime['ffmpeg'],'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25:duration=6','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=6','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
    legacy=root/'editor';env=os.environ.copy();env['THE_RUNTIME_CONFIG']=str(Path(a.runtime).resolve())
    subprocess.run([sys.executable,str(c.backend_path(a.backend)),'init','--project',str(legacy),str(source)],check=True,env=env,stdout=subprocess.DEVNULL)
    plan=c.read(legacy/'plan.json');plan.update(width=640,height=360,fps=25,title='合成验证',clips=[{'id':'E1','source_id':'S001','start':0,'end':6,'framing':'fit'}],chapters=[]);c.save(legacy/'plan.json',plan)
    caps=[]
    for i,(start,end) in enumerate([(1,2),(3,4)]):
        caps.append(dict(id='C'+str(i),start=start,end=end,text='测试句'+str(i),speaker='测试',spoken_text='测试句'+str(i),status='machine',source=dict(source_id='S001',edit_id='E1',start=start,end=end)))
    c.save(legacy/'captions.json',dict(version=1,captions=caps))
    style=c.read(legacy/'style.json');style['endcard']['enabled']=False;style['intro_seconds']=0;c.save(legacy/'style.json',style)
    project=root/'workflow';c.import_editor(project,legacy,a.backend,a.runtime)
    c.edit(project,[dict(id='C1',keep=False)],c.gate_hash(project,'script'))
    for gate in ['topic','script']:c.approve(project,gate,c.gate_hash(project,gate),'SYNTHETIC FIXTURE ONLY — no human content approval','test')
    built=c.compile_project(project)
    assert built['body_duration']==5, built
    result=c.render(project)
    verification=c.read(Path(result['export'])/'verification.json')
    assert verification['duration']==5, verification
    assert 'C1' not in [r['id'] for r in c.read(Path(result['export'])/'captions.json')['captions']]
    copy=c.read(project/'copy.json');copy.update(description='合成媒体测试，不作为真实内容发布',tags=['测试'],cover_lines=['合成验证'],cover_size=[600,800]);c.save(project/'copy.json',copy)
    draft=package(project,True)
    try:package(project)
    except c.HarnessError:pass
    else:raise AssertionError('Final package bypassed film gate')
    c.approve(project,'film',c.gate_hash(project,'film'),'SYNTHETIC FIXTURE ONLY — no human content approval','test')
    final=package(project)
    c.save(root/'result.json',dict(passed=True,body_duration=5,decode=verification['decode'],draft=draft,final=final,fixture_only=True))
    print(json.dumps(c.read(root/'result.json'),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
