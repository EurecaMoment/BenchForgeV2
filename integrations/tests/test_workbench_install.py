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
    def test_root_plugin_is_idempotent_and_does_not_rewrite_modes(self):
        profile = [{"insert": [
            {"id": "official", "name": "@deepseek-ai/dsh-client-ui-sidebar"},
            {"id": "spatialforge", "config": {"id": "spatialforge-standard-ptc", "plugins": [{"id": "existing"}]}},
        ]}]
        original = deepcopy(profile)
        result = install.update_profile(profile, ROOT, [ROOT / "task-workspace"])
        self.assertEqual(profile, original)
        self.assertEqual(result[0], original[0])
        self.assertEqual(result[-1]["insert"][0]["id"], "benchforge-workbench-ui")
        self.assertEqual(install.update_profile(result, ROOT, [ROOT / "task-workspace"]), result)
        result[-1]["insert"][0]["config"]["maxRuns"] = 20
        refreshed = install.update_profile(result, ROOT, None, "next")
        self.assertEqual(refreshed[-1]["insert"][0]["config"], result[-1]["insert"][0]["config"])
        self.assertTrue(refreshed[-1]["insert"][0]["name"].endswith("?workbench_revision=next"))

    def test_reads_current_and_older_global_assignment_forms(self):
        self.assertEqual(install.graph_from_html('<script>globalThis["__DSH_BOOT__"] = {"entries":[]};</script>'), {"entries": []})
        self.assertEqual(install.graph_from_html('<script>window.__DSH_BOOT__={"entries":[]}</script>'), {"entries": []})
        with self.assertRaises(RuntimeError):
            install.graph_from_html("<html>Authentication required</html>")


if __name__ == "__main__":
    unittest.main()

