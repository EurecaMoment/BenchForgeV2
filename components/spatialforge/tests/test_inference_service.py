import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import sys

from spatialforge.generation import GenerationTools
from spatialforge.inference_service import Executor, Jobs, make_server, execute_remote, rewrite_paths


class RemoteInference(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def server(self, executor):
        server = make_server(('127.0.0.1', 0), Jobs(executor))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:' + str(server.server_port)

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
        endpoint = self.server(worker)
        tool = GenerationTools(self.root)
        with patch.dict(os.environ, {'SPATIALFORGE_INFERENCE_URL': endpoint}), patch.object(tool, 'gpu', side_effect=AssertionError('local GPU touched')):
            result = tool.execute('sam3', {'value': 7}, self.root/'job', threading.Event())
        self.assertEqual(result['value'], 7)
        self.assertEqual((self.root/'job/artifact.txt').read_text(), 'remote artifact')

    def test_worker_failure_is_not_reported_as_success(self):
        def worker(*args):
            raise RuntimeError('inference failed')
        endpoint = self.server(worker)
        with self.assertRaisesRegex(RuntimeError, 'inference failed'):
            execute_remote(endpoint, 'sam3', {}, self.root/'failed', threading.Event())

    def test_cancel_reaches_running_worker(self):
        canceled = threading.Event()
        def worker(name, request, work, stop):
            stop.wait(5)
            if stop.is_set():
                canceled.set()
                raise RuntimeError('stopped')
        endpoint = self.server(worker)
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
        endpoint = self.server(worker)
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


if __name__ == '__main__':
    unittest.main()
