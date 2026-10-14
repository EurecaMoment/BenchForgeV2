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
            {"id": "legacy", "config": {"id": "benchforge", "plugins": []}},
            {"id": "published", "config": {"id": "benchforgev2", "plugins": []}},
            {"id": "development", "config": {"id": hot.PRESET_ID, "plugins": [
                {"id": "spatial-learning-tools", "name": "/old/tools.mjs", "config": {"python": "/old/python"}},
                {"id": "spatialforge-tools", "name": "/old/spatialforge.mjs", "config": {"serviceConfig": "/old/config"}},
                {"id": "persistent-shell", "config": [{"id": "persistent-bash", "name": "/old/shell.mjs"}]},
                {"id": "persona", "config": {"prefix": "old", "suffix": "keep"}},
            ]}},
        ]}]
        original = deepcopy(profile)
        result = hot.update_profile(profile, ROOT, ROOT / ".deployment/python-development",
                                    ROOT / ".deployment/model-services.json", ROOT / ".deployment/spatialforge.local.json", "123")
        self.assertEqual(profile, original)
        self.assertEqual(result[0]["insert"][:3], original[0]["insert"][:3])
        plugins = result[0]["insert"][3]["config"]["plugins"]
        learning = plugins[0]
        self.assertIn("model_lama", learning["config"]["includeTools"])
        self.assertIn("pipeline_run", learning["config"]["includeTools"])
        self.assertEqual(learning["name"], str(ROOT / "integrations/dsh/tools.mjs") + "?spatialforge_revision=123")
        self.assertIn(str(ROOT), plugins[1]["config"]["serviceConfig"])
        self.assertTrue(plugins[2]["config"][0]["name"].endswith("?spatialforge_revision=123"))
        self.assertEqual(plugins[3]["config"]["suffix"], "keep")


if __name__ == "__main__":
    unittest.main()
