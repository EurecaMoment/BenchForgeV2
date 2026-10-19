"""SpatialTree trajectory records produced from native Isaac state.

This module deliberately accepts already-materialized simulator artifacts. It
does not run a vision model or turn predictions into ground truth. The recorder
is usable from the Isaac desktop executor and remains dependency-free so that
schema validation also works outside Isaac.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "spatialtree.trajectory/v1"


class TrajectoryError(ValueError):
    """Raised when a trajectory would violate the native-state contract."""


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrajectoryError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise TrajectoryError(f"{name} must be finite")
    return result


def _vector(value: Any, name: str, length: int) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise TrajectoryError(f"{name} must contain {length} values")
    return [_finite_number(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _matrix4(value: Any, name: str) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise TrajectoryError(f"{name} must be a 4x4 matrix")
    rows = [_vector(row, f"{name}[{index}]", 4) for index, row in enumerate(value)]
    if any(abs(rows[index][3]) > 1e-5 for index in range(3)) or abs(rows[3][3] - 1) > 1e-5:
        raise TrajectoryError(f"{name} must be a homogeneous transform")
    return rows


def _matmul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _rigid_inverse(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    # Isaac/USD evidence uses row-vector transforms: translation is in row 3.
    rotation = [[matrix[i][j] for j in range(3)] for i in range(3)]
    translation = [matrix[3][j] for j in range(3)]
    inverse = [[0.0 for _ in range(4)] for _ in range(4)]
    for i in range(3):
        for j in range(3):
            inverse[i][j] = rotation[j][i]
    inverse[3] = [-sum(translation[k] * rotation[j][k] for k in range(3)) for j in range(3)] + [1.0]
    return inverse


def _rotation_angle_deg(matrix: Sequence[Sequence[float]]) -> float:
    trace = sum(matrix[index][index] for index in range(3))
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    return math.degrees(math.acos(cosine))


def _relative_transform(previous: Sequence[Sequence[float]], current: Sequence[Sequence[float]]) -> list[list[float]]:
    return _matmul(current, _rigid_inverse(previous))


def _motion_label(delta: Sequence[float], threshold: float = 1e-5) -> str:
    x, y, z = delta
    if math.sqrt(x * x + y * y + z * z) <= threshold:
        return "stationary"
    axis = max(range(3), key=lambda index: abs(delta[index]))
    labels = (("left", "right"), ("down", "up"), ("forward", "backward"))
    return labels[axis][1 if delta[axis] > 0 else 0]


def _artifact_path(output: Path, source: Any, field: str, folder: str = "artifacts") -> str:
    if not isinstance(source, (str, Path)):
        raise TrajectoryError(f"{field} must be a path")
    path = Path(source)
    if not path.is_file() or path.stat().st_size == 0:
        raise TrajectoryError(f"{field} does not point to a non-empty artifact: {path}")
    try:
        return path.relative_to(output).as_posix()
    except ValueError:
        target = output / folder / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        return target.relative_to(output).as_posix()


def _camera_record(camera: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(camera, Mapping):
        raise TrajectoryError("camera must be an object")
    transform = camera.get("T_world_camera_usd", camera.get("T_world_camera"))
    record = dict(camera)
    record["T_world_camera_usd"] = _matrix4(transform, "camera.T_world_camera_usd")
    if "intrinsics" in camera:
        intrinsics = camera["intrinsics"]
        if not isinstance(intrinsics, Mapping):
            raise TrajectoryError("camera.intrinsics must be an object")
        record["intrinsics"] = {**intrinsics, **{key: _finite_number(intrinsics[key], f"camera.intrinsics.{key}")
                                               for key in ('fx', 'fy', 'cx', 'cy')}}
    record.setdefault("convention", "USD camera -Z forward +Y up")
    return record


def _object_record(obj: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, Mapping) or not isinstance(obj.get("object_id"), str) or not obj["object_id"]:
        raise TrajectoryError("each object needs a non-empty object_id")
    record = dict(obj)
    transform = obj.get("T_world_object", obj.get("world_transform"))
    if transform is not None:
        record["T_world_object"] = _matrix4(transform, f"object[{obj['object_id']}].T_world_object")
    if "velocity_world_m_s" in obj:
        record["velocity_world_m_s"] = _vector(obj["velocity_world_m_s"], f"object[{obj['object_id']}].velocity_world_m_s", 3)
    record.setdefault("state_source", "isaac_native")
    return record


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-safe trajectory manifest."""
    if manifest.get("schema") != SCHEMA:
        raise TrajectoryError(f"schema must be {SCHEMA}")
    if manifest.get("source") != "isaac_native":
        raise TrajectoryError("trajectory ground truth must declare source=isaac_native")
    if manifest.get("ground_truth") is not True:
        raise TrajectoryError("native trajectory manifest must declare ground_truth=true")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise TrajectoryError("trajectory needs at least one frame")
    for index, frame in enumerate(frames):
        if frame.get("frame_id") != index:
            raise TrajectoryError("frame_id values must be contiguous from zero")
        _finite_number(frame.get("timestamp_sim"), f"frames[{index}].timestamp_sim")
        _camera_record(frame.get("camera", {}))
        if not isinstance(frame.get("objects"), list):
            raise TrajectoryError(f"frames[{index}].objects must be a list")
    return dict(manifest)


