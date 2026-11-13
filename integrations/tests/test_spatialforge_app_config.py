import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import spatialforge_app
from benchforge_core.service_config import load_service_client_config
from integrations.tests.test_install_config import local_configuration
from spatialforge.runtime_config import load_service_config, load_worker_config


class SpatialForgeAppConfig(unittest.TestCase):
    def test_client_and_standalone_worker_receive_their_own_credentials(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            spatialforge_app._init_configs(3941, 55432)
            generated = config / 'generated'
            server_path = spatialforge_app.SERVER
            worker_path = generated / 'worker.local.json'
            client_path = generated / 'spatialforge.local.json'
            server = json.loads(server_path.read_text(encoding='utf-8'))
            worker = json.loads(worker_path.read_text(encoding='utf-8'))
            client = json.loads(client_path.read_text(encoding='utf-8'))
            canonical = (config / 'benchforge.local.json').read_text(encoding='utf-8')
            self.assertEqual(client, {'service_config': server_path.name})
            self.assertEqual(server['models_config'], '../benchforge.local.json')
            self.assertEqual((generated / server['models_config']).resolve(),
                             config / 'benchforge.local.json')
            self.assertNotIn('service_config', worker)
            self.assertNotIn('operator_token', worker)
            self.assertNotIn('database_url', worker)
            for name in ('operator_token', 'worker_token'):
                self.assertNotIn(server[name], canonical)
            with patch.dict(os.environ, spatialforge_app.build_environment(), clear=True):
                loaded_server = load_service_config(server_path)
                loaded_client = load_service_client_config(client_path)
                loaded_worker = load_worker_config(worker_path)
            self.assertEqual(loaded_client['operator_token'], loaded_server['operator_token'])
            self.assertEqual(loaded_worker['worker_token'], loaded_server['worker_token'])
            self.assertEqual(loaded_worker['url'], 'http://127.0.0.1:3941')
            self.assertEqual(loaded_worker['ssh_forward'], '3941:127.0.0.1:3941')

    def test_one_edit_updates_port_model_and_worker_projections(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            spatialforge_app._init_configs()
            path = config / 'benchforge.local.json'
            canonical = json.loads(path.read_text(encoding='utf-8'))
            canonical['server']['port'] = 3992
            canonical['web']['port'] = 3993
            canonical['database'].update(port=55539, project='edited-project')
            canonical['worker'].update(worker_id='edited-worker', runs='../capture runs',
                                       ssh_config='../worker ssh.conf')
            canonical['isaac']['grpc'].update(host='example.net', port=4996)
            canonical['isaac']['capture_timeout_seconds'] = 657
            before = json.loads(spatialforge_app.SERVER.read_text(encoding='utf-8'))
            spatialforge_app.write(path, canonical)
            (config / 'ports.env').write_text('SPATIALFORGE_PORT=3883\n', encoding='utf-8')
            spatialforge_app.sync_configuration()
            server = json.loads(spatialforge_app.SERVER.read_text(encoding='utf-8'))
            generated = config / 'generated'
            worker = json.loads((generated / 'worker.local.json').read_text(encoding='utf-8'))
            self.assertEqual(server['port'], 3992)
            self.assertEqual(server['operator_token'], before['operator_token'])
            self.assertEqual(spatialforge_app.configured_web_port(), 3993)
            self.assertEqual(worker['worker_id'], 'edited-worker')
            self.assertEqual(worker['url'], 'http://127.0.0.1:3992')
            self.assertEqual(worker['ssh_forward'], '3992:127.0.0.1:3992')
            self.assertEqual(worker['isaac_grpc'], canonical['isaac']['grpc'])
            self.assertEqual(worker['capture_timeout_seconds'], 657)
            self.assertEqual(worker['runs'], str(config.parent / 'capture runs'))
            self.assertEqual(worker['ssh_config'], str(config.parent / 'worker ssh.conf'))
            self.assertIn('COMPOSE_PROJECT_NAME=edited-project',
                          (generated / 'database.env').read_text(encoding='utf-8'))

    def test_remote_client_does_not_receive_local_backend_credentials(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            path = config / 'benchforge.local.json'
            value = json.loads((config / 'benchforge.example.json').read_text(encoding='utf-8'))
            value['client'] = {'service_url': 'https://bench.example/api',
                               'operator_token_env': 'REMOTE_OP', 'execution_mode': 'exploration'}
            value['database']['url_env'] = 'NEW_DB_URL'
            spatialforge_app.write(path, value)
            spatialforge_app.sync_configuration()
            generated = config / 'generated'
            client_path = generated / 'spatialforge.local.json'
            self.assertEqual(json.loads(client_path.read_text(encoding='utf-8')), value['client'])
            with patch.dict(os.environ, {'REMOTE_OP': 'remote-key'}):
                self.assertEqual(load_service_client_config(client_path)['operator_token'], 'remote-key')
            self.assertFalse(spatialforge_app.database_is_managed())
            self.assertNotIn('POSTGRES_PASSWORD', (generated / 'database.env').read_text(encoding='utf-8'))

    def test_managed_database_projection_controls_service_and_compose(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            spatialforge_app._init_configs()
            path = config / 'benchforge.local.json'
            value = json.loads(path.read_text(encoding='utf-8'))
            value['database']['password_env'] = 'CUSTOM_PASSWORD'
            spatialforge_app.write(path, value)
            password = "literal $password ' # \\" + '"'
            ambient = 'postgresql+psycopg://wrong.example/other'
            with patch.dict(os.environ, {'CUSTOM_PASSWORD': password, 'SPATIALFORGE_DATABASE_URL': ambient}):
                spatialforge_app.sync_configuration()
                environment = spatialforge_app.build_environment()
                configured = environment['SPATIALFORGE_DATABASE_URL']
                self.assertNotEqual(configured, ambient)
                self.assertEqual(unquote(urlsplit(configured).password), password)
                with patch.object(spatialforge_app.subprocess, 'run') as compose:
                    spatialforge_app._database_command(None, False)
                self.assertNotIn('--env-file', compose.call_args.args[0])
                self.assertEqual(compose.call_args.kwargs['env']['POSTGRES_PASSWORD'], password)
                self.assertEqual(compose.call_args.kwargs['env']['SPATIALFORGE_DATABASE_URL'], configured)

    def test_legacy_shell_secrets_are_read_literally_without_execution(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            marker = config / 'unexpected-effect'
            (config / 'dsh.env').write_text(
                f"export LEGACY_KEY='literal # value $(touch {marker})' # assignment\n",
                encoding='utf-8',
            )
            environment = spatialforge_app.build_environment(database=False)
            self.assertEqual(environment['LEGACY_KEY'], f'literal # value $(touch {marker})')
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
