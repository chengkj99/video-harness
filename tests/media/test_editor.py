"""Behavior tests use generated local media, no private fixtures or downloads."""
import argparse, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'video_harness/media_backend/scripts'))
import editor, media
from graphics import Graphics

class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="剪辑 test '");cls.root=Path(cls.tmp.name)
        cls.videos=[]
        for rate in [25,30]:
            dest=cls.root/f'源 {rate}.mp4'
            media.ff('-y','-f','lavfi','-i',f'testsrc2=size=320x240:rate={rate}','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',dest);cls.videos.append(dest)
        cls.silent=cls.root/'无声.mp4';media.ff('-y','-i',cls.videos[0],'-an','-c:v','copy',cls.silent)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def project(self,name='p',inputs=None):
        p=self.root/(name+str(len(list(self.root.iterdir()))));editor.initialize(SimpleNamespace(project=str(p),inputs=inputs or [str(self.videos[0])]))
        plan=media.read(p/'plan.json');plan.update(width=360,height=640,title='表达与 AI',chapters=[{'start':.5,'title':'分清事实'}]);media.save(p/'plan.json',plan)
        style=media.read(p/'style.json');style['endcard'].update(enabled=True,seconds=1,summary='表达前先分清',points=['事实 · 观点 · 立场']);media.save(p/'style.json',style)
        media.save(p/'captions.json',{'version':1,'captions':[{'id':'C025','start':.2,'end':1.7,'text':'但是呢，借助这些','status':'needs_review'}]});return p
    def test_ownership_boundaries(self):
        windows=list(media.chunk_windows(6,3,2));rows=[]
        for w in windows:
            rows+=media.owned_segments([{'words':[{'start':2.9-w['start'],'end':3.1-w['start'],'word':'边界词','probability':.9}]}],w)
        self.assertEqual(len(rows),1);self.assertAlmostEqual(rows[0]['start'],2.9)
        with self.assertRaises(ValueError):list(media.chunk_windows(6,2,2))
    def test_patch_preserves_identity_time_and_rejects_overlap(self):
        p=self.project();before=media.read(p/'captions.json')['captions'][0]
        editor.patch_caption(SimpleNamespace(project=str(p),id='C025',text='但是呢，借助AI',start=None,end=None,status='user_confirmed'))
        after=media.read(p/'captions.json')['captions'][0]
        self.assertEqual((before['id'],before['start'],before['end']),(after['id'],after['start'],after['end']))
        with self.assertRaises(ValueError):editor.patch_caption(SimpleNamespace(project=str(p),id='C025',text=None,start=None,end=99,status=None))
        self.assertEqual(after,media.read(p/'captions.json')['captions'][0]);self.assertTrue(list((p/'history').glob('change*')))
    def test_no_audio_and_missing_source(self):
        p=self.project(inputs=[str(self.silent)])
        with self.assertRaisesRegex(ValueError,'video and audio'):editor.load_project(p)
        p=self.project();project=media.read(p/'project.json');project['sources'][0]['path']=str(self.root/'missing.mp4');media.save(p/'project.json',project)
        with self.assertRaisesRegex(ValueError,'Source unavailable'):editor.load_project(p)
    def test_bad_crop_and_caption_overflow(self):
        p=self.project();plan=media.read(p/'plan.json');plan['clips'][0].update(framing='crop',crop=[0,0,640,480]);media.save(p/'plan.json',plan)
        with self.assertRaisesRegex(ValueError,'Crop'):editor.load_project(p)
        p=self.project();_,_,plan,caps,style=editor.load_project(p);caps[0]['text']='非常长的字幕'*20
        with self.assertRaisesRegex(ValueError,'fit two lines'):Graphics(plan,caps,style)
    def test_transcription_resume_cache(self):
        p=self.project();model=SimpleNamespace()
        def infer(*args,**kwargs):
            word=SimpleNamespace(start=.2,end=.7,word='测试',probability=.9);seg=SimpleNamespace(start=.2,end=.7,text='测试',words=[word]);return iter([seg]),SimpleNamespace(language='zh')
        model.transcribe=infer
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=lambda *a,**k:model)}),patch('media.importlib.metadata.version',return_value='test'):
            one=media.transcribe(p,'S001','fake',str(self.root),chunk=1,overlap=.2,max_chunks=1)
            self.assertFalse(one['complete']);first=Path(one['transcript']).parent/'00000.json';mtime=first.stat().st_mtime_ns
            two=media.transcribe(p,'S001','fake',str(self.root),chunk=1,overlap=.2)
            self.assertTrue(two['complete']);self.assertEqual(two['new_chunks'],1);self.assertEqual(first.stat().st_mtime_ns,mtime)
            three=media.transcribe(p,'S001','fake',str(self.root),chunk=1,overlap=.2);self.assertEqual(three['new_chunks'],0)
    def test_mapping_and_source_anchor(self):
        p=self.project();media.save(p/'captions.json',{'captions':[]});source=media.read(p/'project.json')['sources'][0]
        transcript=p/'transcript.json';media.save(transcript,{'source_id':'S001','complete':True,'options':{'source':source['metadata']['fingerprint'],'duration':2},'segments':[{'start':.1,'end':1.5,'words':[{'start':.1,'end':.5,'word':'借助'},{'start':.6,'end':1.5,'word':'AI'}]}]})
        editor.map_captions(SimpleNamespace(project=str(p),transcripts=[str(transcript)]));c=media.read(p/'captions.json')['captions'][0]
        self.assertEqual(c['text'],'借助AI');self.assertEqual(c['source']['source_id'],'S001')
        with self.assertRaises(ValueError):editor.map_captions(SimpleNamespace(project=str(p),transcripts=[str(transcript)]))
    def test_timeline_change_rejects_stale_mapping(self):
        p=self.project();plan=media.read(p/'plan.json');caps=media.read(p/'captions.json');caps['timeline_signature']=editor.timeline_signature(plan);media.save(p/'captions.json',caps)
        plan['clips'][0]['start']=.1;media.save(p/'plan.json',plan)
        with self.assertRaisesRegex(ValueError,'timeline changed'):editor.load_project(p)
    def test_style_change_reuses_clip_cache(self):
        p=self.project();_,src,plan,caps,style=editor.load_project(p);base=editor.base_video(p,src,plan);mtime=base.stat().st_mtime_ns
        style['endcard']['slogan']='用 AI，让价值被看见';media.save(p/'style.json',style)
        result=editor.render(SimpleNamespace(project=str(p),backend='pillow',allow_no_captions=False));self.assertEqual(base.stat().st_mtime_ns,mtime);self.assertFalse((p/'cache/transcribe').exists())
        self.assertEqual(media.read(Path(result['export'])/'style.json')['endcard']['slogan'],style['endcard']['slogan'])
    def test_render_multifile_cache_and_caption_revision(self):
        p=self.project(inputs=[str(v) for v in self.videos]);_,src,plan,caps,style=editor.load_project(p)
        base=editor.base_video(p,src,plan);self.assertEqual(int(media.probe(base)['video']['nb_frames']),120)
        original=base.stat().st_mtime_ns
        result=editor.render(SimpleNamespace(project=str(p),backend='pillow',allow_no_captions=False));report=editor.verify(SimpleNamespace(export=result['export']))
        self.assertEqual(report['frames'],150)
        editor.patch_caption(SimpleNamespace(project=str(p),id='C025',text='但是呢，借助AI',start=None,end=None,status='user_confirmed'))
        result2=editor.render(SimpleNamespace(project=str(p),backend='pillow',allow_no_captions=False));self.assertNotEqual(result['export'],result2['export']);self.assertEqual(base.stat().st_mtime_ns,original)
        self.assertIn('借助AI',(Path(result2['export'])/'subtitles.srt').read_text());self.assertFalse((p/'cache/transcribe').exists())
    @unittest.skipUnless(os.environ.get('THE_TEST_ASS')=='1','Set THE_TEST_ASS=1 with ASS-capable THE_FFMPEG')
    def test_ass_render(self):
        p=self.project();result=editor.render(SimpleNamespace(project=str(p),backend='ass',allow_no_captions=False));report=editor.verify(SimpleNamespace(export=result['export']));self.assertEqual(report['decode'],'passed')

if __name__=='__main__':unittest.main()
