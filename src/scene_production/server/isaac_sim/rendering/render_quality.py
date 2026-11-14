"""Small per-view render checks used to explain failed captures."""
from __future__ import annotations

from typing import Any


def assess_view(rgb: Any, depth: Any, objects: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np

    pixels = np.asarray(rgb)
    depth_values = np.asarray(depth)
    rgb_std = float(pixels.std()) if pixels.size else 0.0
    finite = np.isfinite(depth_values) & (depth_values > 0)
    finite_fraction = float(finite.mean()) if finite.size else 0.0
    visible_entity_count = len(objects) if isinstance(objects, list) else 0
    reasons = []
    if rgb_std <= 5.0:
        reasons.append("rgb_low_variance")
    if finite_fraction < 0.05:
        reasons.append("insufficient_finite_depth")
    if visible_entity_count < 1:
        reasons.append("no_visible_entities")
    return {"passed": not reasons, "rgb_std": rgb_std,
            "finite_depth_fraction": finite_fraction,
            "visible_entity_count": visible_entity_count, "reasons": reasons,
            "thresholds": {"rgb_std_min": 5.0, "finite_depth_fraction_min": 0.05,
                           "visible_entity_count_min": 1}}
