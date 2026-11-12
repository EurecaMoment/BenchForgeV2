"""Regression coverage for the single operator-owned model configuration."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.dsh.build_preset import Loader, model_patches, refresh_model_patches, yaml
import spatialforge_app
from spatialforge.runtime_config import RuntimeConfig, load_service_config
from integrations.tests.test_install_config import local_configuration

ROOT = Path(__file__).resolve().parents[2]


class UnifiedModelConfig(unittest.TestCase):
    def test_existing_paths_and_scene_model_migrate_without_changing_credentials(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            old_models = config / 'models.local.json'
            old_models.write_text(json.dumps({
                'models': {'flux': {'python': '../venv/bin/python', 'path': '../weights'}},
                'sources': {'sam3': '../sam3-source'},
            }), encoding='utf8')
            server = {'port': 3857, 'operator_token': 'operator', 'worker_token': 'worker',
                      'database_url': 'existing-private-database', 'models_config': old_models.name,
                      'model_url': 'https://scene.example/v1', 'model_id': 'scene-vlm',
                      'model_api_key_env': 'SCENE_SECRET'}
            spatialforge_app.write(spatialforge_app.SERVER, server)
            registry = config / 'benchforge.local.json'
            registry.write_text(json.dumps({'models': {'qwen': {
                'url': 'https://annotation.example/v1', 'model': 'annotation-vlm'}},
                'model_services': {'url': 'https://inference.example'}}), encoding='utf8')
            spatialforge_app._init_configs(3841, 55432)
            saved = json.loads(spatialforge_app.SERVER.read_text(encoding='utf8'))
            self.assertEqual(saved['operator_token'], server['operator_token'])
            self.assertEqual(saved['database_url'], server['database_url'])
            self.assertNotIn('model_url', saved)
            self.assertEqual(saved['models_config'], registry.name)
            value = json.loads(registry.read_text(encoding='utf8'))
            self.assertEqual(value['models']['qwen']['model'], 'annotation-vlm')
            self.assertEqual(value['models']['scene']['model'], 'scene-vlm')
            self.assertEqual(value['model_roles']['scene'], 'scene')
            self.assertEqual(value['model_services']['url'], 'https://inference.example')
            self.assertEqual(value['generation']['mode'], 'local')
            loaded = RuntimeConfig(registry)
            self.assertEqual(loaded.model('flux')['path'], str(config.parent / 'weights'))
            self.assertEqual(loaded.data['sources']['sam3'], str(config.parent / 'sam3-source'))
            self.assertTrue(old_models.is_file())
            before = registry.read_text(encoding='utf8')
            spatialforge_app.sync_model_config()
            self.assertEqual(registry.read_text(encoding='utf8'), before)

    def test_one_registry_drives_backend_generation_and_dsh_without_serializing_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            registry = root / 'benchforge.json'
            value = json.loads((ROOT / 'config/benchforge.example.json').read_text(encoding='utf8'))
            value['models']['qwen'].update(url='https://vlm.example/v1', model='vision-model',
                                           token_env='VLM_SECRET')
            registry.write_text(json.dumps(value), encoding='utf8')
            server = root / 'server.json'
            server.write_text(json.dumps({'execution_mode': 'exploration', 'operator_token': 'o',
                                          'worker_token': 'w', 'models_config': registry.name}), encoding='utf8')
            with patch.dict(os.environ, {'VLM_SECRET': 'do-not-serialize',
                                        'SPATIALFORGE_MODEL_URL': 'https://stale.example',
                                        'SPATIALFORGE_INFERENCE_URL': 'https://stale-inference'}, clear=True):
                loaded = load_service_config(server)
                self.assertEqual(loaded['model_id'], 'vision-model')
                self.assertEqual(os.environ['SPATIALFORGE_MODEL_URL'], 'https://vlm.example/v1')
                self.assertEqual(os.environ['SPATIALFORGE_INFERENCE_URL'], value['model_services']['url'])
                patches = model_patches(registry)
            self.assertNotIn('do-not-serialize', json.dumps(patches))
            provider = patches[0]['config']['providers']['benchforge-models']
            self.assertEqual(provider['baseURL'], loaded['model_url'])
            self.assertEqual(provider['apiKeyEnv'], 'VLM_SECRET')
            self.assertEqual(patches[1]['config']['model'], loaded['model_id'])

    def test_refresh_preserves_custom_presets_ui_and_other_providers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = root / 'models.json'
            value = {'model_roles': {'dsh': 'qwen'}, 'models': {
                'qwen': {'url': 'https://vlm.example/v1', 'model': 'first-model'}}}
            registry.write_text(json.dumps(value), encoding='utf8')
            preset = root / 'preset.yml'
            profile = [{'insert': [{'id': 'existing-preset', 'config': {'workspace': 'keep-session'}}]},
                       {'id': 'llm-pi-ai', 'config': {'providers': {'colleague': {'baseURL': 'https://other'}}}},
                       {'id': 'other-plugin', 'config': {'retained': True}}]
            preset.write_text(yaml.safe_dump(profile), encoding='utf8')
            before = deepcopy(profile)
            refresh_model_patches(preset, registry)
            value['models']['qwen']['model'] = 'second-model'
            registry.write_text(json.dumps(value), encoding='utf8')
            refresh_model_patches(preset, registry)
            after = yaml.load(preset.read_text(encoding='utf8'), Loader=Loader)
            self.assertEqual(after[0], before[0])
            self.assertEqual(after[2], before[2])
            self.assertEqual(after[1]['config']['providers']['colleague'],
                             before[1]['config']['providers']['colleague'])
            self.assertEqual(after[-1]['config']['model'], 'second-model')
            self.assertEqual(len(after), 4)
            value['model_roles'].pop('dsh')
            registry.write_text(json.dumps(value), encoding='utf8')
            refresh_model_patches(preset, registry)
            cleared = yaml.load(preset.read_text(encoding='utf8'), Loader=Loader)
            self.assertEqual(cleared[0], before[0])
            self.assertEqual(cleared[1]['config']['providers'],
                             before[1]['config']['providers'])
            self.assertFalse(any(row.get('id') == 'agent-default-model' for row in cleared))

    def test_placeholder_model_does_not_override_default_dsh_selection(self):
        self.assertEqual(model_patches(ROOT / 'config/benchforge.example.json'), [])

    def test_isaac_sync_does_not_require_a_ports_file(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            spatialforge_app._init_configs(3857, 55432)
            with patch.object(spatialforge_app, 'GENERATED', config):
                spatialforge_app.sync_ports()
            worker = json.loads((config / 'worker.local.json').read_text(encoding='utf8'))
            registry = json.loads((config / 'benchforge.local.json').read_text(encoding='utf8'))
            self.assertEqual(worker['isaac_grpc'], registry['isaac']['grpc'])
            self.assertNotIn('isaac_resident', worker)


if __name__ == '__main__':
    unittest.main()
