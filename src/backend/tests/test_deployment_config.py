import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchforge_backend.runtime_config import load_service_config, load_worker_config


class DeploymentConfig(unittest.TestCase):
    def test_private_config_credentials_and_derived_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / 'server.json'
            policy = root / 'policy.json'
            policy.write_text(json.dumps({'enabled': True, 'enforce_realism': True}))
            path.write_text(json.dumps({'operator_token':'operator','worker_token':'worker',
                                        'artifacts':'artifacts','harness':'harness',
                                        'scene_policy_path':'policy.json', 'model_id':'my-vision-model'}))
            with patch.dict(os.environ, {}, clear=True):
                config = load_service_config(path)
                self.assertEqual(config['operator_token'], 'operator')
                self.assertEqual(os.environ['BENCHFORGE_MODEL_ID'], 'my-vision-model')
                self.assertEqual(config['artifacts'], str(root / 'artifacts'))

    def test_config_directory_keeps_workspace_scene_policy_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            config_dir = root / 'config'
            config_dir.mkdir()
            policy = root / 'scene-library' / 'policy.json'
            policy.parent.mkdir()
            policy.write_text(json.dumps({'enabled': True, 'enforce_realism': True}))
            path = config_dir / 'server.json'
            path.write_text(json.dumps({'operator_token':'operator','worker_token':'worker'}))
            with patch.dict(os.environ):
                os.environ.pop('BENCHFORGE_SCENE_POLICY', None)
                os.environ['BENCHFORGE_EXECUTION_MODE'] = 'exploration'
                load_service_config(path)
                self.assertEqual(os.environ['BENCHFORGE_SCENE_POLICY'], str(policy))

    def test_relative_environment_paths_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            config_dir = root / 'config'
            config_dir.mkdir()
            policy = config_dir / 'scene-policy.json'
            policy.write_text(json.dumps({'enabled': True, 'enforce_realism': True}))
            path = config_dir / 'server.json'
            path.write_text(json.dumps({'operator_token_env': 'OPERATOR_TOKEN', 'worker_token_env': 'WORKER_TOKEN',
                                        'artifacts': '${ARTIFACT_ROOT}', 'scene_policy_path': 'scene-policy.json'}))
            with patch.dict(os.environ, {'ARTIFACT_ROOT': 'artifacts', 'OPERATOR_TOKEN': 'from-env',
                                         'WORKER_TOKEN': 'worker', 'BENCHFORGE_EXECUTION_MODE': 'production'}, clear=True):
                config = load_service_config(path)
            self.assertEqual(config['artifacts'], str(config_dir / 'artifacts'))
            self.assertEqual(config['operator_token'], 'from-env')
            self.assertEqual(config['scene_policy_path'], str(policy))
            path.write_text('{"operator_token":"first","operator_token":"second"}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key: operator_token'):
                load_service_config(path)

    def test_production_requires_a_real_policy_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'server.json'
            path.write_text(json.dumps({'operator_token': 'operator', 'worker_token': 'worker'}))
            with patch.dict(os.environ, {'BENCHFORGE_EXECUTION_MODE': 'production'}, clear=True):
                with self.assertRaisesRegex(ValueError, 'execution_mode=production requires scene_policy_path'):
                    load_service_config(path)

    def test_production_rejects_a_disabled_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            policy = root / 'policy.json'
            policy.write_text('{"enabled":true}')
            path = root / 'server.json'
            path.write_text(json.dumps({'operator_token': 'operator', 'worker_token': 'worker',
                                        'scene_policy_path': str(policy)}))
            with patch.dict(os.environ, {'BENCHFORGE_EXECUTION_MODE': 'production'}, clear=True):
                with self.assertRaisesRegex(ValueError, 'enabled scene policy with enforce_realism=true'):
                    load_service_config(path)

    def test_worker_connection_defaults_derive_from_the_server_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            server = root / 'benchforge-server.local.json'
            server.write_text(json.dumps({'port': 3941, 'worker_token': 'fixture-worker'}))
            worker = root / 'worker.local.json'
            worker.write_text(json.dumps({'service_config': server.name, 'runs': 'runs'}))
            config = load_worker_config(worker)
        self.assertEqual(config['url'], 'http://127.0.0.1:3941')
        self.assertEqual(config['worker_token'], 'fixture-worker')
        self.assertEqual(config['ssh_forward'], '3941:127.0.0.1:3941')
        self.assertEqual(config['runs'], str(root / 'runs'))

    def test_explicit_worker_url_remains_an_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            server = root / 'server.json'
            server.write_text(json.dumps({'port': 3941, 'worker_token': 'fixture-worker'}))
            worker = root / 'worker.json'
            worker.write_text(json.dumps({'service_config': 'server.json', 'url': 'https://worker.example.net/api'}))
            config = load_worker_config(worker)
        self.assertEqual(config['url'], 'https://worker.example.net/api')


if __name__ == '__main__':
    unittest.main()
