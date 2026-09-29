import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spatialforge_client', Path(__file__).parents[1]/'cli.py')
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
            with patch.dict('os.environ', {'SF_TEST_TOKEN': 'test-only'}):
                config = {'service_url': f'http://127.0.0.1:{server.server_port}/', 'operator_token_env': 'SF_TEST_TOKEN'}
                self.assertEqual(client.status(config), {'state': 'PENDING'})
                self.assertEqual(client.status(config, 'sf_example'), {'state': 'PENDING'})
            self.assertEqual(requests, [('/catalog', 'Bearer test-only', {}), ('/observe', 'Bearer test-only', {'run_id': 'sf_example'})])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_missing_credentials_does_not_claim_offline_success(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'SPATIALFORGE_OPERATOR_TOKEN'):
                client.status({'service_url': 'http://127.0.0.1:1'})
