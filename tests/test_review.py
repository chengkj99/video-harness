import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import urllib.request
import urllib.error
import test_workflow


@unittest.skipUnless(os.environ.get('VH_HTTP_TESTS')=='1','Set VH_HTTP_TESTS=1 for loopback integration tests')
class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_workflow.WorkflowTests();self.fixture.setUp()
        self.p=self.fixture.project
        self.proc=subprocess.Popen([sys.executable,'-m','video_harness','serve','--project',str(self.p),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        line=self.proc.stdout.readline()
        if not line:
            raise RuntimeError(self.proc.stderr.read())
        url=json.loads(line)['review_url'];self.url,self.token=url.split('/#')
    def tearDown(self):
        self.proc.terminate();self.proc.wait(timeout=5);self.proc.stdout.close();self.proc.stderr.close();self.fixture.tearDown()
    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body else None,headers={'X-Review-Token':self.token,**(headers or {})})
        return urllib.request.urlopen(req,timeout=5)
    def test_unauthorized_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api',headers={'X-Review-Token':'wrong'})
        self.assertEqual(e.exception.code,403)
    def test_range_returns_declared_source_bytes(self):
        with self.request('/source/S1',headers={'Range':'bytes=0-6'}) as r:
            self.assertEqual(r.status,206);self.assertEqual(r.read(),b'fixture')
    def test_arbitrary_path_denied(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/source/../../harness.json')
    def test_cross_origin_mutation_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/edit',{'changes':[]},headers={'Origin':'https://example.com'})
        self.assertEqual(e.exception.code,403)
    def test_save_and_stale_version(self):
        with self.request('/api') as r:d=json.load(r)
        body={'changes':[{'id':'C1','text':'网页修订'}],'expected':d['status']['gates']['script']['hash']}
        with self.request('/edit',body) as r:self.assertEqual(r.status,200)
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/edit',body)
        self.assertEqual(e.exception.code,409)

if __name__=='__main__':unittest.main()
