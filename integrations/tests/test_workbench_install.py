"""Root UI installation must preserve session presets and official DSH plugins."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workbench_install", ROOT / "integrations/spatialforge/install_workbench.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class WorkbenchInstall(unittest.TestCase):
    def test_ui_plugin_is_installed_only_in_spatialforge_preset_and_is_idempotent(self):
        profile = [{"insert": [
            {"id": "official", "name": "@deepseek-ai/dsh-client-ui-sidebar"},
            {"id": "benchforge-workbench-ui", "name": "/old/global/workbench/index.js"},
            {"id": "spatialforge", "config": {"id": "spatialforge-standard-ptc", "plugins": [{"id": "existing"}]}},
        ]}]
        original = deepcopy(profile)
        result = install.update_profile(profile, ROOT, [ROOT / "task-workspace"])
        self.assertEqual(profile, original)
        self.assertEqual(result[0]["insert"][0], original[0]["insert"][0])
        self.assertEqual(result[0]["insert"][0]["name"], "@deepseek-ai/dsh-client-ui-sidebar")
        self.assertEqual([row["id"] for row in result[0]["insert"]], ["official", "spatialforge"])
        spatial_plugins = result[0]["insert"][1]["config"]["plugins"]
        self.assertEqual(spatial_plugins[0]["id"], "existing")
        self.assertEqual(spatial_plugins[-1]["id"], "spatialforge-evaluation-ui")
        self.assertEqual(install.update_profile(result, ROOT, [ROOT / "task-workspace"]), result)
        spatial_plugins[-1]["config"]["maxRuns"] = 20
        refreshed = install.update_profile(result, ROOT, None, "next")
        updated = refreshed[0]["insert"][1]["config"]["plugins"][-1]
        self.assertEqual(updated["config"], spatial_plugins[-1]["config"])
        self.assertTrue(updated["name"].endswith("?workbench_revision=next"))

    def test_refuses_profile_without_exactly_one_spatialforge_preset(self):
        with self.assertRaises(ValueError):
            install.update_profile([{"insert": [{"id": "ordinary"}]}], ROOT, None)

    def test_reads_current_and_older_global_assignment_forms(self):
        self.assertEqual(install.graph_from_html('<script>globalThis["__DSH_BOOT__"] = {"entries":[]};</script>'), {"entries": []})
        self.assertEqual(install.graph_from_html('<script>window.__DSH_BOOT__={"entries":[]}</script>'), {"entries": []})
        with self.assertRaises(RuntimeError):
            install.graph_from_html("<html>Authentication required</html>")


if __name__ == "__main__":
    unittest.main()

