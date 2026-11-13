import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import sys

import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from interaction_recording import InteractionRecording


class InteractionRecordingTests(unittest.TestCase):
    def test_sampled_frames_encode_with_physics_timestamps(self):
        with tempfile.TemporaryDirectory() as root:
            rendered = []
            def capture(name):
                pixels = np.full((48, 64, 3), len(rendered) * 70, np.uint8)
                cv2.imwrite(str(Path(root) / name), pixels)
                rendered.append(name)
            recording = InteractionRecording(root, 0, {'every_steps':4}, 1/120, capture)
            for step in range(181,191):
                recording.sample(step, 'push', {'position':[step / 100, 0, 0]})
            receipt = recording.finish(190)
            timeline = json.loads((Path(root) / receipt['timeline_file']).read_text())
            self.assertEqual([f['step'] for f in timeline['frames']], [181,185,189])
            self.assertEqual(timeline['frames'][1]['timestamp_sim'], 185/120)
            self.assertEqual(receipt['action_end_step'], 190)
            self.assertEqual(receipt['interpolated_frames'], 0)
            with zipfile.ZipFile(Path(root) / receipt['frames_archive']) as archive:
                self.assertEqual(archive.namelist(), rendered)
                self.assertEqual(archive.read(rendered[1]), (Path(root) / rendered[1]).read_bytes())
            video = cv2.VideoCapture(str(Path(root) / receipt['video']))
            frames = []
            try:
                self.assertAlmostEqual(video.get(cv2.CAP_PROP_FPS),30)
                while True:
                    ok, pixels = video.read()
                    if not ok:break
                    frames.append(pixels)
            finally:video.release()
            self.assertEqual(len(frames),3)
            self.assertGreater(float(frames[-1].mean()-frames[0].mean()),100)

    def test_default_interval_follows_physics_dt(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = InteractionRecording(root, 1, {}, 1/60, lambda _name:None)
            self.assertEqual(recorder.every_steps,2)


if __name__ == '__main__': unittest.main()
