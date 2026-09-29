import copy
import unittest

import numpy as np

from spatialforge.mesh_geometry import transform_mesh_geometry
from spatialforge.source_camera_layout import camera_layout_placement


class SourceCameraLayoutTests(unittest.TestCase):
    def test_executor_recovers_shared_source_positions_and_scale(self):
        # Unequal objects at different depths; per-object normalization must
        # retain both their relative scale and camera-relative separation.
        sources = [np.array([[.2, -.4, 1.1], [.7, -.2, 1.5], [.3, .5, 1.8], [.8, .1, 1.2]]),
                   np.array([[-.9, -.3, 2.5], [-.7, -.1, 2.9], [-.8, .2, 3.2], [-.5, .3, 2.6]])]
        origin = np.array([2., -1., 1.6])
        for yaw in (0, 90):
            for vertices in sources:
                mesh = {'vertices': vertices.tolist(), 'coordinate_frame': 'sam3d_camera'}
                before = copy.deepcopy(mesh)
                result = camera_layout_placement(mesh, 2.5, origin, [0, 0, yaw])
                obj = result['placement']
                local, receipt = transform_mesh_geometry(vertices, obj['size'], mesh['coordinate_frame'], obj['mesh_transform'])
                center = np.array([*obj['xy'], obj['base_z'] + receipt['actual_size_m'][2] / 2])
                expected = (vertices[:, [0, 2, 1]] * [1, 1, -1])
                if yaw == 90:
                    expected = expected[:, [1, 0, 2]] * [-1, 1, 1]
                expected = expected * 2.5 + origin
                np.testing.assert_allclose(local + center, expected, atol=1e-12)
                self.assertAlmostEqual(receipt['uniform_scale'], 2.5)
                self.assertEqual(mesh, before)
                np.testing.assert_allclose(result['camera_pose']['target'], origin + ([-1, 0, 0] if yaw else [0, 1, 0]), atol=1e-12)
                np.testing.assert_allclose(result['camera_pose']['up'], [0, 0, 1], atol=1e-12)

    def test_invalid_scale_and_frame_are_explicit_errors(self):
        mesh = {'coordinate_frame': 'sam3d_camera', 'vertices': [[0, 0, 0], [1, 1, 1]]}
        for scale in (0, -1, float('nan'), float('inf')):
            with self.assertRaisesRegex(ValueError, 'meters_per_unit'):
                camera_layout_placement(mesh, scale, [0, 0, 1])
        with self.assertRaisesRegex(ValueError, 'source geometry'):
            camera_layout_placement({**mesh, 'coordinate_frame': 'z_up'}, 1, [0, 0, 1])


if __name__ == '__main__':
    unittest.main()
