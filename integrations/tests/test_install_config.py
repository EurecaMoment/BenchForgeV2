"""Regression checks for missing and relocated standalone client configuration."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

import benchforge
import spatialforge_app
from integrations.spatialforge import build_preset, check_config


class InstallConfigTest(unittest.TestCase):
    def test_repeated_init_restores_client_using_existing_server_port_and_token(self):
        with tempfile.TemporaryDirectory() as folder:
            config_dir = Path(folder)
            server = config_dir / 'spatialforge-server.local.json'
            original = json.dumps({'port': 3857, 'operator_token': 'existing-private-token',
                                   'database_url': 'existing-database'})
            server.write_text(original, encoding='utf-8')
            with (patch.object(spatialforge_app, 'CONFIG', config_dir),
                  patch.object(spatialforge_app, 'SERVER', server),
                  patch.object(sys, 'argv', ['spatialforge_app.py', 'init', '--port', '3841']),
                  contextlib.redirect_stdout(io.StringIO())):
                spatialforge_app.main()
                client = config_dir / 'spatialforge.local.json'
                self.assertEqual(json.loads(client.read_text(encoding='utf-8')), {
                    'service_url': 'http://127.0.0.1:3857', 'operator_token': 'existing-private-token'})
                retained = '{"service_url":"https://configured.example","operator_token_env":"LOCAL_KEY"}'
                client.write_text(retained, encoding='utf-8')
                spatialforge_app.main()
            self.assertEqual(server.read_text(encoding='utf-8'), original)
            self.assertEqual(client.read_text(encoding='utf-8'), retained)
            self.assertFalse((config_dir / 'database.env').exists())

    def test_fresh_init_creates_matching_client_on_nondefault_port(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_dir = root / 'config'
            config_dir.mkdir()
            for name in ('models.example.json', 'worker.example.json'):
                (config_dir / name).write_text('{}', encoding='utf-8')
            server = config_dir / 'spatialforge-server.local.json'
            with (patch.object(spatialforge_app, 'ROOT', root),
                  patch.object(spatialforge_app, 'CONFIG', config_dir),
                  patch.object(spatialforge_app, 'STATE', root / '.spatialforge'),
                  patch.object(spatialforge_app, 'SERVER', server),
                  patch.object(sys, 'argv', ['spatialforge_app.py', 'init', '--port', '3857', '--db-port', '55547',
                                           '--project', 'benchforge-install-test']),
                  contextlib.redirect_stdout(io.StringIO())):
                spatialforge_app.main()
            saved = json.loads(server.read_text(encoding='utf-8'))
            client = json.loads((config_dir / 'spatialforge.local.json').read_text(encoding='utf-8'))
            self.assertEqual(client['service_url'], 'http://127.0.0.1:3857')
            self.assertEqual(client['operator_token'], saved['operator_token'])
            self.assertIn(':55547/', saved['database_url'])
            database_env = (config_dir / 'database.env').read_text(encoding='utf-8')
            self.assertIn('COMPOSE_PROJECT_NAME=benchforge-install-test\n', database_env)

    def test_setup_rejects_missing_client_before_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            missing = root / 'missing.local.json'
            with (patch.object(benchforge, 'ROOT', root), patch.object(benchforge, 'run') as run,
                  patch.object(sys, 'argv', ['benchforge.py', 'setup', '--spatialforge-config', str(missing)]),
                  contextlib.redirect_stderr(io.StringIO()) as errors,
                  self.assertRaises(SystemExit) as failure):
                benchforge.main()
            self.assertEqual(failure.exception.code, 2)
            self.assertIn(str(missing.resolve()), errors.getvalue())
            run.assert_not_called()
            self.assertFalse((root / '.benchforge').exists())

    def test_direct_builder_rejects_missing_client_without_overwriting_preset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            preset = root / 'existing.yml'
            preset.write_text('keep existing overrides', encoding='utf-8')
            args = ['build_preset.py', '--python', sys.executable, '--config', str(root / 'models.json'),
                    '--service-config', str(root / 'missing.json'), '--output', str(preset)]
            with (patch.object(sys, 'argv', args), patch.object(build_preset.base, 'load_sources') as load,
                  contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure):
                build_preset.main()
            self.assertEqual(failure.exception.code, 2)
            load.assert_not_called()
            self.assertEqual(preset.read_text(encoding='utf-8'), 'keep existing overrides')

    def test_preflight_reads_actual_preset_reference_after_config_move(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            actual = root / 'config/generated/spatialforge.local.json'
            actual.parent.mkdir(parents=True)
            actual.write_text('{"service_url":"http://127.0.0.1:3857"}', encoding='utf-8')
            preset = root / 'preset.yml'
            plugin = {'id': 'spatialforge-tools', 'config': {
                'serviceConfig': str(root / 'config/spatialforge.local.json')}}
            profile = [{'insert': [{'id': 'preset-benchforgev2', 'config': {'plugins': [plugin]}}]}]
            preset.write_text(yaml.safe_dump(profile), encoding='utf-8')
            with self.assertRaisesRegex(FileNotFoundError, 'update serviceConfig'):
                check_config.check_preset(preset)
            plugin['config']['serviceConfig'] = str(actual)
            preset.write_text(yaml.safe_dump(profile), encoding='utf-8')
            self.assertEqual(check_config.check_preset(preset), {actual.resolve()})

    def test_plain_benchforge_and_disabled_spatialforge_need_no_client(self):
        with tempfile.TemporaryDirectory() as folder:
            preset = Path(folder) / 'preset.yml'
            preset.write_text('- insert:\n  - id: benchforge-tools\n    config:\n'
                              '      description: !!js "ignored expression"\n'
                              '  - id: spatialforge-tools\n    disabled: true\n'
                              '    config:\n      serviceConfig: missing.json\n', encoding='utf-8')
            self.assertEqual(check_config.check_preset(preset), set())


if __name__ == '__main__':
    unittest.main()
