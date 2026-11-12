"""Consolidation changes custom presets while preserving official modes and history."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
import io
import json
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("hot_update", ROOT / "integrations/spatialforge/hot_update.py")
hot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hot)


class HotUpdate(unittest.TestCase):
    def test_hot_update_rolls_back_if_the_old_workbench_reader_remains_loaded(self):
        with tempfile.TemporaryDirectory(prefix='benchforge-hot-update-') as directory:
            root = Path(directory)
            profile = root / 'profile.yml'
            original = b'- insert: []\n'
            profile.write_bytes(original)
            runtime_file = root / 'runtime'
            runtime_file.write_text('{}', encoding='utf-8')
            rpc = mock.Mock()
            rpc.call.side_effect = lambda method, params: (
                {'presets': [{'id': key, 'name': value['name']} for key, value in hot.development.base.PRESETS.items()]}
                if method == 'agentPresets/list' else {'description': 'runtime revision 123'})
            rpc.opener.open.return_value = io.StringIO(json.dumps({'ui_revision': 'old-reader'}))
            arguments = ['hot_update.py', '--profile', str(profile), '--python', str(runtime_file),
                         '--mode-config', str(runtime_file), '--service-config', str(runtime_file)]
            with mock.patch('sys.argv', arguments), mock.patch.object(hot, 'ROOT', root), \
                    mock.patch.object(hot, 'service_state', return_value={'ActiveState': 'active', 'MainPID': '1'}), \
                    mock.patch.object(hot, 'DshRpc', return_value=rpc), \
                    mock.patch.object(hot.development.base, 'load_sources', return_value={}), \
                    mock.patch.object(hot, 'update_profile', return_value=[{'insert': [{'id': 'new-row'}]}]), \
                    mock.patch.object(hot.time, 'time_ns', return_value=123), \
                    mock.patch.object(hot.time, 'monotonic', side_effect=[0, 100]):
                with self.assertRaises(TimeoutError):
                    hot.main()
            self.assertEqual(profile.read_bytes(), original)
            self.assertEqual((root / '.deployment/spatialforge-before-hot-update.yml').read_bytes(), original)

    def test_preserves_other_modes_and_resolves_all_custom_entries_inside_repository(self):
        profile = [{"insert": [
            {"id": "official", "config": {"id": "standard", "plugins": [{"id": "official-tools", "name": "official"}]}},
            {"id": "benchforge-workbench-ui", "name": "/old/global/workbench", "config": {
                "workspacePaths": ["/retained/workspace"], "productionConfig": "/retained/service.json",
                "productionPython": "/retained/python"}},
            {"id": "legacy", "config": {"id": "benchforge", "plugins": []}},
            {"id": "published", "config": {"id": "benchforgev2", "plugins": []}},
            {"id": "development", "config": {"id": hot.PRESET_ID, "plugins": [
                {"id": "spatial-learning-tools", "name": "/old/tools.mjs", "config": {"python": "/old/python"}},
                {"id": "spatialforge-tools", "name": "/old/spatialforge.mjs", "config": {"serviceConfig": "/old/config"}},
                {"id": "spatialforge-evaluation-ui", "name": "/old/ui/index.js", "config": {"workspacePaths": ["/preset/workspace"]}},
                {"id": "persistent-shell", "config": [{"id": "persistent-bash", "name": "/old/shell.mjs"}]},
                {"id": "persona", "config": {"prefix": "old", "suffix": "keep"}},
            ]}},
        ]}]
        original = deepcopy(profile)
        result = hot.update_profile(profile, ROOT, ROOT / ".deployment/python-development",
                                    ROOT / "config/benchforge.local.json", ROOT / "config/generated/spatialforge.local.json", "123")
        self.assertEqual(profile, original)
        self.assertEqual([row["id"] for row in result[0]["insert"]], [row["id"] for row in original[0]["insert"]])
        self.assertEqual(result[0]["insert"][0], original[0]["insert"][0])
        presets = {row['config']['id']: row['config'] for row in result[0]['insert']
                   if isinstance(row.get('config'), dict) and 'plugins' in row['config']}
        self.assertEqual([presets[key]['name'] for key in ('benchforge', 'benchforgev2', hot.PRESET_ID)],
                         ['BenchForge', 'BenchForgeV2', 'BenchForgeV2_UI'])
        ui = next(row for row in result[0]["insert"] if row["id"] == "benchforge-workbench-ui")
        self.assertEqual(ui["name"], str(ROOT / "integrations/spatialforge/ui/stage_products.js"))
        self.assertEqual(ui["config"], {**original[0]["insert"][1]["config"],
                                      "workspacePaths": ["/preset/workspace", "/retained/workspace"],
                                      "uiRevision": "123"})
        plugins = next(row for row in result[0]["insert"] if row.get("config", {}).get("id") == hot.PRESET_ID)["config"]["plugins"]
        learning = next(row for row in plugins if row['id'] == 'spatial-learning-tools')
        self.assertIn("model_lama", learning["config"]["includeTools"])
        self.assertIn("model_diffusion", learning["config"]["includeTools"])
        self.assertIn("model_depth_anything", learning["config"]["includeTools"])
        self.assertIn("model_sam3d", learning["config"]["includeTools"])
        self.assertIn("model_blender", learning["config"]["includeTools"])
        self.assertIn("pipeline_run", learning["config"]["includeTools"])
        self.assertEqual(learning["name"], str(ROOT / "integrations/dsh/tools.mjs"))
        self.assertIn(str(ROOT), next(row for row in plugins if row["id"] == "spatialforge-tools")["config"]["serviceConfig"])
        self.assertEqual(next(row for row in plugins if row["id"] == "spatialforge-tools")["name"],
                         str(ROOT / "integrations/spatialforge/plugin/tools.mjs"))
        self.assertNotIn("spatialforge-evaluation-ui", [row["id"] for row in plugins])
        persistent = next(row for row in plugins if row["id"] == "persistent-shell")["config"]
        self.assertEqual(next(row for row in persistent if row['id'] == 'persistent-bash')['name'],
                         str(ROOT / "integrations/dsh/persistent-shell.mjs"))
        self.assertEqual(next(row for row in plugins if row["id"] == "persona")["config"]["suffix"], "keep")
        ordinary_plugins = result[0]["insert"][0]["config"]["plugins"]
        self.assertNotIn("spatialforge-evaluation-ui", [row["id"] for row in ordinary_plugins])
        self.assertEqual(hot.update_profile(result, ROOT, ROOT / '.deployment/python-development',
                                           ROOT / 'config/benchforge.local.json',
                                           ROOT / 'config/generated/spatialforge.local.json', '123'), result)
        new_setup = deepcopy(profile)
        new_setup[0]["insert"] = [row for row in new_setup[0]["insert"] if row["id"] != "benchforge-workbench-ui"]
        migrated = hot.update_profile(new_setup, ROOT, Path("/runtime/python"), Path("/runtime/models.json"),
                                      Path("/runtime/service.json"), "456")
        roots = [row for patch in migrated for row in patch.get('insert', []) if row["id"] == "benchforge-workbench-ui"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["name"], str(ROOT / "integrations/spatialforge/ui/stage_products.js"))
        self.assertEqual(roots[0]["config"], {"workspacePaths": ["/preset/workspace"], "uiRevision": "456",
                                               "productionConfig": str(Path("/runtime/service.json").resolve()),
                                               "productionPython": str(Path("/runtime/python"))})
        migrated_plugins = next(row for row in migrated[0]["insert"] if row.get("config", {}).get("id") == hot.PRESET_ID)["config"]["plugins"]
        self.assertNotIn("spatialforge-evaluation-ui", [row["id"] for row in migrated_plugins])

        with mock.patch("sys.argv", ["hot_update.py", "--pull"]), \
                mock.patch.object(hot.subprocess, "check_output", return_value="featurexx\n"), \
                mock.patch.object(hot.subprocess, "run") as pull, \
                mock.patch.object(hot.Path, "is_file", return_value=False):
            with self.assertRaises(FileNotFoundError):
                hot.main()
        pull.assert_called_once_with(["git", "pull", "--ff-only", "origin", "featurexx"], cwd=hot.ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
