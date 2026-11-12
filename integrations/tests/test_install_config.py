"""Regression checks for missing and relocated standalone client configuration."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

import benchforge
import spatialforge_app
from benchforge_core.service_config import load_service_client_config
from integrations.dsh import build_presets
from integrations.spatialforge import build_development_preset, build_preset, check_config


ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def local_configuration(root):
    config = root / 'config'
    config.mkdir()
    for name in ('spatialforge-server', 'spatialforge', 'benchforge', 'worker'):
        filename = name + '.example.json'
        shutil.copyfile(ROOT / 'config' / filename, config / filename)
    # Python 3.10 on Windows needs SystemRoot even before importing any code.
    # Isolate application settings while preserving the operating environment.
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(('SPATIALFORGE_', 'ISAAC_'))}
    with (patch.multiple(spatialforge_app, ROOT=root, CONFIG=config, STATE=root / '.deployment',
                         GENERATED=config / 'generated', PORTS=config / 'ports.env',
                         SERVER=config / 'spatialforge-server.local.json',
                         SERVER_TEMPLATE=config / 'spatialforge-server.example.json',
                         WORKER_TEMPLATE=config / 'worker.example.json'),
          patch.dict(os.environ, environment, clear=True)):
        yield config


class InstallConfigTest(unittest.TestCase):
    def test_repeated_init_restores_client_using_existing_server_port_and_token(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config_dir:
            server = config_dir / 'spatialforge-server.local.json'
            original = json.dumps({'port': 3857, 'operator_token': 'existing-private-token',
                                   'database_url': 'existing-database'})
            server.write_text(original, encoding='utf-8')
            with (patch.object(sys, 'argv', ['spatialforge_app.py', 'init', '--port', '3841']),
                  contextlib.redirect_stdout(io.StringIO())):
                spatialforge_app.main()
                client = config_dir / 'spatialforge.local.json'
                self.assertEqual(json.loads(client.read_text(encoding='utf-8')), {'service_config': server.name})
                loaded = load_service_client_config(client)
                self.assertEqual(loaded['service_url'], 'http://127.0.0.1:3857')
                self.assertEqual(loaded['operator_token'], 'existing-private-token')
                retained = '{"service_url":"https://configured.example","operator_token_env":"LOCAL_KEY"}'
                client.write_text(retained, encoding='utf-8')
                spatialforge_app.main()
            self.assertEqual(json.loads(server.read_text(encoding='utf-8')),
                             {**json.loads(original), 'models_config': 'benchforge.local.json'})
            self.assertEqual(client.read_text(encoding='utf-8'), retained)
            self.assertFalse((config_dir / 'database.env').exists())

    def test_fresh_init_creates_matching_client_on_nondefault_port(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config_dir:
            server = config_dir / 'spatialforge-server.local.json'
            with (patch.object(sys, 'argv', ['spatialforge_app.py', 'init', '--port', '3857', '--db-port', '55547',
                                           '--project', 'benchforge-install-test']),
                  contextlib.redirect_stdout(io.StringIO())):
                spatialforge_app.main()
            saved = json.loads(server.read_text(encoding='utf-8'))
            client = load_service_client_config(config_dir / 'spatialforge.local.json')
            self.assertEqual(client['service_url'], 'http://127.0.0.1:3857')
            self.assertEqual(client['operator_token'], saved['operator_token'])
            self.assertNotIn('database_url', saved)
            database_env = (config_dir / 'database.env').read_text(encoding='utf-8')
            self.assertIn(':55547/spatialforge', database_env)
            self.assertIn('COMPOSE_PROJECT_NAME=benchforge-install-test\n', database_env)
            with contextlib.redirect_stdout(io.StringIO()):
                spatialforge_app._init_configs(3841, 55432, 'different-project')
            self.assertEqual(json.loads(server.read_text(encoding='utf-8')), saved)
            self.assertEqual((config_dir / 'database.env').read_text(encoding='utf-8'), database_env)

    def test_init_works_without_installed_backend_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            shutil.copyfile(ROOT / 'spatialforge_app.py', root / 'spatialforge_app.py')
            package = root / 'components/spatialforge/src/spatialforge'
            package.mkdir(parents=True)
            for name in ('__init__.py', 'runtime_config.py', 'model_configuration.py'):
                shutil.copyfile(ROOT / 'components/spatialforge/src/spatialforge' / name, package / name)
            with local_configuration(root) as config:
                result = subprocess.run([sys.executable, '-I', '-S', str(root / 'spatialforge_app.py'),
                                         'init', '--port', '3857', '--project', 'isolated-test'],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                client = load_service_client_config(config / 'generated/spatialforge.local.json')
                self.assertEqual(client['service_url'], 'http://127.0.0.1:3857')

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
            for builder in (build_preset, build_development_preset, build_presets):
                with (self.subTest(builder=builder.__name__), patch.object(sys, 'argv', args),
                      patch.object(builder.base, 'load_sources') as load,
                      contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure):
                    builder.main()
                self.assertEqual(failure.exception.code, 2)
                load.assert_not_called()
                self.assertEqual(preset.read_text(encoding='utf-8'), 'keep existing overrides')

    def test_setup_and_start_share_the_three_preset_deployment_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            dsh = root / 'dsh'
            entry = dsh / 'apps/cli/lib/bin.js'
            entry.parent.mkdir(parents=True)
            entry.touch()
            (root / 'third_party').mkdir()
            shutil.copyfile(ROOT / 'third_party/dependencies.json', root / 'third_party/dependencies.json')
            service = root / 'service.json'
            service.write_text('{}', encoding='utf-8')
            python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True)
            python.touch()
            with (patch.object(benchforge, 'ROOT', root), patch.object(benchforge, 'run') as run,
                  patch.object(benchforge.shutil, 'which', return_value='node'),
                  patch.object(benchforge.subprocess, 'check_output', return_value='v24.0.0'),
                  patch.object(sys, 'argv', ['benchforge.py', 'setup', '--dsh-root', str(dsh),
                                           '--spatialforge-config', str(service)]),
                  contextlib.redirect_stdout(io.StringIO())):
                benchforge.main()
                generation = run.call_args_list[-1].args[0]
                self.assertEqual(generation[1], root / 'integrations/dsh/build_presets.py')
                output = generation[generation.index('--output') + 1]
                self.assertEqual(output, root / 'config/generated/benchforge.local.yml')
                run.reset_mock()
                sys.argv = ['benchforge.py', 'start', '--no-open']
                benchforge.main()
                preflight, launch = (call.args[0] for call in run.call_args_list)
                self.assertEqual(preflight[preflight.index('--preset') + 1], output)
                self.assertEqual(launch[launch.index('--patch') + 1], str(output))

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
