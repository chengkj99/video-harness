import copy
import json
from pathlib import Path
import tempfile
import unittest
from video_harness import core as c
from video_harness.package import package, cover_svg


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.source=self.root/'source.mp4';self.source.write_bytes(b'fixture-video-not-real')
        self.backend=self.root/'run.py';self.backend.write_text('# test backend')
        self.legacy=self.root/'legacy';self.legacy.mkdir()
        self.project=self.root/'project'
        c.save(self.legacy/'project.json',{'sources':[{'id':'S1','path':str(self.source),'metadata':{'fingerprint':c.fingerprint(self.source),'duration':20}}]})
        c.save(self.legacy/'plan.json',{'fps':25,'width':640,'height':360,'title':'测试','clips':[{'id':'E1','source_id':'S1','start':0,'end':10,'framing':'fit'}],'chapters':[{'start':0,'title':'开始'},{'start':5,'title':'之后'}]})
        rows=[]
        for i,(start,end) in enumerate([(1,2),(3,4),(5,6)]):
            rows.append({'id':'C'+str(i+1),'start':start,'end':end,'text':'【甲】句子'+str(i+1),'spoken_text':'句子'+str(i+1),'speaker':'甲','status':'needs_review','source':{'source_id':'S1','edit_id':'E1','start':start,'end':end}})
        c.save(self.legacy/'captions.json',{'captions':rows})
        c.save(self.legacy/'style.json',{'endcard':{'enabled':False}})
        c.import_editor(self.project,self.legacy,self.backend)

    def tearDown(self):self.temp.cleanup()
    def approve(self,gate):return c.approve(self.project,gate,c.gate_hash(self.project,gate),'TEST FIXTURE ONLY','test')
    def approve_script(self):self.approve('topic');self.approve('script')
    def fake_render(self):
        dest=self.root/'export';dest.mkdir(exist_ok=True)
        for name in ['video.mp4','subtitles.srt']: (dest/name).write_bytes(b'fixture')
        c.save(dest/'verification.json',{'decode':'passed','human_audio_review':'not_asserted'})
        r={'export':str(dest),'input_hash':c.compile_inputs(self.project),'video_sha256':c.file_hash(dest/'video.mp4'),'verification_sha256':c.file_hash(dest/'verification.json')}
        c.save(self.project/'render.json',r)
        return dest

    def test_import_never_approves(self):
        s=c.status(self.project)
        self.assertEqual(s['next'],'topic');self.assertFalse(s['published'])
        self.assertFalse(any(g['approved'] for g in s['gates'].values()))

    def test_no_overwrite(self):
        with self.assertRaises(c.HarnessError):c.import_editor(self.project,self.legacy,self.backend)

    def test_approval_order_and_version_conflict(self):
        with self.assertRaises(c.HarnessError):self.approve('script')
        old=c.gate_hash(self.project,'topic')
        topic=c.read(self.project/'topic.json');topic['title']='changed';c.save(self.project/'topic.json',topic)
        with self.assertRaises(c.HarnessError):c.approve(self.project,'topic',old,'TEST')

    def test_delete_compiles_video_and_caption_and_preserves_gaps(self):
        self.approve_script()
        c.edit(self.project,[{'id':'C2','keep':False}],c.gate_hash(self.project,'script'))
        result=c.compile_project(self.project);d=Path(result['project'])
        self.assertEqual(result['body_duration'],9)
        self.assertEqual([(r['start'],r['end']) for r in c.read(d/'plan.json')['clips']],[(0,3),(4,10)])
        caps=c.read(d/'captions.json')['captions']
        self.assertEqual([r['id'] for r in caps],['C1','C3'])
        self.assertEqual(caps[1]['start'],4)
        self.assertEqual(c.read(d/'plan.json')['chapters'][1]['start'],4)
        s=c.status(self.project);self.assertTrue(s['gates']['topic']['approved']);self.assertFalse(s['gates']['script']['approved'])

    def test_edit_does_not_change_audio_ranges(self):
        first=c.compile_project(self.project)
        before=c.read(Path(first['project'])/'plan.json')['clips']
        c.edit(self.project,[{'id':'C1','text':'纠正错字'}],c.gate_hash(self.project,'script'))
        after=c.compile_project(self.project)
        self.assertEqual(before,c.read(Path(after['project'])/'plan.json')['clips'])
        self.assertEqual(c.read(self.project/'story.json')['units'][0]['original_text'],'句子1')

    def test_stale_page_cannot_overwrite(self):
        h=c.gate_hash(self.project,'script')
        c.edit(self.project,[{'id':'C1','text':'第一次'}],h)
        with self.assertRaises(c.HarnessError):c.edit(self.project,[{'id':'C1','text':'旧页面'}],h)
        self.assertEqual(c.read(self.project/'story.json')['units'][0]['text'],'第一次')

    def test_direct_edit_invalidates_confirmation(self):
        self.approve_script();s=c.read(self.project/'story.json');s['units'][0]['text']='手改';c.save(self.project/'story.json',s)
        self.assertFalse(c.approval_valid(self.project,'script'))

    def test_source_mutation_detected(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(c.HarnessError):c.status(self.project)

    def test_verified_relocation(self):
        new=self.root/'moved.mp4';self.source.rename(new)
        other=self.root/'relocated'
        c.import_editor(other,self.legacy,self.backend,source_map={'S1':str(new)})
        self.assertEqual(c.read(other/'original/project.json')['sources'][0]['path'],str(new.resolve()))

    def test_incorrect_relocation_rejected(self):
        new=self.root/'other.mp4';new.write_bytes(b'other')
        with self.assertRaises(c.HarnessError):c.import_editor(self.root/'other',self.legacy,self.backend,source_map={'S1':str(new)})

    def test_source_anchor_cannot_be_changed(self):
        s=c.read(self.project/'story.json');s['units'][0]['source']['start']=.5;c.save(self.project/'story.json',s)
        with self.assertRaises(c.HarnessError):c.compile_project(self.project)

    def test_original_snapshot_cannot_be_changed(self):
        s=c.read(self.project/'original/plan.json');s['clips'][0]['end']=11;c.save(self.project/'original/plan.json',s)
        with self.assertRaises(c.HarnessError):c.status(self.project)

    def test_duplicate_or_missing_ids_rejected(self):
        s=c.read(self.project/'story.json');s['units'][1]['id']='C1';c.save(self.project/'story.json',s)
        with self.assertRaises(c.HarnessError):c.compile_project(self.project)

    def test_render_requires_script_confirmation(self):
        with self.assertRaises(c.HarnessError):c.render(self.project)

    def test_publish_package_requires_film_confirmation(self):
        self.approve_script();self.fake_render()
        with self.assertRaises(c.HarnessError):package(self.project)

    def test_copy_changes_do_not_invalidate_film(self):
        self.approve_script();self.fake_render();self.approve('film')
        before=c.compile_inputs(self.project)
        cp=c.read(self.project/'copy.json');cp['description']='测试描述';cp['cover_lines']=['新的封面'];c.save(self.project/'copy.json',cp)
        self.assertEqual(before,c.compile_inputs(self.project));self.assertTrue(c.approval_valid(self.project,'film'))
        out=package(self.project)
        manifest=c.read(Path(out['package'])/'manifest.json')
        self.assertFalse(manifest['published']);self.assertFalse(manifest['draft']);self.assertIn('cover.svg',manifest['files'])

    def test_style_change_invalidates_film_but_not_script(self):
        self.approve_script();self.fake_render();self.approve('film')
        c.save(self.project/'style.json',{'font_size':60})
        self.assertFalse(c.approval_valid(self.project,'film'));self.assertTrue(c.approval_valid(self.project,'script'))

    def test_output_tampering_invalidates_film(self):
        self.approve_script();dest=self.fake_render();self.approve('film');(dest/'video.mp4').write_bytes(b'tampered')
        self.assertFalse(c.approval_valid(self.project,'film'))

    def test_backend_change_invalidates_render(self):
        self.approve_script();self.fake_render();self.approve('film');self.backend.write_text('# changed')
        self.assertFalse(c.approval_valid(self.project,'film'))

    def test_draft_package_cannot_claim_approval(self):
        self.fake_render();cp=c.read(self.project/'copy.json');cp['description']='draft';c.save(self.project/'copy.json',cp)
        out=package(self.project,draft=True);m=c.read(Path(out['package'])/'manifest.json')
        self.assertTrue(m['draft']);self.assertEqual(m['approvals'],{})

    def test_runtime_binary_change_invalidates_render(self):
        binary=self.root/'ffmpeg';binary.write_bytes(b'old tool')
        runtime=self.root/'runtime.json';c.save(runtime,{'ffmpeg':str(binary)})
        cfg=c.read(self.project/'harness.json');cfg['runtime']=str(runtime);c.save(self.project/'harness.json',cfg)
        before=c.compile_inputs(self.project);binary.write_bytes(b'new tool')
        self.assertNotEqual(before,c.compile_inputs(self.project))

    def test_cover_text_escaped(self):
        svg=cover_svg({'cover_lines':['<script>'],'cover_size':[900,1200]})
        self.assertNotIn('<script>',svg);self.assertIn('&lt;script&gt;',svg)

    def test_compile_idempotent_and_stable_ids(self):
        a=c.compile_project(self.project);b=c.compile_project(self.project)
        self.assertEqual(a,b)
        self.assertEqual([x['id'] for x in c.read(Path(a['project'])/'captions.json')['captions']],['C1','C2','C3'])

if __name__=='__main__':unittest.main()
