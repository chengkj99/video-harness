import unittest
from video_harness.package import cover_variants, cover_svg
from video_harness.core import HarnessError

class CoverTests(unittest.TestCase):
    def test_legacy_project_gets_both_ratios_without_mutation(self):
        copy = {'cover_lines': ['Test'], 'cover_size': [1920, 1080]}
        variants = cover_variants(copy)
        self.assertEqual(copy['cover_size'], [1920, 1080])
        self.assertEqual(variants['portrait']['cover_size'], [1500, 2000])
        self.assertEqual(variants['landscape']['cover_size'], [1600, 1200])
        self.assertIn('width="1600" height="1200"', cover_svg(variants['landscape']))

    def test_invalid_landscape_ratio_rejected(self):
        with self.assertRaises(HarnessError):
            cover_variants({'cover_sizes': {'portrait': [1500,2000], 'landscape': [1920,1080]}})

    def test_malformed_dimensions_rejected(self):
        for size in [None, [1], [True,4], [1500,'2000'], [300,400,500]]:
            with self.subTest(size=size), self.assertRaises(HarnessError):
                cover_variants({'cover_sizes': {'portrait': size, 'landscape': [1600,1200]}})
