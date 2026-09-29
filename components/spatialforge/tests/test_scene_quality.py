import copy
import unittest

from spatialforge.contracts import scene_contract_capabilities, validate_program
from spatialforge.scene_quality import audit_scene


def scene_v2():
    return {
        "schema": "spatialforge.scene/v2",
        "scene_id": "mixed_room",
        "title": "A mixed room with a generated lamp",
        "objects": [
            {
                "id": "table",
                "label": "table",
                "kind": "box",
                "size": [1.2, 0.7, 0.75],
                "color": [0.4, 0.25, 0.12],
                "xy": [0, 0],
                "support": "ground",
                "base_z": 0,
                "yaw_deg": 0,
                "dynamic": False,
                "mass_kg": 20,
                "parts": [],
                "room_id": "living",
                "zone_id": "work_zone",
                "material_id": "wood",
                "semantic_labels": ["support_surface"],
                "affordances": ["place_on"],
            },
            {
                "id": "lamp",
                "label": "generated floor lamp",
                "kind": "mesh",
                "asset_id": "lamp_asset",
                "size": [0.3, 0.3, 1.5],
                "color": [0.8, 0.7, 0.4],
                "xy": [1.1, 0],
                "support": "ground",
                "base_z": 0,
                "yaw_deg": 0,
                "dynamic": False,
                "mass_kg": 3,
                "parts": [],
                "room_id": "living",
                "zone_id": "rest_zone",
                "material_id": "metal",
                "semantic_labels": ["lighting", "furniture"],
            },
        ],
        "cameras": [
            {"position": [3, -4, 2.2], "target": [0, 0, 0.7]},
            {"position": [-2, -1, 1.8], "target": [0, 0, 0.8]},
        ],
        "assumptions": ["dimensions are synthetic priors"],
        "rooms": [{"id": "living", "name": "Living room", "bounds": {"center": [0, 0, 1.5], "size": [5, 5, 3]}}],
        "zones": [
            {"id": "work_zone", "name": "Work zone", "room_id": "living", "bounds": [1, 1, 0.75], "purpose": "place objects"},
            {"id": "rest_zone", "name": "Rest zone", "room_id": "living", "bounds": [1, 1, 0.75], "purpose": "lighting"},
        ],
        "portals": [{"id": "door", "kind": "door", "position": [-2.4, 0, 1.1], "size": [0.9, 0.2, 2.1], "from_room": "living", "passable": True}],
        "assets": [
            {"id": "lamp_asset", "kind": "generated", "uri": "runtime/generated_assets/lamp", "provenance": {"generator": "diffusion+sam3d", "measured": False}},
        ],
        "materials": [
            {"id": "wood", "name": "wood", "base_color": [0.4, 0.25, 0.12], "roughness": 0.65, "metallic": 0},
            {"id": "metal", "name": "metal", "base_color": [0.7, 0.7, 0.7], "roughness": 0.35, "metallic": 0.8},
        ],
        "lights": [{"id": "window", "kind": "area", "position": [0, -2, 2.5], "color": [1, 0.95, 0.9], "intensity": 500}],
        "render_environment": {"renderer": "PathTracing", "samples_per_pixel": 64, "exposure": 0},
        "navigation": {"agents": [{"id": "human", "radius": 0.3}], "waypoints": [{"id": "p0", "position": [0, 0, 0]}], "edges": [], "clearance_m": 0.6},
        "affordances": [{"id": "put_lamp", "action": "place_on", "object_id": "lamp", "target_id": "table"}],
        "semantic_layers": [{"id": "native", "name": "simulator labels", "labels": ["table", "lamp"], "authority": "simulator"}],
        "scene_graph": {"nodes": [{"id": "living", "type": "room"}], "edges": [{"source": "table", "target": "living", "relation": "inside"}]},
        "provenance": {"sources": [{"kind": "generated", "id": "lamp_asset"}], "generator": "spatialforge"},
    }


class SceneQuality(unittest.TestCase):
    def test_v2_contract_accepts_free_form_asset_and_scene_metadata(self):
        validate_program(scene_v2())
        capabilities = scene_contract_capabilities()
        self.assertIn("rooms", capabilities["extensions"])
        self.assertIn("diffusion", capabilities["asset_sources"])


    def test_v2_rejects_bad_room_reference_without_restricting_scene_style(self):
        proposal = scene_v2()
        proposal["zones"][0]["room_id"] = "missing_room"
        with self.assertRaisesRegex(ValueError, "zone room"):
            validate_program(proposal)


    def test_quality_audit_keeps_missing_evidence_as_capability_gap(self):
        report = audit_scene(scene_v2(), capture={}, intent={"required_views": 3})
        self.assertEqual(report["tier"], "exploration_candidate")
        self.assertFalse(report["gt_written"])
        self.assertEqual(report["gt_authority"], "native_simulator_or_official_source_only")
        self.assertTrue(any("simulator" in gap.lower() for gap in report["capability_gaps"]))
        self.assertEqual(report["dimensions"]["interaction"]["evidence_level"], "declared")
        self.assertNotIn("score", report["dimensions"]["physics"])


    def test_quality_audit_credits_measured_receipts(self):
        capture = {
            "renderable": True,
            "views": ["view_0.png", "view_1.png", "view_2.png"],
            "depth": True,
            "segmentation": {"authority": "simulator", "instances": [{"id": 1, "label": "table"}]},
            "geometry": {"valid": True},
            "physics": {"stable": True, "steps": 120, "contact_pairs": []},
            "interaction": {"validated": True, "action_results": [{"action": "place_lamp", "success": True}]},
            "semantic_labels": True,
            "lighting": "validated",
        }
        report = audit_scene(scene_v2(), capture=capture, intent={"required_views": 3})
        self.assertEqual(report["tier"], "publishable_candidate")
        self.assertTrue(all(report["dimensions"][key]["evidence_level"] in {"measured", "observed"} for key in ("geometry", "render", "physics", "interaction", "semantic", "coverage")))


    def test_quality_does_not_mutate_scene(self):
        proposal = scene_v2()
        before = copy.deepcopy(proposal)
        audit_scene(proposal, capture={})
        self.assertEqual(proposal, before)

    def test_stable_rollout_is_not_physical_realism_evidence(self):
        report = audit_scene(scene_v2(), capture={"physics": {"stable": True, "steps": 60}})
        physics = report["dimensions"]["physics"]
        self.assertEqual(physics["evidence_level"], "observed")
        self.assertEqual(physics["truth_scope"], "rollout_stability_only")
        self.assertTrue(any("does not establish" in gap for gap in physics["capability_gaps"]))

    def test_v2_allows_building_scale_and_requires_valid_render_settings(self):
        proposal = scene_v2()
        proposal["objects"][0].update(size=[40, 25, 6], xy=[120, -80], mass_kg=5000)
        proposal["cameras"][0] = {"position": [140, -110, 35], "target": [120, -80, 2]}
        validate_program(proposal)
        proposal["render_environment"]["samples_per_pixel"] = 8
        with self.assertRaisesRegex(ValueError, "samples_per_pixel"):
            validate_program(proposal)

    def test_room_bounds_do_not_imply_walls(self):
        proposal = scene_v2()
        proposal["rooms"][0].update(representation="explicit_objects", geometry={"object_ids": ["missing_wall"]})
        with self.assertRaisesRegex(ValueError, "room geometry object"):
            validate_program(proposal)


if __name__ == "__main__":
    unittest.main()
