"""Exercise the session artifact projection without services or model calls."""
import importlib.util
import io
from pathlib import Path
import unittest
import tempfile
import time
from unittest.mock import patch
from urllib.error import HTTPError, URLError


SPEC = importlib.util.spec_from_file_location('production_observer', Path(__file__).parents[1] / 'host/workbench/production_observer.py')
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)
import scene_preview_video as preview
import scene_library as library
from runtime_paths import CHECKOUT_ROOT
import json


class StageArtifactsTest(unittest.TestCase):
    def test_moved_helpers_keep_the_checkout_deployment_and_backend_paths(self):
        checkout = Path(__file__).resolve().parents[3]
        self.assertEqual(CHECKOUT_ROOT, checkout)
        self.assertEqual(preview.CACHE_ROOT, checkout / '.deployment/scene-previews')

    def test_remote_client_reads_associated_runs_without_database_access(self):
        config = {'service_url': 'https://fixture.invalid', 'operator_token': 'test-only'}
        with patch.object(observer, 'service_read', return_value={'runs': []}) as metadata, \
                patch.object(observer, 'production_observation', return_value={
                    'state': 'RUNNING', 'terminal': False, 'tasks': [],
                }) as read:
            value = observer.observe(config, 'session-test', ['sf_saved'])
        metadata.assert_called_once_with(config, '/workbench/session-runs', {
            'session_id': 'session-test', 'related_session_ids': [],
        })
        read.assert_called_once_with(config, 'sf_saved')
        self.assertEqual(value['runs'][0]['run_id'], 'sf_saved')

    def test_discovery_failure_keeps_runs_registered_by_the_workbench(self):
        config = {'operator_token': 'fixture', 'database_url': 'sqlite:///unused-fixture'}
        local = {'current_collection': {'rows': [{'run_id': 'sf_registered'}]}}
        with patch.object(observer, 'current_production_progress', return_value=local), \
                patch.object(observer, 'session_runs', side_effect=URLError('discovery failed')), \
                patch.object(observer, 'production_observation', return_value={
                    'state': 'RUNNING', 'terminal': False, 'tasks': [],
                }) as read:
            value = observer.observe(config, 'session-test', ['sf_saved'])
        self.assertEqual(value['status'], 'partial')
        self.assertEqual(value['error'], 'URLError')
        self.assertEqual([row['run_id'] for row in value['runs']], ['sf_registered', 'sf_saved'])
        self.assertCountEqual([call.args for call in read.call_args_list],
                              [(config, 'sf_registered'), (config, 'sf_saved')])

    def test_workspace_paths_normalize_root_and_reject_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / 'nested'
            nested.mkdir()
            alias = nested / '..'
            self.assertEqual(observer.workspace_file(alias, root / 'plan.json'), root.resolve() / 'plan.json')
            self.assertEqual(observer.workspace_file(alias, 'plan.json'), root.resolve() / 'plan.json')
            with self.assertRaises(ValueError):
                observer.workspace_file(alias, '../outside.json')

    def test_repairs_keep_public_plan_and_candidate_counts_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'bench-office100'
            (folder / 'evidence').mkdir(parents=True)
            evidence = folder / 'evidence/evidence.jsonl'
            evidence.write_text('{}\n')
            (folder / 'questions').mkdir()
            plan = {'inputs': {'target_items': 100, 'evidence': str(evidence)}}
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            reference = {'path': str(plan_path.resolve()), 'file_version': observer.file_version(plan_path)}
            path = folder / 'questions/generation_progress.json'
            saved = {'schema': 'bench-office100-generation-progress-v1', 'session_id': 'session-counts',
                'plan_path': reference['path'], 'plan_version': reference['file_version'], 'target_items': 100,
                'state': 'running', 'pid': 123, 'heartbeat_at': time.time(), 'candidate_count': 100,
                'written_count': 100, 'verified_count': 89, 'published_count': 0, 'contract_eligible_count': 81,
                'repair_candidate_target': 19, 'repair_candidate_written_count': 19, 'repair_candidate_verified_count': 19}
            path.write_text(json.dumps(saved))
            with patch.object(observer, 'process_alive', return_value=True):
                value = observer.generation_progress(root, 'session-counts', plan, reference)
            self.assertEqual((value['written_count'], value['verified_count'], value['contract_eligible_count']), (100, 89, 81))
            self.assertEqual((value['repair_target_count'], value['repair_candidate_verified_count']), (19, 19))
            saved.update(state='complete', verified_count=100)
            path.write_text(json.dumps(saved))
            self.assertEqual(observer.generation_progress(root, 'session-counts', plan, reference)['state'], 'incomplete')
            saved.update(contract_eligible_count=101)
            path.write_text(json.dumps(saved))
            self.assertIsNone(observer.generation_progress(root, 'session-counts', plan, reference))

    def test_frozen_scene_identity_groups_retries_without_exposing_program(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'sf_retry.scene0/revision_0'
            folder.mkdir(parents=True)
            (folder / 'program.json').write_text(json.dumps({'scene_id': 'office_work',
                'title': 'Office', 'answer': 'PRIVATE_ORACLE', 'objects': [{'id': 'secret'}]}))
            value = observer.saved_scene_identity({'artifacts': str(root)}, {'id': 'sf_retry.scene0', 'revision': 0})
            self.assertEqual(value['scene_id'], 'office_work')
            self.assertEqual(value['name'], 'Office')
            self.assertIn('created_at', value)
            self.assertNotIn('PRIVATE_ORACLE', str(value))
            self.assertEqual(observer.saved_scene_identity({'artifacts': str(root)}, {'id': '../outside', 'revision': 0}), {})
            self.assertEqual(observer.saved_scene_identity({'artifacts': str(root)}, {'id': 'sf_retry.scene0', 'revision': -1}), {})

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


class SceneLibraryTest(unittest.TestCase):
    def test_http_catalog_follows_the_backend_cursor(self):
        cursor = {'task_id': 'sf_one.scene0', 'created_at': '1'}
        pages = [{'items': [{'id': 'sf_one.scene0'}], 'next': cursor},
                 {'items': [{'id': 'sf_two.scene0'}], 'next': None}]
        with patch.object(library, 'service_read', side_effect=pages) as metadata:
            self.assertEqual(library.completed_tasks({}), [page['items'][0] for page in pages])
        self.assertEqual([call.args[2] for call in metadata.call_args_list], [{}, {'after': cursor}])

    def fixtures(self, root):
        tasks = []
        for name, session, revision in [('history', 'session-older', 2), ('current', 'session-current', 0)]:
            task_id = 'sf_' + name + '.scene0'
            source = root / 'runtime' / task_id / ('revision_' + str(revision))
            (source / 'capture').mkdir(parents=True)
            (source / 'capture/view_0.png').write_bytes(b'public-frame')
            (source / 'program.json').write_text('{}')
            tasks.append({'id': task_id, 'run_id': 'sf_' + name, 'unit': {'revision': revision, 'intent': {'name': name}},
                          'created_at': '1', 'origin_session': session})
        return tasks

    def test_shared_catalog_selection_persistence_isolation_and_source_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = self.fixtures(root)
            config = {'artifacts': str(root / 'runtime')}
            with patch.object(library, 'completed_tasks', return_value=tasks), patch.object(preview, 'CACHE_ROOT', root / 'previews'):
                initial = library.operate(config, root, 'session-current')
                self.assertEqual(initial['all'], 2)
                self.assertEqual(initial['selection']['selected'], [{'id': 'sf_current.scene0', 'revision': 0}])
                self.assertFalse(initial['selection']['allow_new_scenes'])
                saved = library.operate(config, root, 'session-current', 'save', {
                    'version': 1, 'selected': [{'id': 'sf_history.scene0', 'revision': 2}], 'allow_new_scenes': False})
                self.assertEqual(saved['version'], 2)
                reopened = library.operate(config, root, 'session-current', 'selection')
                self.assertEqual(reopened['sources'][0]['id'], 'sf_history.scene0')
                self.assertIn('revision_2', reopened['sources'][0]['program_path'])
                other = library.operate(config, root, 'session-other')
                self.assertEqual(other['selection']['selected'], [])
                self.assertEqual(library.operate(config, root, 'session-current')['selection']['selected'], saved['selected'])
                with self.assertRaises(library.LibraryError) as stale:
                    library.operate(config, root, 'session-current', 'save', {'version': 1, 'selected': [], 'allow_new_scenes': False})
                self.assertEqual(stale.exception.status, 409)
                tasks[0]['unit']['revision'] = 3
                with self.assertRaises(library.LibraryError) as changed:
                    library.operate(config, root, 'session-current', 'selection')
                self.assertEqual(changed.exception.status, 409)
                with self.assertRaises(library.LibraryError):
                    library.selection_file(root / 'scene-library', '../../another-session')

    def test_library_preview_grants_only_registered_scene_and_excludes_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = self.fixtures(root)
            config = {'artifacts': str(root / 'runtime')}
            with patch.object(library, 'completed_tasks', return_value=tasks), patch.object(preview, 'CACHE_ROOT', root / 'previews'):
                library.operate(config, root, 'session-current')
            with patch.object(library, 'completed_tasks', side_effect=AssertionError('media must not rescan the catalog')), \
                    patch.object(library, 'stage_artifacts', return_value={'safe': True}) as read:
                library.operate(config, root, 'session-current', 'file', task_id='sf_history.scene0', revision=2, file='capture/view_0.png')
                self.assertEqual(read.call_args.kwargs['run_ids'], ['sf_history'])
                with self.assertRaises(library.LibraryError) as missing:
                    library.operate(config, root, 'session-current', 'file', task_id='sf_unregistered.scene0', revision=0, file='capture/view_0.png')
                self.assertEqual(missing.exception.status, 403)
                with self.assertRaises(library.LibraryError) as old:
                    library.operate(config, root, 'session-current', 'file', task_id='sf_history.scene0', revision=1, file='capture/view_0.png')
                self.assertEqual(old.exception.status, 409)
                self.assertEqual(read.call_count, 1)

if __name__ == '__main__':
    unittest.main()
