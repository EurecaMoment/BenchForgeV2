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
    shutil.copyfile(ROOT / 'config/benchforge.example.json', config / 'benchforge.example.json')
    # Python 3.10 on Windows needs SystemRoot even before importing any code.
    # Isolate application settings while preserving the operating environment.
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(('SPATIALFORGE_', 'ISAAC_', 'BENCHFORGE_', 'POSTGRES_'))}
    generated = config / 'generated'
    with (patch.multiple(spatialforge_app, ROOT=root, CONFIG=config, STATE=root / '.spatialforge',
                         GENERATED=generated, SERVER=generated / 'spatialforge-server.local.json'),
          patch.dict(os.environ, environment, clear=True)):
        yield config


class InstallConfigTest(unittest.TestCase):
    def test_repeated_init_retains_migrated_identity_and_uses_canonical_client(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            old_server = config / 'spatialforge-server.local.json'
            old = {'port': 3857, 'operator_token': 'existing-private-token',
                   'database_url': 'postgresql+psycopg://postgres.example/external'}
            old_server.write_text(json.dumps(old), encoding='utf-8')
            with (patch.object(sys, 'argv', ['spatialforge_app.py', 'init', '--port', '3841']),
                  contextlib.redirect_stdout(io.StringIO())):
                spatialforge_app.main()
                client = config / 'generated/spatialforge.local.json'
                self.assertEqual(json.loads(client.read_text(encoding='utf-8')),
                                 {'service_config': old_server.name})
                loaded = load_service_client_config(client)
                self.assertEqual(loaded['service_url'], 'http://127.0.0.1:3857')
                self.assertEqual(loaded['operator_token'], old['operator_token'])
                client.write_text('{"service_url":"https://stale.example"}', encoding='utf-8')
                spatialforge_app.main()
            settings = (config / 'benchforge.local.json').read_text(encoding='utf-8')
            self.assertNotIn(old['operator_token'], settings)
            server = json.loads(spatialforge_app.SERVER.read_text(encoding='utf-8'))
            self.assertEqual(server['database_url'], old['database_url'])
            self.assertEqual(load_service_client_config(client), loaded)
            self.assertEqual(json.loads(old_server.read_text(encoding='utf-8')), old)

    def test_fresh_init_creates_matching_client_on_nondefault_ports(self):
        with tempfile.TemporaryDirectory() as folder, local_configuration(Path(folder).resolve()) as config:
            generated = config / 'generated'
            with (patch.object(sys, 'argv', ['spatialforge_app.py', 'init', '--port', '3857', '--db-port', '55547',
                                           '--web-port', '3098', '--project', 'benchforge-install-test']),
                  contextlib.redirect_stdout(io.StringIO())):
                spatialforge_app.main()
            saved = json.loads(spatialforge_app.SERVER.read_text(encoding='utf-8'))
            client = load_service_client_config(generated / 'spatialforge.local.json')
            self.assertEqual(spatialforge_app.configured_web_port(), 3098)
            self.assertEqual(client['service_url'], 'http://127.0.0.1:3857')
            self.assertEqual(client['operator_token'], saved['operator_token'])
            self.assertNotIn('database_url', saved)
            database_env = (generated / 'database.env').read_text(encoding='utf-8')
            self.assertIn(':55547/spatialforge', database_env)
            self.assertIn('COMPOSE_PROJECT_NAME=benchforge-install-test\n', database_env)
            spatialforge_app._init_configs(3841, 55432, 'different-project', web_port=3081)
            self.assertEqual(spatialforge_app.configured_web_port(), 3098)
            self.assertEqual(json.loads(spatialforge_app.SERVER.read_text(encoding='utf-8')), saved)
            self.assertEqual((generated / 'database.env').read_text(encoding='utf-8'), database_env)

    def test_init_works_without_installed_backend_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ('spatialforge_app.py', 'deployment_config.py'):
                shutil.copyfile(ROOT / name, root / name)
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

    def test_setup_and_start_share_the_v2_preset_deployment_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            dsh = root / 'dsh'
            entry = dsh / 'apps/cli/lib/bin.js'
            entry.parent.mkdir(parents=True)
            entry.touch()
            (root / 'third_party').mkdir()
            shutil.copyfile(ROOT / 'third_party/dependencies.json', root / 'third_party/dependencies.json')
            (root / 'config').mkdir()
            shutil.copyfile(ROOT / 'config/benchforge.example.json', root / 'config/benchforge.example.json')
            service = root / 'service.json'
            service.write_text('{}', encoding='utf-8')
            python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True)
            python.touch()
            with (patch.object(benchforge, 'ROOT', root), patch.object(benchforge, 'run') as run,
                  patch.object(benchforge.shutil, 'which', return_value='node'),
                  patch.object(benchforge.subprocess, 'check_output', return_value='v24.0.0'),
                  patch.object(spatialforge_app, 'configured_web_port', return_value=4823),
                  patch.object(spatialforge_app, 'build_environment', return_value={'LOCAL_KEY':'test'}) as env,
                  patch.object(sys, 'argv', ['benchforge.py', 'setup', '--dsh-root', str(dsh),
                                           '--spatialforge-config', str(service)]),
                  contextlib.redirect_stdout(io.StringIO())):
                benchforge.main()
                generation = run.call_args_list[-1].args[0]
                self.assertEqual(generation[1], root / 'integrations/dsh/build_presets.py')
                output = generation[generation.index('--output') + 1]
                self.assertEqual(output, root / 'config/generated/benchforge.local.yml')
                profile = [{'insert': [{'id': 'spatialforge-tools', 'config': {'serviceConfig': str(service)}}]}]
                output.write_text(yaml.safe_dump(profile), encoding='utf-8')
                run.reset_mock()
                sys.argv = ['benchforge.py', 'start', '--no-open']
                benchforge.main()
                preflight, launch = (call.args[0] for call in run.call_args_list)
                self.assertEqual(preflight[preflight.index('--preset') + 1], output)
                self.assertEqual(launch[launch.index('--patch') + 1], str(output))
                self.assertEqual(launch[launch.index('--port') + 1], '4823')
                self.assertEqual(run.call_args_list[0].kwargs['env']['LOCAL_KEY'], 'test')
                env.assert_called_once_with(database=False)

                local_client = root / 'config/generated/spatialforge.local.json'
                profile[0]['insert'][0]['config']['serviceConfig'] = str(local_client)
                output.write_text(yaml.safe_dump(profile), encoding='utf-8')
                run.reset_mock()
                sys.argv = ['benchforge.py', 'start', '--port', '4824', '--no-open']
                benchforge.main()
                sync, _, launch = (call.args[0] for call in run.call_args_list)
                self.assertEqual(sync[1:], [root / 'spatialforge_app.py', 'sync'])
                self.assertEqual(launch[launch.index('--port') + 1], '4824')

                run.reset_mock()
                sys.argv = ['benchforge.py', 'start', '--config-synced', '--check-config']
                benchforge.main()
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0][1], root / 'integrations/spatialforge/check_config.py')

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

    def test_generic_tools_and_disabled_spatialforge_need_no_client(self):
        with tempfile.TemporaryDirectory() as folder:
            preset = Path(folder) / 'preset.yml'
            preset.write_text('- insert:\n  - id: benchforge-tools\n    config:\n'
                              '      description: !!js "ignored expression"\n'
                              '  - id: spatialforge-tools\n    disabled: true\n'
                              '    config:\n      serviceConfig: missing.json\n', encoding='utf-8')
            self.assertEqual(check_config.check_preset(preset), set())


if __name__ == '__main__':
    unittest.main()
