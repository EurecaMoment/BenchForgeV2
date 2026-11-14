import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import deployment_config
from benchforge_backend.generation import GenerationTools, generation_defaults
from benchforge_backend.inference_service import execute_remote
from benchforge_backend.provider_config import inference_config, isaac_endpoint
from benchforge_backend.runtime_config import load_service_config
from benchforge_core.model_services.client import ModelService
from dsh.presets import build_preset


ROOT = Path(__file__).resolve().parents[3]


class ProviderConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for key in list(os.environ):
            if key.startswith(('BENCHFORGE_', 'SPATIALFORGE_')):
                os.environ.pop(key)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.config = root / 'config'
        self.config.mkdir()
        self.template = ROOT / 'config/benchforge.example.json'
        (self.config / self.template.name).write_bytes(self.template.read_bytes())
        self.local = self.config / 'benchforge.local.json'
        self.generated = self.config / 'generated'
        self.server = self.generated / deployment_config.SERVER_CONFIG
        self.state = root / '.benchforge/backend'

    def sync(self):
        return deployment_config.sync_configuration(self.config, self.generated, self.server, self.state)

    def test_new_config_uses_only_submodule_providers_and_can_start_unconfigured(self):
        self.sync()
        config = deployment_config.read_object(self.local)
        providers = deployment_config.read_object(ROOT / 'third_party/dependencies.json')['provider_submodules']
        self.assertEqual(config['providers'].keys(), providers.keys())
        self.assertNotIn('models', config)
        self.assertNotIn('client', config)
        self.assertEqual(build_preset.model_patches(self.local), [])
        self.assertEqual(build_preset.model_tools(self.local), [])
        self.assertTrue((self.generated / 'scene-library/policy.json').is_file())
        os.environ.update(deployment_config.read_env(self.generated / 'database.env'))
        service = load_service_config(self.server)
        tools = GenerationTools(service['artifacts'])
        with self.assertRaisesRegex(ValueError, 'Configure inference.url'):
            tools.config

    def test_v2_migration_preserves_private_settings_and_selects_the_six_providers(self):
        legacy = {
            'config_version': 2,
            'web': {'port': 3099},
            'server': {'port': 3858, 'artifacts': '../archive'},
            'database': {'project': 'preserved-db', 'port': 55223},
            'models': {
                'qwen': {'model': 'served-model', 'url': 'https://llm.example.net/v1/chat/completions',
                         'token_env': 'FIXTURE_LLM_TOKEN'},
                'vlm': {'model': 'vision-model', 'url': 'https://vision.example.net/v1'},
                'sam3d': {'path': '/old-weights', 'python': '/old-python'},
            },
            'model_roles': {'dsh': 'qwen', 'scene': 'vlm', 'annotation': 'qwen'},
            'generation': {'mode': 'remote', 'service': 'model_services'},
            'model_services': {
                'url': 'https://gateway.example.net', 'token_env': 'FIXTURE_GATEWAY_TOKEN',
                'tools': {'diffusion': {'request_defaults': {'steps': 6}}, 'yoloe': {}},
            },
            'services': {'yoloe': {'url': 'https://old.example.net'}},
            'isaac': {'grpc': {'host': 'YOUR_ISAAC_GRPC_HOST', 'port': 50051, 'timeout_seconds': 60}},
            'worker': {'isaac_grpc': {'host': '192.0.2.12', 'port': 50054}, 'capture_timeout_seconds': 901,
                       'runs': 'D:/captures'},
        }
        deployment_config.write(self.local, legacy)
        self.sync()
        current = deployment_config.read_object(self.local)
        self.assertEqual(current['config_version'], 3)
        for key in ('services', 'model_services', 'model_roles', 'models', 'generation', 'isaac'):
            self.assertNotIn(key, current)
        self.assertEqual(current['web']['port'], 3099)
        self.assertEqual(current['database']['project'], 'preserved-db')
        self.assertEqual(current['providers']['FastFLUX2Klein']['request_defaults']['steps'], 6)
        self.assertEqual(current['inference']['token_env'], 'FIXTURE_GATEWAY_TOKEN')
        self.assertEqual(deployment_config.read_object(self.state / 'benchforge-before-v3.json'), legacy)
        worker = deployment_config.read_object(self.generated / 'worker.local.json')
        self.assertEqual(isaac_endpoint(worker['isaac_grpc']), '192.0.2.12:50054')
        self.assertEqual(worker['capture_timeout_seconds'], 901)
        self.assertEqual(current['worker']['runs'], 'D:/captures')
        host_model = build_preset.model_patches(self.local)
        dsh = host_model[0]['config']['providers']['benchforge-models']
        self.assertEqual(dsh['baseURL'], 'https://llm.example.net/v1')
        self.assertEqual(dsh['apiKeyEnv'], 'FIXTURE_LLM_TOKEN')
        self.assertNotIn('model_yoloe', build_preset.model_tools(self.local))
        self.assertIn('model_trellis', build_preset.model_tools(self.local))
        os.environ.update(deployment_config.read_env(self.generated / 'database.env'))
        service = load_service_config(self.server)
        self.assertEqual(service['model_id'], 'vision-model')
        self.assertEqual(Path(service['task_root']), Path(service['artifacts']) / 'operator_workspaces')
        self.sync()
        self.assertEqual(deployment_config.read_object(self.local), current)

    def test_gateway_defaults_and_routes_use_the_same_registry(self):
        registry = deployment_config.read_object(self.template)
        records = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                records.append((self.path, body, self.headers.get('Authorization')))
                if self.path.endswith('/health'):
                    response = {'available': True, 'tool': self.path.split('/')[2]}
                else:
                    response = {'id': 'fixture-job', 'status': 'completed', 'result': {'status': 'ok'}}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                endpoint = f'http://127.0.0.1:{server.server_port}'
                registry['inference'].update(url=endpoint, token_env='FIXTURE_GATEWAY_TOKEN')
                registry['providers']['FastTrellis2']['gateway_tool'] = 'reconstruct'
                registry['providers']['FastFLUX2Klein']['request_defaults']['steps'] = 8
                deployment_config.write(self.local, registry)
                self.sync()
                os.environ.update(deployment_config.read_env(self.generated / 'database.env'))
                os.environ['FIXTURE_GATEWAY_TOKEN'] = 'fixture-only'
                load_service_config(self.server)
                config = inference_config(registry)
                work = self.config.parent / 'fixture-work'
                direct = ModelService(config)
                direct.call('diffusion', request={'prompt': 'fixture'}, work=work)
                self.assertEqual(generation_defaults('diffusion')['steps'], 8)
                execute_remote(endpoint, 'diffusion', {'prompt': 'fixture'}, work, threading.Event(), config=config)
                direct.call('trellis', request={'objects': []}, work=work)
                execute_remote(endpoint, 'sam3d', {'objects': []}, work, threading.Event(), config=config)
                jobs = [body for path, body, _ in records if path == '/jobs']
                self.assertEqual(jobs[0], jobs[1])
                self.assertEqual(jobs[0]['request']['steps'], 8)
                self.assertEqual(jobs[2], jobs[3])
                self.assertEqual(jobs[2]['tool'], 'reconstruct')
                self.assertEqual(jobs[2]['request']['provider'], 'trellis2')
                self.assertEqual([path for path, _, _ in records if path != '/jobs'],
                                 ['/tools/diffusion/health'] * 2 + ['/tools/reconstruct/health'] * 2)
                self.assertTrue(all(token == 'Bearer fixture-only' for _, _, token in records))
            finally:
                server.shutdown()
                thread.join()

    def test_invalid_provider_and_placeholder_are_rejected_before_projection(self):
        registry = deployment_config.read_object(self.template)
        registry['providers']['unrelated'] = {}
        deployment_config.write(self.local, registry)
        with self.assertRaisesRegex(ValueError, 'Unknown providers'):
            self.sync()
        registry['providers'].pop('unrelated')
        registry['providers']['IssacSim4A100']['grpc']['host'] = 'YOUR_ISAAC_GRPC_HOST'
        deployment_config.write(self.local, registry)
        with self.assertRaisesRegex(ValueError, 'IssacSim4A100.grpc.host'):
            self.sync()
        self.assertFalse(self.server.exists())