class SpatialTreeTrajectoryRecorder:
    """Collect native per-frame records and write a SpatialTree-ready bundle."""

    def __init__(self, output: str | Path, *, fps: float, width: int, height: int,
                 scenario_id: str = "scene", split: str = "train") -> None:
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.fps = _finite_number(fps, "fps")
        if self.fps <= 0 or type(width) is not int or width <= 0 or type(height) is not int or height <= 0:
            raise TrajectoryError("fps, width and height must be positive")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise TrajectoryError("scenario_id must be non-empty")
        if split not in {"train", "dev", "test", "sealed"}:
            raise TrajectoryError("split must be train, dev, test or sealed")
        self.width, self.height = width, height
        self.scenario_id, self.split = scenario_id, split
        self.frames: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []

    def add_action(self, *, step: int, timestamp_sim: float, action: Mapping[str, Any]) -> dict[str, Any]:
        if type(step) is not int or step < 0:
            raise TrajectoryError("action step must be a non-negative integer")
        row = {"action_id": len(self.actions), "step": step, "timestamp_sim": _finite_number(timestamp_sim, "action.timestamp_sim"),
               "source": "isaac_native", "action": dict(action)}
        self.actions.append(row)
        return row

    def add_frame(self, *, step: int, timestamp_sim: float, rgb_path: str | Path,
                  depth_path: str | Path, semantic_path: str | Path, instance_path: str | Path,
                  camera: Mapping[str, Any], objects: Iterable[Mapping[str, Any]],
                  action_ids: Iterable[int] = (), metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if type(step) is not int or step < 0:
            raise TrajectoryError("frame step must be a non-negative integer")
        if self.frames and step < self.frames[-1]["step"]:
            raise TrajectoryError("frame steps must be monotonic")
        object_rows = [_object_record(obj) for obj in objects]
        if len({row["object_id"] for row in object_rows}) != len(object_rows):
            raise TrajectoryError("object_id must be unique within a frame")
        frame_id = len(self.frames)
        frame = {
            "frame_id": frame_id,
            "step": step,
            "timestamp_sim": _finite_number(timestamp_sim, "frame.timestamp_sim"),
            "timestamp_source": "isaac_simulation_clock",
            "rgb": _artifact_path(self.output, rgb_path, "rgb_path", f"frames/{frame_id:06d}"),
            "depth": _artifact_path(self.output, depth_path, "depth_path", f"frames/{frame_id:06d}"),
            "semantic": _artifact_path(self.output, semantic_path, "semantic_path", f"frames/{frame_id:06d}"),
            "instance": _artifact_path(self.output, instance_path, "instance_path", f"frames/{frame_id:06d}"),
            "depth_kind": "optical_axis_z_m",
            "camera": _camera_record(camera),
            "objects": object_rows,
            "action_ids": [int(value) for value in action_ids],
            "metadata": dict(metadata or {}),
            "source": "isaac_native",
        }
        if self.frames:
            previous = self.frames[-1]
            relative_camera = _relative_transform(previous["camera"]["T_world_camera_usd"], frame["camera"]["T_world_camera_usd"])
            frame["ego_motion"] = {
                "delta_T_camera_previous": relative_camera,
                "translation_m": relative_camera[3][:3],
                "rotation_deg": _rotation_angle_deg(relative_camera),
                "label": "rotation_only" if _motion_label(relative_camera[3][:3]) == "stationary" and _rotation_angle_deg(relative_camera) > 1e-5 else _motion_label(relative_camera[3][:3]),
                "coordinate_frame": "previous_camera_usd_x_right_y_up_z_backward",
            }
            previous_objects = {item["object_id"]: item for item in previous["objects"]}
            frame["correspondence"] = sorted(item["object_id"] for item in object_rows
                if item.get('visible_pixels', 0) > 0 and previous_objects.get(item["object_id"], {}).get('visible_pixels', 0) > 0)
            object_motion = []
            for obj in object_rows:
                old = previous_objects.get(obj["object_id"])
                if old and old.get("T_world_object") and obj.get("T_world_object"):
                    delta = _relative_transform(old["T_world_object"], obj["T_world_object"])
                    translation = [obj['T_world_object'][3][axis] - old['T_world_object'][3][axis] for axis in range(3)]
                    object_motion.append({"object_id": obj["object_id"], "translation_m": translation,
                                          "coordinate_frame": "world_z_up",
                                          "rotation_deg": _rotation_angle_deg(delta),
                                          "moving": math.sqrt(sum(v*v for v in translation)) > 1e-5 or _rotation_angle_deg(delta) > 1e-5})
            frame["object_motion"] = object_motion
        else:
            frame["ego_motion"] = None
            frame["correspondence"] = []
            frame["object_motion"] = []
        self.frames.append(frame)
        return frame

    def finalize(self, *, video_path: str | Path | None = None) -> dict[str, Any]:
        if not self.frames:
            raise TrajectoryError("cannot finalize an empty trajectory")
        manifest: dict[str, Any] = {
            "schema": SCHEMA,
            "source": "isaac_native",
            "ground_truth": True,
            "gt_authority": "Isaac Sim world state, camera state and rendered annotators",
            "scenario_id": self.scenario_id,
            "split": self.split,
            "fps": self.fps,
            "image_size": {"width": self.width, "height": self.height},
            "frame_count": len(self.frames),
            "action_count": len(self.actions),
            "modalities": ["rgb", "depth", "semantic", "instance"],
            "capabilities": ["N04", "N05", "N09", "N14"],
            "provenance": {"kind": "native_simulation", "real_world_calibration": False},
            "correspondence_kind": "object_id_visible_in_both_frames; not dense surface-point tracking",
            "matrix_convention": "USD row-vector local-to-world; translation in last row; meters",
            "frames": self.frames,
            "actions": self.actions,
            "video": None,
        }
        if video_path is not None:
            path = Path(video_path)
            if not path.is_file() or path.stat().st_size == 0:
                raise TrajectoryError(f"video_path does not point to a non-empty artifact: {path}")
            manifest["video"] = _artifact_path(self.output, path, "video_path")
        validate_manifest(manifest)
        (self.output / "frames.jsonl").write_text("".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in self.frames), encoding="utf8")
        (self.output / "actions.jsonl").write_text("".join(json.dumps(action, ensure_ascii=False) + "\n" for action in self.actions), encoding="utf8")
        (self.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
        return {key: value for key, value in manifest.items() if key not in {"frames", "actions"}}
