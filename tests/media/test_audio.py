"""Audio regressions with temporary generated fixtures; no private recordings."""
import array
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'video_harness/media_backend/scripts'))
import editor
import media


class Audio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ac = media.read(editor.SKILL / 'assets/style-default.json')['audio']

    def test_defaults_and_independent_switches(self):
        self.assertEqual(self.ac, dict(normalize=True, denoise=True, highpass=65, lufs=-14, true_peak=-1.6))
        media.save(self.root / 'loudness.json', dict(input_i='-22', input_tp='-18', input_lra='0', input_thresh='-32', target_offset='0'))
        for normalize in (False, True):
            for denoise in (False, True):
                ac = dict(self.ac, normalize=normalize, denoise=denoise)
                chain = editor.audio_filter(ac, 'unused', self.root)
                self.assertEqual('afftdn=' in chain, denoise)
                self.assertEqual('loudnorm=' in chain, normalize)
                self.assertEqual('highpass=' in chain, normalize or denoise)
        legacy = dict(self.ac, lufs=-16)
        del legacy['denoise']
        self.assertNotIn('afftdn', editor.audio_filter(legacy, 'unused', self.root))
        self.assertIn('I=-16', editor.audio_filter(legacy, 'unused', self.root))
        self.assertEqual(editor.audio_filter(dict(legacy, normalize=False), 'unused', self.root), 'anull')
        self.assertNotIn('highpass', editor.audio_filter(dict(self.ac, highpass=0), 'unused', self.root))

    def test_measure_and_output_share_preprocessing(self):
        meter = dict(input_i='-22', input_tp='-18', input_lra='0', input_thresh='-32', target_offset='0')
        with patch.object(editor.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr=json.dumps(meter))) as run:
            chain = editor.audio_filter(self.ac, 'unused', self.root)
        measured = run.call_args.args[0]
        measured = measured[measured.index('-af') + 1]
        self.assertEqual(measured.split(',loudnorm')[0], chain.split(',loudnorm')[0])

    def test_silence_skips_gain(self):
        source = self.root / 'silence.wav'
        media.ff('-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', '3', source)
        chain = editor.audio_filter(self.ac, source, self.root)
        self.assertEqual(chain, 'highpass=f=65,afftdn=nr=8:nf=-50:tn=1')
        output = self.root / 'out.wav'
        media.ff('-i', source, '-af', chain, output)
        self.assertEqual(self.rms(output), 0)

    def rms(self, source, chain='anull'):
        result = subprocess.run([media.binary('ffmpeg'), '-v', 'error', '-i', str(source), '-af', chain, '-f', 'f32le', '-ac', '1', '-'], capture_output=True, check=True)
        samples = array.array('f', result.stdout)
        # Exclude startup noise estimator settling.
        samples = samples[48000:]
        return math.sqrt(sum(x*x for x in samples) / len(samples))

    def test_noise_reduction(self):
        source = self.root / 'noise.wav'
        media.ff('-f', 'lavfi', '-i', 'anoisesrc=color=white:amplitude=0.003:seed=42:r=48000', '-t', '5', '-c:a', 'pcm_f32le', source)
        baseline = self.rms(source, 'highpass=f=65')
        chain = editor.audio_filter(dict(self.ac, normalize=False), source, self.root)
        cleaned = self.rms(source, chain)
        self.assertLess(cleaned, baseline * 0.9)

    def test_aac_loudness_and_peak(self):
        source = self.root / 'tone.wav'
        media.ff('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '8', source)
        chain = editor.audio_filter(self.ac, source, self.root)
        output = self.root / 'out.m4a'
        media.ff('-i', source, '-af', chain, '-ar', '48000', '-c:a', 'aac', '-b:a', '192k', output)
        result = subprocess.run([media.binary('ffmpeg'), '-hide_banner', '-i', str(output), '-af', 'loudnorm=print_format=json', '-f', 'null', '-'], capture_output=True, text=True, check=True)
        meter = json.JSONDecoder().raw_decode(result.stderr[result.stderr.rfind('{'):])[0]
        self.assertAlmostEqual(float(meter['input_i']), -14, delta=1)
        self.assertLessEqual(float(meter['input_tp']), -1)


if __name__ == '__main__':
    unittest.main()
