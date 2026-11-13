import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchforge_core.service_config import load_service_client_config


class ServiceClientConfig(unittest.TestCase):
    def test_default_projection_falls_back_to_a_legacy_local_client_only_if_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config'
            generated = config / 'generated'
            generated.mkdir(parents=True)
            legacy = config / 'spatialforge.local.json'
            legacy.write_text(json.dumps({'service_url': 'https://legacy.invalid',
                                          'operator_token': 'test-only', 'execution_mode': 'exploration'}),
                              encoding='utf-8')
            client = generated / 'benchforge-client.local.json'
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_service_client_config(client)['service_url'], 'https://legacy.invalid')
                client.write_text('{"port":1,"port":2}', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                    load_service_client_config(client)

    def test_relative_policy_and_port_fallback_resolve_from_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_dir = root / 'config'
            config_dir.mkdir()
            policy = config_dir / 'policy.json'
            policy.write_text(json.dumps({'enabled': True, 'enforce_realism': True}))
            config = config_dir / 'service.local.json'
            config.write_text(json.dumps({'port': 3942, 'operator_token': 'fixture-token',
                                          'execution_mode': 'production', 'scene_policy_path': 'policy.json'}))
            value = load_service_client_config(config)
        self.assertEqual(value['service_url'], 'http://127.0.0.1:3942')
        self.assertEqual(value['scene_policy_path'], str(policy.resolve()))
        self.assertEqual(value['execution_mode'], 'production')
        self.assertEqual(value['operator_token'], 'fixture-token')

    def test_environment_paths_and_token_environment_override_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'policy.json').write_text('{"enabled":true,"enforce_realism":true}')
            config = root / 'service.json'
            config.write_text(json.dumps({'port': 3841, 'operator_token': 'stale',
                                          'operator_token_env': 'OPERATOR_TOKEN',
                                          'execution_mode': 'production',
                                          'scene_policy_path': '${POLICY_FILE}'}))
            with patch.dict(os.environ, {'POLICY_FILE': str(root / 'policy.json'),
                                         'OPERATOR_TOKEN': 'environment-token'}, clear=True):
                value = load_service_client_config(config)
        self.assertEqual(value['operator_token'], 'environment-token')
        self.assertEqual(value['scene_policy_path'], str((root / 'policy.json').resolve()))

    def test_legacy_projection_and_env_references_resolve_new_config_and_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            generated = Path(folder) / 'config' / 'generated'
            generated.mkdir(parents=True)
            server = generated / 'benchforge-server.local.json'
            server.write_text(json.dumps({'operator_token_env': 'SPATIALFORGE_OPERATOR_TOKEN',
                                          'execution_mode': 'exploration'}), encoding='utf-8')
            client = generated / 'benchforge-client.local.json'
            client.write_text(json.dumps({'service_config': 'spatialforge-server.local.json'}), encoding='utf-8')
            with patch.dict(os.environ, {'BENCHFORGE_OPERATOR_TOKEN': 'canonical-test-token',
                                         'SPATIALFORGE_SERVICE_URL': 'https://legacy.invalid'}, clear=True):
                value = load_service_client_config(generated / 'spatialforge.local.json')
            self.assertEqual(value['operator_token'], 'canonical-test-token')
            self.assertEqual(value['service_url'], 'https://legacy.invalid')

    def test_duplicate_json_fields_and_invalid_production_policy_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'service.json'
            config.write_text('{"operator_token":"one","operator_token":"two"}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key: operator_token'):
                load_service_client_config(config)
            policy = root / 'policy.json'
            policy.write_text('{"enabled":false}')
            config.write_text(json.dumps({'operator_token': 'fixture', 'execution_mode': 'production',
                                          'scene_policy_path': str(policy)}))
            with self.assertRaisesRegex(ValueError, 'enabled scene policy with enforce_realism=true'):
                load_service_client_config(config)

    def test_exploration_may_omit_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'service.json'
            config.write_text(json.dumps({'operator_token': 'fixture', 'execution_mode': 'exploration'}))
            value = load_service_client_config(config)
        self.assertIsNone(value['scene_policy_path'])
        self.assertEqual(value['execution_mode'], 'exploration')

    def test_configured_mode_rejects_conflicting_environment_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            policy = root / 'policy.json'
            policy.write_text('{"enabled":true,"enforce_realism":true}')
            config = root / 'service.json'
            config.write_text(json.dumps({'operator_token': 'fixture', 'execution_mode': 'production',
                                          'scene_policy_path': str(policy)}))
            with patch.dict(os.environ, {'BENCHFORGE_EXECUTION_MODE': 'exploration'}, clear=True):
                with self.assertRaisesRegex(ValueError, 'conflicts with configured execution_mode'):
                    load_service_client_config(config)


if __name__ == '__main__':
    unittest.main()
