"""Regression contracts for preset consolidation, deployment options and packaging."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

INTEGRATIONS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('profile_migration', INTEGRATIONS / 'dsh/profile_migration.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
catalog = migration.catalog


class ProfileMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = catalog.build(catalog.base.load_sources(), None, 'python3',
                                       Path('config/benchforge.local.json'),
                                       Path('config/spatialforge.local.json'), package_imports=True)

    def test_preserves_official_rows_extra_options_and_session_identity(self):
        official = {'id': 'preset-standard', 'name': '@deepseek-ai/dsh-agent-preset',
                    'config': {'id': 'standard', 'plugins': []}}
        profile = [{'insert': [official,
            {'id': 'legacy-first', 'config': {'id': 'benchforge', 'plugins': [
                {'id': 'benchforge-tools', 'name': '/old/tools.mjs', 'config': {
                    'configPath': '/old/models.json', 'environment': {'KEEP_THIS_OPTION': '1'},
                }},
            ]}},
            {'id': 'legacy-v2', 'config': {'id': 'benchforgev2', 'plugins': [
                {'id': 'benchforge-tools', 'config': {'maxOutputBytes': 12345}},
            ]}},
            {'id': 'legacy-ui', 'config': {'id': 'spatialforge-standard-ptc', 'name': 'SpatialForge', 'plugins': [
                {'id': 'persona', 'config': {'prefix': 'old', 'suffix': 'retained deployment context'}},
                {'id': 'spatialforge-evaluation-ui', 'config': {'workspacePaths': ['/saved/workspace']}},
                {'id': 'custom-model', 'name': 'custom-provider', 'config': {'model': 'retain-this-model'}},
            ]}},
        ]}, {'remove': ['unrelated-old-plugin']}]
        original = deepcopy(profile)
        result = migration.migrate_profile(profile, self.generated, 'revision-1')
        self.assertEqual(profile, original)
        self.assertEqual(result[0]['insert'][0], official)
        self.assertEqual(result[1], original[1])
        rows = migration.inserted_rows(result)
        presets = {migration.preset_id(row): row for row in rows if migration.preset_id(row) in catalog.base.PRESETS}
        self.assertEqual(len(presets), 3)
        self.assertEqual(presets['spatialforge-standard-ptc']['id'], 'legacy-ui')
        self.assertEqual(presets['spatialforge-standard-ptc']['config']['name'], 'BenchForgeV2_UI')
        first = next(p for p in presets['benchforge']['config']['plugins'] if p['id'] == 'benchforge-tools')
        self.assertEqual(first['config']['configPath'], 'config/benchforge.local.json')
        self.assertEqual(first['config']['environment'], {'KEEP_THIS_OPTION': '1'})
        learning = next(p for p in presets['benchforgev2']['config']['plugins'] if p['id'] == 'spatial-learning-tools')
        self.assertEqual(learning['config']['maxOutputBytes'], 12345)
        plugins = presets['spatialforge-standard-ptc']['config']['plugins']
        self.assertEqual(next(p for p in plugins if p['id'] == 'custom-model')['config']['model'], 'retain-this-model')
        self.assertEqual(next(p for p in plugins if p['id'] == 'persona')['config']['suffix'], 'retained deployment context')
        reader = next(row for row in rows if row['id'] == migration.UI_ID)
        self.assertEqual(reader['config']['workspacePaths'], ['/saved/workspace'])
        self.assertEqual(migration.migrate_profile(result, self.generated, 'revision-1'), result)

    def test_duplicate_rows_collapse_without_changing_the_historical_preset_id(self):
        profile = deepcopy(self.generated)
        profile.append({'insert': [deepcopy(self.generated[0]['insert'][2]),
                                   deepcopy(self.generated[0]['insert'][3])]})
        result = migration.migrate_profile(profile, self.generated)
        rows = migration.inserted_rows(result)
        self.assertEqual(len(rows), 4)
        self.assertEqual([migration.preset_id(row) for row in rows[:3]], list(catalog.base.PRESETS))
        self.assertEqual(migration.migrate_profile(result, self.generated), result)

    def test_shipped_bundle_is_the_portable_catalog(self):
        bundle = catalog.yaml.load((INTEGRATIONS / 'cordis.patch.yml').read_text(encoding='utf-8'),
                                   Loader=catalog.base.Loader)
        self.assertEqual(bundle, self.generated)

    def test_installer_preserves_original_profile_in_backup(self):
        with tempfile.TemporaryDirectory(prefix='benchforge-presets-') as directory:
            root = Path(directory)
            profile, generated = root / 'profile.yml', root / 'presets.yml'
            original = '- insert:\n  - id: unrelated\n    name: keep-this-plugin\n'
            profile.write_text(original, encoding='utf-8')
            generated.write_text(catalog.yaml.dump(self.generated, Dumper=catalog.base.Dumper), encoding='utf-8')
            result = subprocess.run([sys.executable, str(INTEGRATIONS / 'dsh/install_preset.py'),
                                     '--profile', str(profile), '--preset', str(generated)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            backups = list(root.glob('profile.yml.before-benchforge-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding='utf-8'), original)
            installed = catalog.yaml.load(profile.read_text(encoding='utf-8'), Loader=catalog.base.Loader)
            self.assertEqual(installed[0]['insert'][0], {'id': 'unrelated', 'name': 'keep-this-plugin'})
            self.assertEqual(len([row for row in migration.inserted_rows(installed)
                                  if migration.preset_id(row) in catalog.base.PRESETS]), 3)


if __name__ == '__main__':
    unittest.main()
