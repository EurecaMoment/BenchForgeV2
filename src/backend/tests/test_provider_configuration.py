import json
import os
from pathlib import Path
from threading import Event
import tempfile
import unittest
from unittest.mock import patch

import deployment_config
from benchforge_backend.generation import GenerationTools
from benchforge_backend.provider_config import isaac_endpoint
from benchforge_backend.runtime_config import load_service_config
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
        with self.assertRaisesRegex(ValueError, r'providers.FastFLUX2Klein.url'):
            tools.execute('diffusion', {}, self.state / 'work', Event())

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
