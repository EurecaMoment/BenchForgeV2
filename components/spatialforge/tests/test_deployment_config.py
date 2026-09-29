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
            path = Path(folder) / 'models.json'
            path.write_text(json.dumps({'models': {'sam3': {'python': 'venv/bin/python', 'path': 'weights'}},
                                        'sources': {'sam3': 'source'}}))
            config = RuntimeConfig(path)
            self.assertEqual(config.model('sam3')['python'], str(Path(folder) / 'venv/bin/python'))
            self.assertEqual(config.data['sources']['sam3'], str(Path(folder) / 'source'))
            with self.assertRaisesRegex(ValueError, 'Configure models.flux'):
                config.model('flux')

    def test_private_config_and_environment_credentials(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'SF_OPERATOR':'operator','SF_WORKER':'worker'}, clear=True):
            path = Path(folder) / 'server.json'
            path.write_text(json.dumps({'operator_token_env':'SF_OPERATOR','worker_token_env':'SF_WORKER',
                                        'artifacts':'artifacts','harness':'harness','models_config':'models.json',
                                        'model_id':'my-vision-model','gpu_candidates':'2'}))
            config = load_service_config(path)
            self.assertEqual(config['operator_token'], 'operator')
            self.assertEqual(os.environ['SPATIALFORGE_MODEL_ID'], 'my-vision-model')
            self.assertEqual(os.environ['SPATIALFORGE_GPU_CANDIDATES'], '2')
            self.assertEqual(config['artifacts'], str(Path(folder) / 'artifacts'))


if __name__ == '__main__':
    unittest.main()
