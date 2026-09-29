from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def load_mask(path: str | Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8) >= 128


def save_mask(path: str | Path, mask: np.ndarray) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L").save(destination)


def area_ratio(mask: np.ndarray) -> float:
    return float(np.count_nonzero(mask) / mask.size)


def intersection_over_union(left: np.ndarray, right: np.ndarray) -> float:
    union = np.count_nonzero(left | right)
    return 0.0 if union == 0 else float(np.count_nonzero(left & right) / union)


def bounding_box(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return [0, 0, 0, 0]
    return [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]


def box_iou(left: list[float], right: list[float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union


def dilate(mask: np.ndarray, pixels: int) -> np.ndarray:
    if pixels <= 0:
        return mask.copy()
    try:
        import cv2

        size = 2 * pixels + 1
        kernel = np.ones((size, size), dtype=np.uint8)
        return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool)
    except ImportError:
        image = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L")
        from PIL import ImageFilter

        return np.asarray(image.filter(ImageFilter.MaxFilter(2 * pixels + 1))) >= 128


def rectangular_fill_mask(mask: np.ndarray, padding: int) -> np.ndarray:
    result = np.zeros_like(mask, dtype=bool)
    x1, y1, x2, y2 = bounding_box(mask)
    if x2 <= x1 or y2 <= y1:
        return result
    height, width = mask.shape
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(width, x2 + padding)
    y2 = min(height, y2 + padding)
    result[y1:y2, x1:x2] = True
    return result


def union_masks(masks: list[np.ndarray], shape: tuple[int, int]) -> np.ndarray:
    result = np.zeros(shape, dtype=bool)
    for mask in masks:
        if mask.shape != shape:
            raise ValueError(f"Mask shape {mask.shape} does not match {shape}")
        result |= mask
    return result
