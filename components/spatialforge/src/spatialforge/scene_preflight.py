"""Lightweight authoring diagnostics for scene cameras.

The preflight uses only declared room bounds and camera metadata. It does not
infer walls, move cameras, or turn a design reference into ground truth.
These diagnostics are non-blocking: semantic zone bounds do not establish
whether a camera is occluded or outside the physical building.
"""
from __future__ import annotations

from typing import Any


def _inside(point: list[float], center: list[float], size: list[float]) -> bool:
    return all(abs(point[i] - center[i]) <= size[i] / 2 for i in range(3))


def preflight_scene(program: dict[str, Any], *, vertical_tolerance_m: float = 0.05) -> dict[str, Any]:
    rooms = [room for room in program.get("rooms", []) if isinstance(room, dict)]
    records = []
    errors = []
    for index, camera in enumerate(program.get("cameras", [])):
        position = camera.get("position")
        target = camera.get("target")
        record = {"camera_index": index, "camera_id": camera.get("id", index),
                  "position": position, "target": target, "status": "not_applicable"}
        if camera.get("allow_external") or camera.get("role") == "external":
            record.update(status="passed", reason="external_camera_declared")
            records.append(record)
            continue
        containing = []
        for room in rooms:
            bounds = room.get("bounds")
            if isinstance(bounds, dict) and _inside(target, bounds["center"], bounds["size"]):
                containing.append(room)
        if not containing:
            record.update(status="not_applicable", reason="target_not_inside_declared_room")
            records.append(record)
            continue
        floor = max(room.get("floor_z", room["bounds"]["center"][2] - room["bounds"]["size"][2] / 2) for room in containing)
        ceiling = min(room["bounds"]["center"][2] + room["bounds"]["size"][2] / 2 for room in containing)
        record["room_ids"] = [room["id"] for room in containing]
        record["declared_vertical_range_m"] = [floor, ceiling]
        if position[2] > ceiling + vertical_tolerance_m:
            record.update(status="failed", reason="camera_above_declared_ceiling")
            errors.append({"camera_index": index, "camera_id": record["camera_id"],
                           "code": "camera_above_declared_ceiling",
                           "message": "camera is above the ceiling while targeting a declared room",
                           "vertical_range_m": [floor, ceiling], "position_z_m": position[2]})
        elif position[2] < floor - vertical_tolerance_m:
            record.update(status="failed", reason="camera_below_declared_floor")
            errors.append({"camera_index": index, "camera_id": record["camera_id"],
                           "code": "camera_below_declared_floor",
                           "message": "camera is below the floor while targeting a declared room",
                           "vertical_range_m": [floor, ceiling], "position_z_m": position[2]})
        else:
            record.update(status="passed", reason="camera_vertical_position_is_plausible")
        records.append(record)
    return {"schema": "spatialforge.scene-preflight/v1", "passed": not errors, "blocking": False,
            "errors": errors, "cameras": records,
            "limits": ["declared room bounds only", "does not infer walls or occlusion", "external cameras are allowed"]}
