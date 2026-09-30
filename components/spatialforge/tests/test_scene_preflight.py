import copy
import unittest

from spatialforge.scene_preflight import preflight_scene


def scene(camera):
    return {
        'rooms': [{'id': 'room', 'name': 'Room', 'bounds': {'center': [0, 0, 1.5], 'size': [4, 4, 3]}}],
        'cameras': [camera],
    }


class ScenePreflightTests(unittest.TestCase):
    def test_camera_above_ceiling_is_reported_without_mutating_program(self):
        program = scene({'id': 'overview', 'position': [1, 2, 6.5], 'target': [0, 0, 1]})
        original = copy.deepcopy(program)
        result = preflight_scene(program)
        self.assertFalse(result['passed'])
        self.assertFalse(result['blocking'])
        self.assertEqual(result['errors'][0]['code'], 'camera_above_declared_ceiling')
        self.assertEqual(program, original)

    def test_external_camera_is_allowed(self):
        result = preflight_scene(scene({'id': 'outside', 'role': 'external', 'position': [1, 2, 6.5], 'target': [0, 0, 1]}))
        self.assertTrue(result['passed'])
        self.assertEqual(result['cameras'][0]['reason'], 'external_camera_declared')


if __name__ == '__main__':
    unittest.main()
