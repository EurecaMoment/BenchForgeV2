"""Exercise the session artifact projection without services or model calls."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError, URLError


SPEC = importlib.util.spec_from_file_location('production_observer', Path(__file__).parents[1] / 'ui/production_observer.py')
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)
import scene_preview_video as preview


class StageArtifactsTest(unittest.TestCase):
    def test_saved_movie_is_reused_and_playback_never_invokes_the_encoder(self):
        with tempfile.TemporaryDirectory(prefix='benchforge-preview-') as directory:
            cache = Path(directory)
            frame = cache / 'view_0.png'
            frame.write_bytes(b'public-scene-image')
            calls = []

            def encode(arguments, **_kwargs):
                calls.append(arguments)
                Path(arguments[-1]).write_bytes(b'public-movie-bytes' * 8)

            def service(_config, route, _args):
                if route == '/inspect':
                    return {'state': 'SUCCEEDED', 'tasks': [{'id': 'sf_one.scene0', 'state': 'SUCCEEDED', 'unit': {
                        'revision': 2, 'phase': 'capture', 'workflow': 'scene', 'intent': {'name': 'Room'}}}]}
                return {'files': [{'file': 'capture/view_0.png', 'bytes': 18}]} if _args['file'] == 'capture' else {'files': []}

            with patch.object(preview, 'CACHE_ROOT', cache), patch.object(preview, 'encoder_path', return_value='ffmpeg'), \
                    patch.object(preview.subprocess, 'run', side_effect=encode), \
                    patch.object(observer, 'session_runs', return_value=[{'id': 'sf_one'}]), \
                    patch.object(observer, 'service_read', side_effect=service):
                saved = preview.persist_preview('sf_one.scene0', 2, [frame])
                movie_stat = Path(saved['source_path']).stat()
                again = preview.persist_preview('sf_one.scene0', 2, [frame])
                self.assertTrue(again['reused'])
                self.assertEqual(len(calls), 1)
                self.assertIn('+faststart', calls[0])
                for _open in range(2):
                    products = observer.stage_artifacts({}, 'session-one', 'sf_one')
                    movies = [row for row in products['items'] if row['file'] == preview.PREVIEW_FILE]
                    self.assertEqual(len(movies), 1)
                    self.assertEqual(movies[0]['purpose'], 'scene_tour')
                    media = observer.stage_artifacts({}, 'session-one', 'sf_one', 'sf_one.scene0', 2, preview.PREVIEW_FILE)
                    self.assertEqual(media['content_type'], 'video/mp4')
                    self.assertEqual(Path(media['source_path']).stat().st_mtime_ns, movie_stat.st_mtime_ns)
                self.assertEqual(len(calls), 1)
                refused = observer.stage_artifacts({}, 'session-one', 'sf_other', 'sf_other.scene0', 2, preview.PREVIEW_FILE)
                self.assertEqual(refused['status_code'], 403)
                stale = observer.stage_artifacts({}, 'session-one', 'sf_one', 'sf_one.scene0', 1, preview.PREVIEW_FILE)
                self.assertEqual(stale['status_code'], 409)

    def test_missing_stage_directories_keep_saved_plan_and_network_errors_propagate(self):
        def service(_config, route, _args):
            if route == '/inspect':
                return {'state': 'RUNNING', 'tasks': [{'id': 'sf_one.scene0', 'state': 'RUNNING', 'unit': {
                    'revision': 0, 'phase': 'plan', 'intent': {'name': 'Waiting scene'}}}]}
            raise HTTPError('http://service/evidence', 404, 'not produced yet', {}, None)

        with patch.object(observer, 'session_runs', return_value=[]), patch.object(observer, 'service_read', side_effect=service):
            # Only the Node server's verified workspace pipeline reference grants this alternate path.
            value = observer.stage_artifacts({}, 'session-one', 'sf_one', run_ids=['sf_one'])
            self.assertEqual(value['plan']['objective'], 'Waiting scene')
            self.assertEqual(value['items'], [])
            self.assertEqual(value['config']['scenes'][0]['task_id'], 'sf_one.scene0')
        with patch.object(observer, 'service_read', side_effect=URLError('service offline')):
            with self.assertRaises(URLError):
                observer.optional_evidence({}, {'file': 'capture'})
        with patch.object(observer, 'service_read', side_effect=HTTPError('http://service', 401, 'unauthorized', {}, None)):
            with self.assertRaises(HTTPError):
                observer.optional_evidence({}, {'file': 'capture'})

    def test_declared_products_plan_projection_and_authority_exclusion(self):
        calls = []

        def service(_config, route, args):
            calls.append((route, args))
            if route == '/inspect':
                return {'state': 'RUNNING', 'tasks': [{'id': 'sf_one.scene0', 'state': 'RUNNING', 'unit': {
                    'revision': 2, 'phase': 'capture', 'workflow': 'scene', 'intent': {
                        'name': 'Room', 'description': 'Observe the room', 'target_items': 12,
                        'split': 'dev', 'authority': 'PRIVATE_ORACLE_SENTINEL'}}}]}
            if args.get('file') == 'capture':
                return {'files': [{'file': 'capture/view_00.png', 'bytes': 123},
                                  {'file': 'capture/view_00.json', 'bytes': 456},
                                  {'file': 'capture/interaction_0.mp4', 'bytes': 789},
                                  {'file': 'authority.jsonl', 'bytes': 100}]}
            if args.get('file') == 'release':
                return {'files': [{'file': 'release/complete.json', 'bytes': 32},
                                  {'file': 'release/authority_bundle.zip', 'bytes': 100}]}
            return {'source_path': '/safe/capture/view_00.json', 'latest_revision': 2,
                    'data': {'frame_id': 'view_00', 'answer': 'PRIVATE_ORACLE_SENTINEL',
                             'objects': [{'object_id': 'cube', 'label': 'Cube', 'bbox_2d': {'xyxy': [1, 2, 3, 4]},
                                          'authority': 'PRIVATE_ORACLE_SENTINEL'}]}}

        with patch.object(observer, 'session_runs', return_value=[{'id': 'sf_one'}]), patch.object(observer, 'service_read', side_effect=service):
            value = observer.stage_artifacts({}, 'session-one', 'sf_one')
            self.assertEqual([row['stage'] for row in value['items']], ['S2', 'S3', 'S2', 'S5'])
            self.assertEqual(value['plan']['objective'], 'Observe the room')
            self.assertNotIn('PRIVATE_ORACLE_SENTINEL', str(value))
            self.assertEqual(len(calls), 3)  # Only explicit inspect + current capture/release listings.
            preview = observer.stage_artifacts({}, 'session-one', 'sf_one', 'sf_one.scene0', 2, 'capture/view_00.json')
            self.assertEqual(preview['data']['visible_objects'][0]['label'], 'Cube')
            self.assertNotIn('PRIVATE_ORACLE_SENTINEL', str(preview))
            refused = observer.stage_artifacts({}, 'session-one', 'sf_one', 'sf_one.scene0', 2, 'authority.jsonl')
            self.assertEqual(refused['status_code'], 403)
            cross_session = observer.stage_artifacts({}, 'session-one', 'sf_elsewhere')
            self.assertEqual(cross_session['status_code'], 403)
            stale = observer.stage_artifacts({}, 'session-one', 'sf_one', 'sf_one.scene0', 1, 'capture/view_00.json')
            self.assertEqual(stale['status_code'], 409)


if __name__ == '__main__':
    unittest.main()
