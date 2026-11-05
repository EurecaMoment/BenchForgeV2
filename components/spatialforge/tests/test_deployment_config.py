import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatialforge.runtime_config import RuntimeConfig, load_service_config


class DeploymentConfig(unittest.TestCase):
    def test_only_requested_model_needs_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / 'models.json'
            path.write_text(json.dumps({'models': {'sam3': {'python': 'venv/bin/python', 'path': 'weights'}},
                                        'sources': {'sam3': 'source'}}))
            config = RuntimeConfig(path)
            self.assertEqual(config.model('sam3')['python'], str(root / 'venv/bin/python'))
            self.assertEqual(config.data['sources']['sam3'], str(root / 'source'))
            with self.assertRaisesRegex(ValueError, 'Configure models.flux'):
                config.model('flux')

    def test_private_config_credentials_and_derived_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / 'server.json'
            path.write_text(json.dumps({'operator_token':'operator','worker_token':'worker',
                                        'artifacts':'artifacts','harness':'harness','models_config':'models.json',
                                        'model_id':'my-vision-model','gpu_candidates':'2'}))
            config = load_service_config(path)
            self.assertEqual(config['operator_token'], 'operator')
            self.assertEqual(os.environ['SPATIALFORGE_MODEL_ID'], 'my-vision-model')
            self.assertEqual(os.environ['SPATIALFORGE_GPU_CANDIDATES'], '2')
            self.assertEqual(config['artifacts'], str(root / 'artifacts'))

    def test_config_directory_keeps_workspace_scene_policy_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            config_dir = root / 'config'
            config_dir.mkdir()
            policy = root / 'scene-library' / 'policy.json'
            policy.parent.mkdir()
            policy.write_text('{}')
            path = config_dir / 'server.json'
            path.write_text(json.dumps({'operator_token':'operator','worker_token':'worker'}))
            with patch.dict(os.environ):
                os.environ.pop('SPATIALFORGE_SCENE_POLICY', None)
                load_service_config(path)
                self.assertEqual(os.environ['SPATIALFORGE_SCENE_POLICY'], str(policy))


if __name__ == '__main__':
    unittest.main()
