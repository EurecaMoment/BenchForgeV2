import unittest

from spatialforge.camera_trajectory import sampled_camera


class CameraTrajectoryTests(unittest.TestCase):
    def test_interpolates_position_and_aim_at_recording_step(self):
        base = {'id': 'walkthrough', 'up': [0, 0, 1], 'focal_length_mm': 30}
        path = [
            {'step': 0, 'position': [0, -2, 1], 'target': [0, 0, 0]},
            {'step': 10, 'position': [2, 0, 1], 'target': [0, 0, 0]},
        ]
        frame = sampled_camera(base, path, 5)
        self.assertEqual(frame['position'], [1, -1, 1])
        self.assertEqual(frame['target'], [0, 0, 0])
        self.assertEqual((frame['id'], frame['up'], frame['focal_length_mm']),
                         ('walkthrough', [0, 0, 1], 30))

    def test_last_pose_is_held_after_path_ends(self):
        path = [
            {'step': 0, 'position': [0, 0, 1], 'target': [0, 0, 0]},
            {'step': 2, 'position': [1, 0, 1], 'target': [0, 0, 0]},
        ]
        self.assertEqual(sampled_camera({}, path, 6)['position'], [1, 0, 1])


if __name__ == '__main__':
    unittest.main()
