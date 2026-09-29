import unittest

import numpy as np

from render_quality import assess_view


class RenderQualityTests(unittest.TestCase):
    def test_low_variance_view_is_explained(self):
        result = assess_view(np.full((4, 4, 3), 255, dtype=np.uint8), np.ones((4, 4)), [{'object_id': 'wall'}])
        self.assertFalse(result['passed'])
        self.assertEqual(result['reasons'], ['rgb_low_variance'])

    def test_view_with_rgb_depth_and_entity_passes(self):
        rgb = np.arange(48, dtype=np.uint8).reshape((4, 4, 3))
        result = assess_view(rgb, np.ones((4, 4)), [{'object_id': 'table'}])
        self.assertTrue(result['passed'])
        self.assertEqual(result['visible_entity_count'], 1)

    def test_empty_view_reports_all_missing_evidence(self):
        result = assess_view(np.zeros((4, 4, 3), dtype=np.uint8), np.full((4, 4), np.inf), [])
        self.assertEqual(result['reasons'], ['rgb_low_variance', 'insufficient_finite_depth', 'no_visible_entities'])


if __name__ == '__main__':
    unittest.main()
