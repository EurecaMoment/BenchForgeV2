"""Planning directions from native asset front axes verified in captured USD.

These directions are planning aids. Physical scene acceptance still requires
the scene's execution evidence; this module does not edit or accept scenes.
"""

import json
import math
from pathlib import Path
from typing import Sequence, Tuple


_ASSETS = json.loads(
    Path(__file__).with_name("native_asset_facing.json").read_text(encoding="utf-8")
)["assets"]
_AXIS_VECTORS = {
    "+X": (1.0, 0.0),
    "-X": (-1.0, 0.0),
    "+Y": (0.0, 1.0),
    "-Y": (0.0, -1.0),
}


def _front_vector(kind: str) -> Tuple[float, float]:
    record = _ASSETS.get(kind)
    axis = record.get("front_axis") if record else None
    if axis not in _AXIS_VECTORS:
        raise ValueError(f"Unknown or unverified native asset front axis: {kind!r}")
    return _AXIS_VECTORS[axis]


def _xy(value: Sequence[float], name: str) -> Tuple[float, float]:
    try:
        if isinstance(value, (str, bytes)):
            raise ValueError
        x, y = value
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must contain exactly two finite coordinates") from None
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"{name} must contain exactly two finite coordinates")
    return x, y


def yaw_toward(
    kind: str, source_xy: Sequence[float], target_xy: Sequence[float]
) -> float:
    """Return yaw in (-180, 180] degrees that points the verified front at target.

    Positive yaw rotates +X toward +Y around +Z. Unknown front axes and
    coincident points raise ValueError; no scene geometry is changed.
    """
    fx, fy = _front_vector(kind)
    sx, sy = _xy(source_xy, "source_xy")
    tx, ty = _xy(target_xy, "target_xy")
    dx, dy = tx - sx, ty - sy
    if dx == 0.0 and dy == 0.0:
        raise ValueError("source_xy and target_xy must be distinct points")
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError("source_xy to target_xy direction must be finite")
    yaw = math.degrees(math.atan2(dy, dx) - math.atan2(fy, fx)) % 360.0
    return yaw - 360.0 if yaw > 180.0 else yaw


def world_forward(kind: str, yaw_deg: float) -> Tuple[float, float]:
    """Return the verified front's unit XY vector after the given yaw."""
    fx, fy = _front_vector(kind)
    try:
        yaw = float(yaw_deg)
    except (TypeError, ValueError):
        raise ValueError("yaw_deg must be finite") from None
    if not math.isfinite(yaw):
        raise ValueError("yaw_deg must be finite")
    radians = math.radians(yaw % 360.0)
    cosine, sine = math.cos(radians), math.sin(radians)
    return fx * cosine - fy * sine, fx * sine + fy * cosine
