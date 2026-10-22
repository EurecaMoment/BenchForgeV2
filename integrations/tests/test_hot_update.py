"""Only the custom SpatialForge preset may change during a hot update."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("hot_update", ROOT / "integrations/spatialforge/hot_update.py")
hot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hot)


class HotUpdate(unittest.TestCase):
    def test_preserves_other_modes_and_resolves_all_custom_entries_inside_repository(self):
        profile = [{"insert": [
            {"id": "official", "config": {"id": "standard", "plugins": [{"id": "official-tools", "name": "official"}]}},
            {"id": "benchforge-workbench-ui", "name": "/old/global/workbench"},
            {"id": "legacy", "config": {"id": "benchforge", "plugins": []}},
            {"id": "published", "config": {"id": "benchforgev2", "plugins": []}},
            {"id": "development", "config": {"id": hot.PRESET_ID, "plugins": [
                {"id": "spatial-learning-tools", "name": "/old/tools.mjs", "config": {"python": "/old/python"}},
                {"id": "spatialforge-tools", "name": "/old/spatialforge.mjs", "config": {"serviceConfig": "/old/config"}},
                {"id": "spatialforge-evaluation-ui", "name": "/old/ui/index.js", "config": {}},
                {"id": "persistent-shell", "config": [{"id": "persistent-bash", "name": "/old/shell.mjs"}]},
                {"id": "persona", "config": {"prefix": "old", "suffix": "keep"}},
            ]}},
        ]}]
        original = deepcopy(profile)
        result = hot.update_profile(profile, ROOT, ROOT / ".deployment/python-development",
                                    ROOT / ".deployment/model-services.json", ROOT / ".deployment/spatialforge.local.json", "123")
        self.assertEqual(profile, original)
        self.assertEqual([row["id"] for row in result[0]["insert"][:3]], ["official", "legacy", "published"])
        self.assertEqual(result[0]["insert"][0], original[0]["insert"][0])
        plugins = next(row for row in result[0]["insert"] if row.get("config", {}).get("id") == hot.PRESET_ID)["config"]["plugins"]
        learning = plugins[0]
        self.assertIn("model_lama", learning["config"]["includeTools"])
        self.assertIn("model_diffusion", learning["config"]["includeTools"])
        self.assertIn("model_depth_anything", learning["config"]["includeTools"])
        self.assertIn("model_sam3d", learning["config"]["includeTools"])
        self.assertIn("model_blender", learning["config"]["includeTools"])
        self.assertIn("pipeline_run", learning["config"]["includeTools"])
        self.assertEqual(learning["name"], str(ROOT / "integrations/dsh/tools.mjs") + "?spatialforge_revision=123")
        self.assertIn(str(ROOT), next(row for row in plugins if row["id"] == "spatialforge-tools")["config"]["serviceConfig"])
        self.assertEqual(next(row for row in plugins if row["id"] == "spatialforge-evaluation-ui")["name"],
                         str(ROOT / "integrations/spatialforge/ui/index.js") + "?spatialforge_revision=123")
        persistent = next(row for row in plugins if row["id"] == "persistent-shell")["config"]
        self.assertTrue(persistent[0]["name"].endswith("?spatialforge_revision=123"))
        self.assertEqual(next(row for row in plugins if row["id"] == "persona")["config"]["suffix"], "keep")
        ordinary_plugins = result[0]["insert"][0]["config"]["plugins"]
        self.assertNotIn("spatialforge-evaluation-ui", [row["id"] for row in ordinary_plugins])
        self.assertNotIn("benchforge-workbench-ui", [row["id"] for row in result[0]["insert"]])


if __name__ == "__main__":
    unittest.main()
