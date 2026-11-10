import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from spatialforge.generation import GenerationTools
from spatialforge.inference_service import Executor, Jobs, make_server, execute_remote, rewrite_paths


class RemoteInference(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def server(self, executor, *, auth_token=None, state_path=None, max_active=32):
        jobs = Jobs(executor, work_root=self.root, state_path=state_path, max_active=max_active)
        server = make_server(('127.0.0.1', 0), jobs, auth_token=auth_token)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(jobs.shutdown)
        return 'http://127.0.0.1:' + str(server.server_port), jobs

    def test_compute_path_rewrite_preserves_non_model_inputs(self):
        original = {'model_path':'/home/maqiang/model/Qwen/Qwen-Image-Edit-2511',
                    'items':[{'image':'/home/maqiang/GitHub/SpatialForge/runtime/scene.png',
                              'note':'Use /home/maqiang/model/Qwen/Qwen-Image-Edit-2511 naturally'}]}
        rewritten = rewrite_paths(original, {
            '/home/maqiang/model/Qwen/Qwen-Image-Edit-2511':
            '/docker-image/spatialforge-models/Qwen/Qwen-Image-Edit-2511'})
        self.assertEqual(rewritten['model_path'],
                         '/docker-image/spatialforge-models/Qwen/Qwen-Image-Edit-2511')
        self.assertEqual(rewritten['items'], original['items'])

    def test_fit_dispatches_without_local_gpu_or_model_config(self):
        def worker(name, request, work, stop):
            (work/'artifact.txt').write_text('remote artifact')
            return {'status': 'ok', 'value': request['value'], 'tool': name}
        endpoint, _ = self.server(worker)
        tool = GenerationTools(self.root)
        with patch.dict(os.environ, {'SPATIALFORGE_INFERENCE_URL': endpoint}), patch.object(tool, 'gpu', side_effect=AssertionError('local GPU touched')):
            result = tool.execute('sam3', {'value': 7}, self.root/'job', threading.Event())
        self.assertEqual(result['value'], 7)
        self.assertEqual((self.root/'job/artifact.txt').read_text(), 'remote artifact')

    def test_worker_failure_is_not_reported_as_success(self):
        def worker(*args):
            raise RuntimeError('inference failed')
        endpoint, _ = self.server(worker)
        with self.assertRaisesRegex(RuntimeError, 'inference failed'):
            execute_remote(endpoint, 'sam3', {}, self.root/'failed', threading.Event())

    def test_cancel_reaches_running_worker(self):
        canceled = threading.Event()
        def worker(name, request, work, stop):
            stop.wait(5)
            if stop.is_set():
                canceled.set()
                raise RuntimeError('stopped')
        endpoint, _ = self.server(worker)
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(RuntimeError, 'canceled'):
            execute_remote(endpoint, 'sam3', {}, self.root/'cancel', stop)
        self.assertTrue(canceled.wait(2))

    def test_engine_signal_without_wait_completes_and_cancels(self):
        class TaskSignal:
            def __init__(self): self.canceled = False
            def is_set(self): return self.canceled
        signal = TaskSignal()
        started = threading.Event()
        completed = threading.Event()
        canceled = threading.Event()
        def worker(name, request, work, stop):
            started.set()
            if request['cancel']:
                signal.canceled = True
                if stop.wait(5):
                    canceled.set()
                    raise RuntimeError('stopped')
            else:
                completed.wait(5)
                return {'status':'ok', 'artifact':'ready'}
        endpoint, _ = self.server(worker)
        timer = threading.Timer(.1, completed.set)
        timer.start()
        self.addCleanup(timer.join)
        result = execute_remote(endpoint, 'test', {'cancel':False}, self.root/'success', signal)
        self.assertEqual(result['artifact'], 'ready')
        with self.assertRaisesRegex(RuntimeError, 'canceled'):
            execute_remote(endpoint, 'test', {'cancel':True}, self.root/'canceled', signal)
        self.assertTrue(canceled.wait(2))

    def test_executor_uses_only_configured_gpu_and_writes_real_receipt(self):
        (self.root/'worker_fixture.py').write_text('''import argparse,json,os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--response');a=p.parse_args()
r=json.loads(Path(a.request).read_text());Path(r['output']).write_text('produced')
Path(a.response).write_text(json.dumps({'status':'ok','gpu':os.environ['CUDA_VISIBLE_DEVICES'],'output':r['output'],'worker_setting':os.environ['WORKER_SETTING']}))
''')
        executor = Executor({'project':str(self.root), 'environment':{'PYTHONPATH':str(self.root)},
                             'tools':{'test':{'python':sys.executable,'module':'worker_fixture','minimum_mib':2000,
                                 'environment':{'WORKER_SETTING':'per-tool','CUDA_VISIBLE_DEVICES':'0'}}}}, '4')
        work = self.root/'execution'
        with patch('spatialforge.inference_service.subprocess.check_output',return_value='0, 81920\n4, 80000\n'):
            result = executor('test', {'output':str(work/'artifact')}, work, threading.Event())
        self.assertEqual(result['gpu'], '4')
        self.assertEqual(result['worker_setting'], 'per-tool')
        self.assertEqual((work/'artifact').read_text(), 'produced')
        self.assertEqual(json.loads((work/'execution.json').read_text())['exit_code'], 0)

    def test_authenticated_jobs_are_reachable_and_unauthenticated_reads_are_rejected(self):
        endpoint, _ = self.server(lambda *args: {'status': 'ok'}, auth_token='secret-token')
        with self.assertRaises(HTTPError) as failure:
            urlopen(endpoint + '/health', timeout=5)
        self.assertEqual(failure.exception.code, 401)

        request = Request(endpoint + '/health', headers={'Authorization': 'Bearer secret-token'})
        with urlopen(request, timeout=5) as response:
            self.assertEqual(json.load(response)['status'], 'ready')

    def test_non_loopback_listener_requires_authentication(self):
        with self.assertRaisesRegex(ValueError, 'requires an authentication token'):
            make_server(('0.0.0.0', 0), Jobs(lambda *args: None, work_root=self.root))

    def test_work_root_and_active_job_limit_bound_waiting_work(self):
        release = threading.Event()
        worker_started = threading.Event()

        def worker(*args):
            worker_started.set()
            release.wait(5)
            return {'status': 'ok'}

        _, jobs = self.server(worker, max_active=1)
        jobs.submit({'tool': 'fixture', 'request': {}, 'work': str(self.root / 'first')})
        self.assertTrue(worker_started.wait(2))
        with self.assertRaisesRegex(RuntimeError, 'queue is full'):
            jobs.submit({'tool': 'fixture', 'request': {}, 'work': str(self.root / 'second')})
        with self.assertRaisesRegex(ValueError, 'inside the configured inference work root'):
            jobs.submit({'tool': 'fixture', 'request': {}, 'work': str(self.root.parent / 'outside')})
        release.set()

    def test_restart_marks_inflight_job_failed_and_retains_its_identity(self):
        state = self.root / 'jobs.json'
        state.write_text(json.dumps([{
            'id': 'interrupted-job', 'tool': 'fixture', 'work': str(self.root / 'job'),
            'status': 'running', 'submitted': time.time(),
        }]), encoding='utf-8')

        jobs = Jobs(lambda *args: None, work_root=self.root, state_path=state)

        record = jobs.get('interrupted-job')
        self.assertEqual(record['status'], 'failed')
        self.assertIn('restarted', record['error'])
        self.assertEqual(json.loads(state.read_text(encoding='utf-8'))[0]['id'], 'interrupted-job')

    def test_shutdown_cancels_owned_work_and_waits_for_worker_exit(self):
        started = threading.Event()
        canceled = threading.Event()

        def worker(name, request, work, stop):
            started.set()
            stop.wait(5)
            if stop.is_set():
                canceled.set()
                raise RuntimeError('stopped')
            return {'status': 'ok'}

        _, jobs = self.server(worker)
        submitted = jobs.submit({'tool': 'fixture', 'request': {}, 'work': str(self.root / 'shutdown')})
        self.assertTrue(started.wait(2))

        jobs.shutdown(timeout_seconds=2)

        self.assertTrue(canceled.is_set())
        self.assertEqual(jobs.get(submitted['id'])['status'], 'canceled')
        persisted = json.loads((self.root / 'shutdown' / 'remote_job.json').read_text(encoding='utf-8'))
        self.assertEqual(persisted['status'], 'canceled')

    def test_shutdown_does_not_start_a_job_still_preparing_its_receipt(self):
        worker_started = threading.Event()
        receipt_preparing = threading.Event()
        allow_receipt = threading.Event()
        jobs = Jobs(lambda *args: worker_started.set(), work_root=self.root,
                    state_path=self.root / 'jobs.json')
        original_write = jobs._write_work_record
        first_write = True

        def pause_initial_receipt(work, record):
            nonlocal first_write
            if first_write:
                first_write = False
                receipt_preparing.set()
                allow_receipt.wait(2)
            original_write(work, record)

        jobs._write_work_record = pause_initial_receipt
        errors = []

        def submit():
            try:
                jobs.submit({'tool': 'fixture', 'request': {}, 'work': str(self.root / 'racing')})
            except RuntimeError as exc:
                errors.append(str(exc))

        submitter = threading.Thread(target=submit)
        submitter.start()
        self.assertTrue(receipt_preparing.wait(2))
        jobs.shutdown(timeout_seconds=1)
        allow_receipt.set()
        submitter.join(2)

        self.assertFalse(submitter.is_alive())
        self.assertFalse(worker_started.is_set())
        record = json.loads((self.root / 'jobs.json').read_text(encoding='utf-8'))[0]
        receipt = json.loads((self.root / 'racing' / 'remote_job.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(receipt['status'], 'failed')
        self.assertTrue(errors)


if __name__ == '__main__':
    unittest.main()
