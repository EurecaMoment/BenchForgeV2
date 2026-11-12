import json
import csv
import io
import os
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from benchforge_core.runtime import Runtime, write, jsonl, read, rows, select
from benchforge_core.geometry import pinhole_camera, axial_depth_to_range


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def evidence(self, kind='official'):
        write(self.root/'raw.json', {'answer': 'left'})
        jsonl(self.root/'input.jsonl', [{'id':'e1','media':[],
            'facts':{'answer':'forged'},'selectors':{'answer':'/answer'},
            'provenance':{'kind':kind,'path':'raw.json'}}])
        return self.runtime.call('evidence', {'input':str(self.root/'input.jsonl')})

    def build(self, evidence):
        jsonl(self.root/'items.jsonl',[{'id':'q1','question':'Where is it?',
            'evidence_id':'e1','answer_field':'answer','answer':'forged','metadata':{'secret':1}}])
        return self.runtime.call('build',{'evidence':evidence['evidence'],'items':str(self.root/'items.jsonl')})

    def test_source_replay_and_public_authority_separation(self):
        evidence=self.evidence()
        self.assertEqual(rows(evidence['evidence'])[0]['facts']['answer'],'left')
        package=self.build(evidence)
        self.assertEqual(rows(Path(package['authority'])/'gold.jsonl')[0]['answer'],'left')
        with zipfile.ZipFile(package['package']) as archive:
            self.assertEqual(archive.namelist(), ['media/', 'items.jsonl'])
            item=json.loads(archive.read('items.jsonl'))
            self.assertEqual(set(item), {'id','question','media'})

    def test_prediction_not_promoted_and_failure_is_durable(self):
        with self.assertRaisesRegex(ValueError,'Prediction-only'):
            self.build(self.evidence('prediction'))
        self.assertEqual(self.runtime.call('status',{})['operations'][0]['state'],'failed')

    def test_evaluation_missing_and_duplicate_ids(self):
        package=self.build(self.evidence())
        jsonl(self.root/'predictions.jsonl',[])
        request={'authority':package['authority'],'predictions':str(self.root/'predictions.jsonl')}
        score=self.runtime.call('evaluate',request)
        self.assertEqual((score['missing'],score['accuracy']),(1,0))
        jsonl(self.root/'predictions.jsonl',[{'id':'q1','answer':'left'}]*2)
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            self.runtime.call('evaluate',request)

    def test_pointer_escapes_and_empty_key(self):
        self.assertEqual(select({'a/b':{'':2}},'/a~1b/'),2)

    def test_legacy_and_shared_json_readers_accept_utf8_bom(self):
        from benchforge_core.artifacts import read as legacy_read, rows as legacy_rows
        from benchforge_core.artifact_io import read_json, read_jsonl

        json_path = self.root / 'bom.json'
        jsonl_path = self.root / 'bom.jsonl'
        json_path.write_bytes(b'\xef\xbb\xbf{"answer":"ok"}')
        jsonl_path.write_bytes(b'\xef\xbb\xbf{"item_id":"one"}\n')

        expected_json = {'answer': 'ok'}
        expected_rows = [{'item_id': 'one'}]
        self.assertEqual(read_json(json_path), expected_json)
        self.assertEqual(legacy_read(json_path), expected_json)
        self.assertEqual(read_jsonl(jsonl_path), expected_rows)
        self.assertEqual(legacy_rows(jsonl_path), expected_rows)

    def test_range_order_can_differ_from_axial_depth(self):
        camera=pinhole_camera(640,480)
        self.assertEqual(axial_depth_to_range(2,camera['cx'],camera['cy'],camera),2)
        self.assertGreater(axial_depth_to_range(2,0,0,camera),axial_depth_to_range(2.3,camera['cx'],camera['cy'],camera))

    def test_missing_backend_has_setup_guidance(self):
        with self.assertRaisesRegex(ValueError, 'Configure services.sam3.url'):
            self.runtime.call('sam3', {'payload':{}})

    def test_collector_help_is_not_a_failed_capture(self):
        self.runtime.config={'collectors':{'habitat':{'command':[sys.executable,'-c','print("usage: habitat --scenes")']}}}
        result=self.runtime.call('habitat',{'argv':['--help']})
        self.assertIn('--scenes',result['help'])
        self.assertFalse(result['capture_started'])

    def test_collector_timeout_reaps_child_process(self):
        # 使用 carla 本地采集路径验证超时后子进程被清理；
        # isaac 采集已改为远程 gRPC（需 scene_program），不再走本地 subprocess。
        script = self.root / 'spawns_child.py'
        child_pid_path = self.root / 'child.pid'
        script.write_text(
            'import subprocess, sys, time\n'
            f'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            f'open({str(child_pid_path)!r}, "w").write(str(child.pid))\n'
            'time.sleep(60)\n',
            encoding='utf-8',
        )
        self.runtime.config = {
            'collectors': {'carla': {'command': [sys.executable], 'script': str(script)}}
        }

        with self.assertRaises(subprocess.TimeoutExpired):
            self.runtime.call('carla', {'timeout_seconds': 0.5})

        child_pid = int(child_pid_path.read_text(encoding='utf-8'))
        for _ in range(30):
            if os.name == 'nt':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {child_pid}', '/FO', 'CSV', '/NH'],
                    capture_output=True, text=True, check=False,
                )
                rows = csv.reader(io.StringIO(result.stdout))
                alive = any(len(row) > 1 and row[1].strip() == str(child_pid) for row in rows)
            else:
                stat = Path(f'/proc/{child_pid}/stat')
                alive = stat.exists() and stat.read_text().split()[2] != 'Z'
            if not alive:
                break
            time.sleep(0.1)
        self.assertFalse(alive, f'collector child process {child_pid} survived timeout cleanup')

    def test_depth_array_stays_private(self):
        evidence=self.evidence()
        record=rows(evidence['evidence'])[0]
        depth=self.root/'depth.npy'
        depth.write_bytes(b'raw simulator evidence')
        record['media']=[str(depth)]
        jsonl(evidence['evidence'],[record])
        with self.assertRaisesRegex(ValueError,'private assets'):
            self.build(evidence)
        record['media']=[]
        record['assets']=[str(depth)]
        jsonl(evidence['evidence'],[record])
        package=self.build(evidence)
        gold=rows(Path(package['authority'])/'gold.jsonl')[0]
        self.assertEqual((Path(package['authority'])/gold['assets'][0]).read_bytes(),depth.read_bytes())
        with zipfile.ZipFile(package['package']) as archive:
            self.assertFalse(any(name.endswith('.npy') for name in archive.namelist()))

    def test_http_contract_without_starting_services(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"masks":[]}')
            def log_message(self,*args):
                pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            self.runtime.config={'services':{'sam3':{'url':f'http://127.0.0.1:{server.server_port}'}}}
            result=self.runtime.call('sam3',{'payload':{'image_path':'image.png','text_prompt':'chair'}})
            self.assertEqual(requests,[('/image/infer',{'image_path':'image.png','text_prompt':'chair'})])
            self.assertFalse(result['gt_written'])
            self.runtime.config = {'model_roles': {'annotation': 'qwen'}, 'models': {
                'qwen': {'url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'fixture-vlm'}}}
            self.runtime.call('llm_local', {'payload': {'messages': []}})
            self.assertEqual(requests[-1], ('/v1/chat/completions',
                                           {'messages': [], 'model': 'fixture-vlm'}))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__=='__main__':
    unittest.main()
