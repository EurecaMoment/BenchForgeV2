import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from spatialforge.trajectory import SCHEMA, SpatialTreeTrajectoryRecorder, TrajectoryError, validate_manifest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from interaction_recording import InteractionRecording


def transform(x=0.0, y=0.0, z=0.0):
    return [[1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [x, y, z, 1.0]]


class SpatialTreeTrajectoryTests(unittest.TestCase):
    def artifacts(self, root, prefix):
        paths = []
        for suffix in ('rgb.png', 'depth.npy', 'semantic.npy', 'instance.npy'):
            path = Path(root) / f'{prefix}_{suffix}'
            path.write_bytes((prefix + suffix).encode('ascii'))
            paths.append(path)
        return paths

    def add(self, recorder, paths, step, camera_x, object_x, phase):
        recorder.add_frame(
            step=step,
            timestamp_sim=step / 30,
            rgb_path=paths[0], depth_path=paths[1], semantic_path=paths[2], instance_path=paths[3],
            camera={'T_world_camera_usd': transform(camera_x), 'intrinsics': {'fx': 500, 'fy': 500, 'cx': 32, 'cy': 24}},
            objects=[{'object_id': 'cube', 'label': 'cube', 'T_world_object': transform(object_x),
                      'visible_pixels': 120}],
            metadata={'phase': phase},
        )

    def test_native_motion_and_correspondence_are_derived(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = SpatialTreeTrajectoryRecorder(root, fps=30, width=64, height=48, scenario_id='moving-camera')
            self.add(recorder, self.artifacts(root, 'one'), 0, 0, 0, 'before')
            self.add(recorder, self.artifacts(root, 'two'), 1, .4, .2, 'move')
            receipt = recorder.finalize()
            manifest = json.loads((Path(root) / 'manifest.json').read_text())
            self.assertEqual(receipt['schema'], SCHEMA)
            self.assertTrue(manifest['ground_truth'])
            self.assertEqual(manifest['source'], 'isaac_native')
            self.assertEqual(manifest['frames'][1]['correspondence'], ['cube'])
            self.assertEqual(manifest['frames'][1]['ego_motion']['label'], 'right')
            self.assertAlmostEqual(manifest['frames'][1]['ego_motion']['translation_m'][0], .4)
            self.assertTrue(manifest['frames'][1]['object_motion'][0]['moving'])
            self.assertEqual(manifest['frames'][1]['object_motion'][0]['coordinate_frame'], 'world_z_up')
            self.assertAlmostEqual(manifest['frames'][1]['object_motion'][0]['translation_m'][0], .2)
            self.assertEqual(len((Path(root) / 'frames.jsonl').read_text().splitlines()), 2)

    def test_external_artifacts_are_copied_and_invalid_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            recorder = SpatialTreeTrajectoryRecorder(root, fps=24, width=16, height=16, scenario_id='copy')
            self.add(recorder, self.artifacts(outside, 'external'), 0, 0, 0, 'before')
            recorder.finalize()
            self.assertTrue((Path(root) / 'frames' / '000000' / 'external_rgb.png').is_file())
            manifest = json.loads((Path(root) / 'manifest.json').read_text())
            self.assertEqual(validate_manifest(manifest)['schema'], SCHEMA)
            manifest['source'] = 'model_prediction'
            with self.assertRaises(TrajectoryError):
                validate_manifest(manifest)

    def test_steps_must_be_monotonic(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = SpatialTreeTrajectoryRecorder(root, fps=30, width=8, height=8)
            self.add(recorder, self.artifacts(root, 'one'), 3, 0, 0, 'before')
            with self.assertRaises(TrajectoryError):
                self.add(recorder, self.artifacts(root, 'two'), 2, 0, 0, 'out_of_order')

    def test_interaction_exports_transferable_spatialtree_zip(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as root:
            def capture(name):
                image = np.full((16, 16, 3), 120, dtype=np.uint8)
                cv2.imwrite(str(Path(root) / name), image)

            def trajectory_frame(step, phase, image):
                paths = self.artifacts(root, f'frame_{step}')
                return {
                    'step': step, 'timestamp_sim': step / 30,
                    'rgb_path': image, 'depth_path': paths[1], 'semantic_path': paths[2],
                    'instance_path': paths[3],
                    'camera': {'T_world_camera_usd': transform(step / 30),
                               'intrinsics': {'fx': 30, 'fy': 30, 'cx': 8, 'cy': 8}},
                    'objects': [], 'metadata': {'phase': phase},
                }

            recording = InteractionRecording(root, 0,
                {'every_steps': 1, 'spatialtree': {'split': 'train'}},
                1 / 30, capture, trajectory_frame=trajectory_frame, width=16, height=16)
            recording.spatialtree_action_id = recording.spatialtree.add_action(
                step=0, timestamp_sim=0, action={'type': 'record_trajectory'})['action_id']
            recording.sample(0, 'start', {})
            recording.sample(1, 'move', {})
            receipt = recording.finish(1)
            bundle = Path(root) / receipt['spatialtree']['bundle']
            self.assertTrue(bundle.is_file())
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                self.assertIn('manifest.json', names)
                self.assertIn('frames.jsonl', names)
                self.assertIn('frames/000000/000000.png', names)
                self.assertIn('frames/000000/frame_0_depth.npy', names)
                self.assertIn('artifacts/interaction_0.mp4', names)
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['frame_count'], 2)
                self.assertEqual(manifest['capabilities'], ['N04', 'N05', 'N09', 'N14'])


if __name__ == '__main__':
    unittest.main()
