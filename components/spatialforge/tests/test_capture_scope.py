"""Output selection traverses submission, desktop jobs and upload acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatialforge.capture_scope import capture_scope
from spatialforge.capture_transfer import validate_capture
from spatialforge.service import start_capture_request
from spatialforge.storage import Store


class CaptureScopeTests(unittest.TestCase):
    def test_selection_preserves_program_and_full_capture_defaults(self):
        program = {'title':'fixture', 'cameras':[{}, {}, {}], 'objects':[]}
        original = deepcopy(program)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'program.json').write_text(json.dumps(program))
            class CaptureStore:
                def __init__(self): self.root = root
                def submit(self, key, intents, submitted_programs):
                    self.intent = intents[0]
                    return 'sf_scope'
                def directory(self, *args): return root
            store = CaptureStore()
            options = {'view_indices':[2], 'export_scene':False}
            with patch('spatialforge.service.read_program_submission', return_value={'program':program}):
                start_capture_request(store, {'request_key':'focused', 'scene_program_path':'fixture.json', 'capture_options':options})
                task = {'id':'sf_scope.scene0', 'unit':{'revision':0, 'intent':store.intent}}
                job = Store._job(store, task, 'fixture-token')
                self.assertEqual(job['capture_options'], options)
                self.assertEqual(job['program'], original)
                scope = capture_scope(job['program'], job['capture_options'])
                self.assertFalse(scope['full_scene_capture'])
                self.assertEqual(scope['view_indices'], [2])
                start_capture_request(store, {'request_key':'full', 'scene_program_path':'fixture.json'})
                task['unit']['intent'] = store.intent
                full = Store._job(store, task, 'next-token')
                self.assertEqual(full['capture_options'], {})
                self.assertEqual(capture_scope(program)['view_indices'], [0,1,2])
                self.assertTrue(capture_scope(program)['full_scene_capture'])
        self.assertEqual(program, original)

    def test_upload_uses_requested_scope_and_retains_original_view_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = {'task_id':'sf_scope.scene0', 'revision':0, 'token':'fixture-token'}
            intent = {'capture_options':{'view_indices':[2], 'export_scene':False}}
            class CaptureStore:
                def directory(self, *args): return root
                def snapshot(self, *args): return {'tasks':[{'id':job['task_id'], 'unit':{'intent':intent}}]}
            store = CaptureStore()
            (root/'program.json').write_text(json.dumps({'cameras':[{}, {}, {}]}))
            # The uploaded report cannot silently relax the stored request.
            (root/'report.json').write_text(json.dumps({'status':'captured', 'token':job['token'],
                'capture_scope':{'view_indices':[], 'scene_export_requested':False}}))
            (root/'evidence.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'incomplete native capture'):
                validate_capture(root, job, store)
            for suffix in ('.png', '.json', '_depth.npy', '_semantic.npy', '_instance.npy'):
                (root/('view_2'+suffix)).write_bytes(b'fixture')
            validate_capture(root, job, store)
            intent.pop('capture_options')
            with self.assertRaisesRegex(ValueError, 'incomplete native capture'):
                validate_capture(root, job, store)
            intent['capture_options'] = {'view_indices':[], 'export_scene':False}
            validate_capture(root, job, store)

    def test_invalid_selection_has_actionable_errors(self):
        program = {'cameras':[{}, {}]}
        for options in ({'view_indices':[2]}, {'view_indices':[0,0]}, {'view_indices':[True]},
                        {'export_scene':'false'}, {'typo':[]}, []):
            with self.subTest(options=options), self.assertRaises(ValueError):
                capture_scope(program, options)


if __name__ == '__main__': unittest.main()
