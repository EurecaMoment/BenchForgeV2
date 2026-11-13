"""Queue deadlines and generated coordinate frames; no model weights are loaded."""
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from benchforge_backend import generation_stage
from benchforge_backend.trellis_service import Resident


class TrellisServiceTests(unittest.TestCase):
    def test_expired_queue_entry_never_runs_and_capacity_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        class Model:
            def infer(self, item):
                calls.append(item.id)
                entered.set()
                release.wait(2)
                return {'status': 'ok'}

        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'image.png'
            image.write_bytes(b'fixture')
            request = {'objects': [{'object_id': 'one', 'image': str(image)}], 'output_dir': temp}
            resident = Resident({'max_requests': 2}, model_factory=lambda _config: Model())
            first = resident.submit(request, 2)
            self.assertTrue(entered.wait(1))
            second = resident.submit(request, .01)
            with self.assertRaises(queue.Full):
                resident.submit(request, 2)
            second.canceled.set()
            release.set()
            self.assertTrue(first.done.wait(1))
            self.assertTrue(second.done.wait(1))
            self.assertEqual(calls, [first.id])
            self.assertEqual((resident.completed, resident.expired), (1, 1))
            self.assertIsNone(second.result)

    def test_trellis_stage_preserves_y_up_without_fabricating_camera_or_gaussian(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, mask = root / 'image.png', root / 'mask.png'
            image.write_bytes(b'image')
            mask.write_bytes(b'mask')

            class Tools:
                def __init__(self, _root):
                    pass

                def source_path(self, value):
                    return Path(value)

                def execute(self, name, request, work, stop):
                    output = Path(request['output_dir'])
                    output.mkdir(parents=True)
                    (output / 'subject.glb').write_bytes(b'mesh fixture')
                    return {'status': 'ok', 'provider': 'trellis2', 'assets': [{
                        'object_id': 'subject', 'asset': 'subject.glb',
                        'model': 'microsoft/TRELLIS.2-4B', 'source_frame': 'y_up'}]}

            class Store:
                def __init__(self):
                    self.root = root

                def directory(self, *_args):
                    return root

                def update(self, *_args, **_kwargs):
                    pass

            task = {'id': 'sf_trellis.scene0', 'unit': {'revision': 0, 'intent': {
                'tool': 'sam3d', 'parameters': {'source_image': str(image), 'objects': [
                    {'object_id': 'subject', 'source_mask': str(mask)}]}}}}
            with patch.object(generation_stage, 'GenerationTools', Tools), \
                    patch.object(generation_stage, 'record_progress'), \
                    patch.dict(os.environ, {'BENCHFORGE_INFERENCE_URL': 'http://fixture'}):
                result = generation_stage.execute_generation_stage(Store(), task, threading.Event())
            asset = result['assets'][0]
            self.assertEqual(asset['source_frame'], 'y_up')
            self.assertEqual(asset['model'], 'microsoft/TRELLIS.2-4B')
            self.assertNotIn('gaussian_source_path', asset)
            self.assertNotIn('rotation_wxyz', asset)
            self.assertEqual(json.loads((root / 'generation_stage.json').read_text())['assets'][0]['source_frame'], 'y_up')


if __name__ == '__main__':
    unittest.main()
