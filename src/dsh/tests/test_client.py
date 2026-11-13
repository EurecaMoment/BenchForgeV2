import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('benchforge_client', Path(__file__).parents[1]/'cli.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

class ClientTests(unittest.TestCase):
    def test_real_post_routes_and_auth(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                requests.append((self.path, self.headers['Authorization'], json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"state":"PENDING"}')
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            config = {'service_url': f'http://127.0.0.1:{server.server_port}/', 'operator_token': 'test-only'}
            self.assertEqual(client.status(config), {'state': 'PENDING'})
            self.assertEqual(client.status(config, 'sf_example'), {'state': 'PENDING'})
            self.assertEqual(requests, [('/catalog', 'Bearer test-only', {}), ('/observe', 'Bearer test-only', {'run_id': 'sf_example'})])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_missing_credentials_does_not_claim_offline_success(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'operator_token'):
                client.status({'service_url': 'http://127.0.0.1:1'})

    def test_load_config_follows_local_service_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'scene-library').mkdir()
            (root/'scene-library/policy.json').write_text(
                '{"enabled":true,"enforce_realism":true}', encoding='utf-8')
            (root/'server.local.json').write_text(json.dumps({
                'port': 3941, 'operator_token_env': 'BENCHFORGE_TEST_TOKEN',
                'execution_mode': 'production', 'scene_policy_path': 'scene-library/policy.json',
            }), encoding='utf-8')
            client_config = root/'benchforge-client.local.json'
            client_config.write_text('{"service_config":"server.local.json"}', encoding='utf-8')
            with patch.dict(os.environ, {'BENCHFORGE_TEST_TOKEN': 'fixture-token'}, clear=True):
                loaded = client.load_config(client_config)
        self.assertEqual(loaded['service_url'], 'http://127.0.0.1:3941')
        self.assertEqual(loaded['operator_token'], 'fixture-token')
        self.assertEqual(loaded['execution_mode'], 'production')
