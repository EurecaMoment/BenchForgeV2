"""Regressions for front-axis mistakes observed in captured office scenes."""

import unittest

from src.dsh.task_support.native_asset_facing import world_forward, yaw_toward


class NativeAssetFacingTests(unittest.TestCase):
    def test_study_desk_pair_and_reading_armchair(self):
        monitor_xy = (-1.4, 1.86)
        chair_xy = (-1.15, 0.82)
        self.assertAlmostEqual(
            yaw_toward("office_monitor", monitor_xy, chair_xy), -76.5, places=1
        )
        self.assertAlmostEqual(
            yaw_toward("office_chair", chair_xy, monitor_xy), 103.5, places=1
        )
        self.assertAlmostEqual(
            yaw_toward("office_armchair", (-1.3, -1.55), (-1.3, 0.0)), 90.0
        )
        fx, fy = world_forward("office_armchair", 90)
        self.assertAlmostEqual(fx, 0.0)
        self.assertAlmostEqual(fy, 1.0)
        # The captured 180-degree pose faces west, despite the visual-review pass.
        for kind in ("office_monitor", "office_armchair", "office_chair"):
            with self.subTest(kind=kind):
                fx, fy = world_forward(kind, 180)
                self.assertAlmostEqual(fx, -1.0)
                self.assertAlmostEqual(fy, 0.0)

    def test_lounge_armchairs_face_inward_from_west_and_east(self):
        west_yaw = yaw_toward("office_armchair", (-1.42, 0.85), (0.0, 0.85))
        east_yaw = yaw_toward("office_armchair", (1.42, 0.55), (0.0, 0.55))
        self.assertAlmostEqual(west_yaw, 0.0)
        self.assertAlmostEqual(east_yaw, 180.0)
        for yaw, expected_x in ((west_yaw, 1.0), (east_yaw, -1.0)):
            fx, fy = world_forward("office_armchair", yaw)
            self.assertAlmostEqual(fx, expected_x)
            self.assertAlmostEqual(fy, 0.0)

    def test_unknown_kinds_do_not_inherit_a_front_axis(self):
        for kind in ("unregistered_asset",):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "Unknown or unverified"):
                    yaw_toward(kind, (0, 0), (1, 0))
                with self.assertRaisesRegex(ValueError, "Unknown or unverified"):
                    world_forward(kind, 0)

    def test_lounge_north_wall_sofa_faces_south_into_room(self):
        yaw = yaw_toward("office_sofa", (0.0, 1.94), (0.0, 0.0))
        self.assertAlmostEqual(yaw, -90.0)
        fx, fy = world_forward("office_sofa", yaw)
        self.assertAlmostEqual(fx, 0.0)
        self.assertAlmostEqual(fy, -1.0)
        # The captured yaw=90 points north toward the wall.
        fx, fy = world_forward("office_sofa", 90)
        self.assertAlmostEqual(fx, 0.0)
        self.assertAlmostEqual(fy, 1.0)

    def test_coincident_points_and_nonfinite_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "distinct points"):
            yaw_toward("office_monitor", (-1.4, 1.86), (-1.4, 1.86))
        with self.assertRaisesRegex(ValueError, "finite coordinates"):
            yaw_toward("office_chair", (0, 0), (float("nan"), 1))
        with self.assertRaisesRegex(ValueError, "yaw_deg must be finite"):
            world_forward("office_armchair", float("inf"))


if __name__ == "__main__":
    unittest.main()
