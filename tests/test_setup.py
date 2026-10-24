import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from video_harness import core
from video_harness.setup import configure


class SetupTests(unittest.TestCase):
    def test_bundled_resources_exist_and_have_neutral_defaults(self):
        runner=core.backend_path('builtin')
        self.assertTrue(runner.is_file())
        style=json.loads((runner.parents[1]/'assets/style-default.json').read_text())
        self.assertFalse(style['endcard']['enabled'])
        self.assertEqual(style['endcard']['cta'],'')

    def test_external_backend_still_resolves(self):
        self.assertEqual(core.backend_path('/tmp/custom.py'),Path('/tmp/custom.py'))

    def test_failed_probe_does_not_write_config(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'runtime.json'
            with patch('video_harness.setup.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='missing ffmpeg',stderr='')):
                with self.assertRaisesRegex(ValueError,'missing ffmpeg'): configure(path)
            self.assertFalse(path.exists())

    def test_configure_records_environment_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'runtime.json'
            with patch('video_harness.setup.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'font':'/tmp/font.ttf'}))),patch('video_harness.setup.shutil.which',side_effect=lambda x:'/tmp/'+x),patch.dict('os.environ',{},clear=True):
                configure(path)
            data=json.loads(path.read_text())
            self.assertEqual(data['ffmpeg'],'/tmp/ffmpeg')
            self.assertEqual(data['font'],'/tmp/font.ttf')
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'不覆盖'):configure(path)
            self.assertEqual(before,path.read_bytes())
