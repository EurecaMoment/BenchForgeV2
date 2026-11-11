import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'components' / 'spatialforge' / 'src'))

import spatialforge_app
from benchforge_core.service_config import load_service_client_config
from spatialforge.runtime_config import load_service_config, load_worker_config


class SpatialForgeAppConfig(unittest.TestCase):
    def test_init_creates_one_server_config_referenced_by_dsh_and_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            config_dir = root / 'config'
            state_dir = root / '.deployment'
            config_dir.mkdir()
            with (patch.object(spatialforge_app, 'ROOT', root),
                  patch.object(spatialforge_app, 'CONFIG', config_dir),
                  patch.object(spatialforge_app, 'STATE', state_dir),
                  patch.object(spatialforge_app, 'SERVER', config_dir / 'spatialforge-server.local.json'),
                  patch.object(spatialforge_app, 'SERVER_TEMPLATE', root / 'config' / 'spatialforge-server.example.json'),
                  patch.object(spatialforge_app, 'MODELS_TEMPLATE', root / 'config' / 'models.example.json'),
                  patch.object(spatialforge_app, 'WORKER_TEMPLATE', root / 'config' / 'worker.example.json'),
                  patch.dict(os.environ, {'ISAAC_SIM_ROOT': str(root / 'isaac'),
                                          'ISAAC_ASSET_ROOT': str(root / 'assets')}, clear=True)):
                for name in ('spatialforge-server.example.json', 'models.example.json', 'worker.example.json', 'spatialforge.example.json'):
                    source = Path(__file__).resolve().parents[2] / 'config' / name
                    (config_dir / name).write_bytes(source.read_bytes())
                spatialforge_app._init_configs(3941, 55432)
                server_path = config_dir / 'spatialforge-server.local.json'
                worker_path = config_dir / 'worker.local.json'
                client_path = config_dir / 'spatialforge.local.json'
                server = json.loads(server_path.read_text(encoding='utf-8'))
                worker = json.loads(worker_path.read_text(encoding='utf-8'))
                client = json.loads(client_path.read_text(encoding='utf-8'))
                self.assertEqual(set(client), {'service_config'})
                self.assertEqual(client['service_config'], server_path.name)
                self.assertEqual(worker['service_config'], server_path.name)
                self.assertNotIn('worker_token', worker)
                environment = dict(line.split('=', 1) for line in (config_dir / 'database.env').read_text().splitlines())
                with patch.dict(os.environ, environment, clear=True):
                    loaded_server = load_service_config(server_path)
                    loaded_client = load_service_client_config(client_path)
                    loaded_worker = load_worker_config(worker_path)
                self.assertEqual(loaded_client['operator_token'], loaded_server['operator_token'])
                self.assertEqual(loaded_worker['worker_token'], loaded_server['worker_token'])
                self.assertEqual(loaded_worker['url'], 'http://127.0.0.1:3941')
                self.assertEqual(loaded_worker['ssh_forward'], '3941:127.0.0.1:3941')


if __name__ == '__main__':
    unittest.main()
