#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BenchClaw executable Stage4 synthesis engine.

Adapted from the user-provided runnable UAV / embodied-spatial static VLM benchmark synthesizer and
connected to the unified template pack schema. It preserves the original generation logic while emitting
BenchClaw unified eval-item fields (`item_id`, `question_text`, `gold_answer`, `evidence_ref`, etc.) in
addition to backward-compatible aliases.

UAV / embodied-spatial static VLM benchmark synthesizer.

Input data contract, compatible with the uploaded sample folder/zip:
  sample/
    img_0001.jpg
    entity_annotations.json
    result.json                         optional
    instance_masks/*.png                optional
    depth_map.png / semantic_*.png      optional

Core GT fields used:
  objects[*].object_id
  objects[*].category
  objects[*].mask.area_px / mask.path
  objects[*].bbox_2d.xyxy / centroid_xy / centroid_normalized_xy
  objects[*].depth_median / depth_stats
  objects[*].centroid_3d.xyz
  objects[*].rough_3d_bbox.size_xyz
  objects[*].confidence.value
  objects[*].valid_for_question_generation

This script generates JSONL items.  Instance-level questions use generated
bbox overlays so that labels A/B/C/D are visually grounded rather than hidden
inside metadata.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:  # pragma: no cover
    raise SystemExit("Pillow is required: pip install pillow") from exc

LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

DEFAULT_NEGATIVE_CATEGORIES = [
    # outdoor / UAV / road scene distractors
    "person", "bicycle", "motorcycle", "traffic light", "traffic sign",
    "crosswalk", "river", "boat", "airplane", "bench", "container",
    "railway", "sidewalk", "street lamp", "crane", "excavator",
    # indoor distractors, useful when mixing scene types
    "chair", "table", "sofa", "bed", "door", "window", "sink", "refrigerator",
]


# Strict production policy for BenchClaw agent template selection.
# Default generation uses only templates that are stable for static image-text benchmark construction.
# Deprecated templates are hard-locked: they cannot be generated even if requested.
STRICT_CORE_TEMPLATES = {
    "T001", "T002", "T006", "T008",
    "T012", "T013", "T014", "T015",
    "T021", "T022", "T023", "T024",
    "T030", "T031", "T045", "T085",
}
STRICT_DEPTH_TEMPLATES = STRICT_CORE_TEMPLATES | {
    "T036", "T037", "T038", "T039", "T040", "T041", "T091", "T095", "T096", "T097",
}
STRICT_REWRITTEN_OPTIONAL_TEMPLATES = STRICT_DEPTH_TEMPLATES | {
    "T003", "T004", "T011", "T025", "T026", "T027", "T028", "T029", "T032", "T033", "T034", "T035",
    "T056", "T057", "T060", "T063",
}
DEPRECATED_LOCKED_TEMPLATES = {
    "T020", "T042", "T043", "T058", "T061", "T064", "T069", "T081", "T082", "T083", "T084", "T090", "T093", "T099", "T100",
}
TEMPLATE_SETS = {
    "strict_core": STRICT_CORE_TEMPLATES,
    "strict_depth": STRICT_DEPTH_TEMPLATES,
    "strict_all_supported": STRICT_REWRITTEN_OPTIONAL_TEMPLATES,
}

GRID_9_ZH = {
    (0, 0): "左上", (1, 0): "上中", (2, 0): "右上",
    (0, 1): "左中", (1, 1): "中心", (2, 1): "右中",
    (0, 2): "左下", (1, 2): "下中", (2, 2): "右下",
}

DEPTH_BINS = [
    (0.0, 2.0, "小于 2 米"),
    (2.0, 4.0, "2–4 米"),
    (4.0, 6.0, "4–6 米"),
    (6.0, 10.0, "6–10 米"),
    (10.0, float("inf"), "大于等于 10 米"),
]

DIST_BINS = [
    (0.0, 0.5, "小于 0.5 米"),
    (0.5, 1.0, "0.5–1 米"),
    (1.0, 2.0, "1–2 米"),
    (2.0, 5.0, "2–5 米"),
    (5.0, float("inf"), "大于等于 5 米"),
]

TEMPLATE_META: Dict[str, Dict[str, Any]] = {
    "T001": {"format": "F3 判断题", "capability": ["C1", "C11"], "scoring": "Exact Match"},
    "T002": {"format": "F2 多选题", "capability": ["C1"], "scoring": "Precision / Recall / F1"},
    "T003": {"format": "F1 单选题", "capability": ["C1"], "scoring": "Exact Match"},
    "T004": {"format": "F1 单选题", "capability": ["C1", "C8"], "scoring": "Exact Match"},
    "T006": {"format": "F3 判断题", "capability": ["C1"], "scoring": "Exact Match"},
    "T007": {"format": "F12 图文匹配题", "capability": ["C1"], "scoring": "Exact Match"},
    "T008": {"format": "F9 区间选择题", "capability": ["C1", "C2"], "scoring": "Exact Match"},
    "T011": {"format": "F9 区间选择题", "capability": ["C2"], "scoring": "Exact Match"},
    "T012": {"format": "F10 对比选择题", "capability": ["C2"], "scoring": "Exact Match"},
    "T013": {"format": "F1 单选题", "capability": ["C2"], "scoring": "Exact Match"},
    "T014": {"format": "F5 排序题", "capability": ["C2"], "scoring": "Kendall Tau / Pairwise Accuracy"},
    "T015": {"format": "F9 区间选择题", "capability": ["C2"], "scoring": "Exact Match"},
    "T020": {"format": "F24 JSON 结构化输出题", "capability": ["C2"], "scoring": "Schema Check + Field Accuracy"},
    "T021": {"format": "F3 判断题", "capability": ["C5"], "scoring": "Exact Match"},
    "T022": {"format": "F3 判断题", "capability": ["C5"], "scoring": "Exact Match"},
    "T023": {"format": "F3 判断题", "capability": ["C5"], "scoring": "Exact Match"},
    "T024": {"format": "F3 判断题", "capability": ["C5"], "scoring": "Exact Match"},
    "T025": {"format": "F1 单选题", "capability": ["C5"], "scoring": "Exact Match"},
    "T026": {"format": "F1 单选题", "capability": ["C5"], "scoring": "Exact Match"},
    "T027": {"format": "F1 单选题", "capability": ["C5"], "scoring": "Exact Match"},
    "T028": {"format": "F1 单选题", "capability": ["C5"], "scoring": "Exact Match"},
    "T029": {"format": "F1 单选题", "capability": ["C5"], "scoring": "Exact Match"},
    "T030": {"format": "F13 区域选择题", "capability": ["C5"], "scoring": "Exact Match"},
    "T031": {"format": "F13 区域选择题", "capability": ["C5"], "scoring": "Exact Match"},
    "T032": {"format": "F3 判断题", "capability": ["C5", "C12"], "scoring": "Exact Match"},
    "T033": {"format": "F3 判断题", "capability": ["C5"], "scoring": "Exact Match"},
    "T034": {"format": "F5 排序题", "capability": ["C5"], "scoring": "Kendall Tau / Pairwise Accuracy"},
    "T035": {"format": "F5 排序题", "capability": ["C5"], "scoring": "Kendall Tau / Pairwise Accuracy"},
    "T036": {"format": "F10 对比选择题", "capability": ["C6", "C7"], "scoring": "Exact Match"},
    "T037": {"format": "F1 单选题", "capability": ["C7"], "scoring": "Exact Match"},
    "T038": {"format": "F1 单选题", "capability": ["C7"], "scoring": "Exact Match"},
    "T039": {"format": "F5 排序题", "capability": ["C7"], "scoring": "Kendall Tau / Pairwise Accuracy"},
    "T040": {"format": "F9 区间选择题", "capability": ["C7"], "scoring": "Exact Match"},
    "T041": {"format": "F3 判断题", "capability": ["C7"], "scoring": "Exact Match"},
    "T042": {"format": "F10 对比选择题", "capability": ["C7"], "scoring": "Exact Match"},
    "T043": {"format": "F3 判断题", "capability": ["C6"], "scoring": "Exact Match"},
    "T045": {"format": "F3 判断题", "capability": ["C1", "C7"], "scoring": "Exact Match"},
    "T056": {"format": "F9 区间选择题", "capability": ["C7"], "scoring": "Exact Match"},
    "T057": {"format": "F10 对比选择题", "capability": ["C7"], "scoring": "Exact Match"},
    "T060": {"format": "F1 单选题", "capability": ["C8"], "scoring": "Exact Match"},
    "T061": {"format": "F1 单选题", "capability": ["C8"], "scoring": "Exact Match"},
    "T063": {"format": "F5 排序题", "capability": ["C8"], "scoring": "Kendall Tau / Pairwise Accuracy"},
    "T082": {"format": "F20 错误检测题", "capability": ["C30"], "scoring": "Exact Match"},
    "T084": {"format": "F3 判断题", "capability": ["C11", "C30"], "scoring": "Exact Match"},
    "T085": {"format": "F20 错误检测题", "capability": ["C1", "C11"], "scoring": "Exact Match"},
    "T090": {"format": "F4 三选判断题", "capability": ["C30"], "scoring": "Exact Match"},
    "T091": {"format": "F3 判断题", "capability": ["C6", "C12"], "scoring": "Exact Match"},
    "T095": {"format": "F5 排序题", "capability": ["C12", "C7"], "scoring": "Kendall Tau / Pairwise Accuracy"},
    "T096": {"format": "F1 单选题", "capability": ["C27", "C28"], "scoring": "Exact Match"},
    "T097": {"format": "F1 单选题", "capability": ["C5", "C28"], "scoring": "Exact Match"},
    "T099": {"format": "F6 匹配题", "capability": ["C5", "C7"], "scoring": "Field Accuracy"},
    "T100": {"format": "F24 JSON 结构化输出题", "capability": ["C1", "C7", "C28"], "scoring": "Schema Check + Field Accuracy"},
}


@dataclass
class Obj:
    object_id: str
    category: str
    area: int
    bbox: Tuple[int, int, int, int]
    cx: float
    cy: float
    nx: float
    ny: float
    depth: Optional[float]
    xyz: Optional[Tuple[float, float, float]]
    size_xyz: Optional[Tuple[float, float, float]]
    confidence: float
    mask_path: Optional[str]
    yoloe_verified: bool

    @property
    def ref(self) -> str:
        return f"{self.category}#{self.object_id}"

    @property
    def volume(self) -> Optional[float]:
        if not self.size_xyz:
            return None
        x, y, z = self.size_xyz
        if x is None or y is None or z is None:
            return None
        return float(max(x, 0.0) * max(y, 0.0) * max(z, 0.0))

    @property
    def height_like(self) -> Optional[float]:
        # Camera frame in this dataset is x-right, y-down, z-forward.
        # This is not world height. We only use it as visible 3D bbox y-size.
        if not self.size_xyz:
            return None
        return float(self.size_xyz[1])


@dataclass
class Sample:
    sample_id: str
    source_path: str
    image_size: Tuple[int, int]
    image_bytes: bytes
    image_name: str
    entity_json: Dict[str, Any]
    objects: List[Obj]
    zip_file: Optional[zipfile.ZipFile] = None
    root_dir: Optional[Path] = None


def metric_from_scoring_text(scoring_text: str, answer_type: str) -> str:
    """Map the original human-readable scoring note to the package scorer metric id."""
    s = (scoring_text or "").lower()
    at = (answer_type or "").lower()
    if "precision" in s or "recall" in s or "f1" in s:
        return "set_exact_match + macro_f1"
    if "kendall" in s or "pairwise" in s or at == "ordered_list":
        return "ordered_list_pairwise_accuracy"
    if "schema" in s or "field accuracy" in s or at in {"json", "json_array"}:
        return "json_field_accuracy"
    if "absolute error" in s or at == "number":
        return "numeric_exact"
    return "exact_match"


def unified_gold_answer(answer: Any, answer_type: str) -> Any:
    """Normalize generated answers without discarding structured answers."""
    if answer_type == "multi_choice" and isinstance(answer, list):
        return sorted(answer)
    if answer_type == "ordered_list" and isinstance(answer, list):
        return answer
    return answer


def build_unified_scoring(scoring_text: str, answer_type: str, template_id: str) -> Dict[str, Any]:
    metric = metric_from_scoring_text(scoring_text, answer_type)
    normalization = ["strip", "upper"]
    if "set" in metric or answer_type == "multi_choice":
        normalization.append("split_comma_for_sets")
    if answer_type in {"json", "json_array"}:
        normalization = ["parse_json", "field_compare"]
    if answer_type == "ordered_list":
        normalization = ["strip", "upper", "split_sequence"]
    return {
        "metric": metric,
        "normalization": normalization,
        "tolerance": None,
        "aggregation_group": template_id,
    }


def relative_or_str(path: str) -> str:
    """Keep a stable string path; downstream packaging can rewrite it if needed."""
    return str(path)


class ItemSink:
    def __init__(self, sample: Sample, asset_dir: Path, max_per_template: int, rng: random.Random, allowed_template_ids: Optional[set[str]] = None):
        self.sample = sample
        self.asset_dir = asset_dir
        self.max_per_template = max_per_template
        self.rng = rng
        self.allowed_template_ids = allowed_template_ids
        self.items: List[Dict[str, Any]] = []
        self.count_by_template: Counter[str] = Counter()
        self.used_signatures: set = set()
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        self.base_image_path = self.asset_dir / f"{self.sample.sample_id}.jpg"
        if not self.base_image_path.exists():
            self.base_image_path.write_bytes(sample.image_bytes)

    def can_add(self, template_id: str) -> bool:
        if template_id in DEPRECATED_LOCKED_TEMPLATES:
            return False
        if self.allowed_template_ids is not None and template_id not in self.allowed_template_ids:
            return False
        return self.count_by_template[template_id] < self.max_per_template

    def add(
        self,
        template_id: str,
        question: str,
        answer: Any,
        answer_type: str,
        options: Optional[Any] = None,
        objects: Optional[List[Obj]] = None,
        fields: Optional[List[str]] = None,
        gt: Optional[Dict[str, Any]] = None,
        overlay_objects: Optional[List[Obj]] = None,
        overlay_labels: Optional[List[str]] = None,
        quality: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.can_add(template_id):
            return False
        obj_sig = [o.object_id for o in (objects or [])]
        # Same wording can be valid for different overlay-labeled objects.
        # Keep object IDs and GT in the signature to avoid suppressing valid variants.
        sig = json.dumps([template_id, question, answer, options, obj_sig, gt], ensure_ascii=False, sort_keys=True)
        if sig in self.used_signatures:
            return False
        self.used_signatures.add(sig)
        local_idx = self.count_by_template[template_id] + 1
        qa_id = f"{self.sample.sample_id}_{template_id}_{local_idx:04d}"
        image_path = str(self.base_image_path)
        auxiliary_images: List[str] = []
        if overlay_objects:
            overlay_path = self.asset_dir / f"{qa_id}_overlay.jpg"
            make_overlay(self.sample.image_bytes, overlay_objects, overlay_labels, overlay_path)
            image_path = str(overlay_path)
            auxiliary_images.append(str(self.base_image_path))

        meta = TEMPLATE_META.get(template_id, {})
        item = {
            "id": qa_id,
            "sample_id": self.sample.sample_id,
            "image": image_path,
            "auxiliary_images": auxiliary_images,
            "template_id": template_id,
            "question_format": meta.get("format"),
            "capability": meta.get("capability", []),
            "question": question,
            "options": options,
            "answer": answer,
            "answer_type": answer_type,
            "scoring": meta.get("scoring", "Exact Match"),
            "provenance": {
                "source_path": self.sample.source_path,
                "gt_file": "entity_annotations.json",
                "gt_fields": fields or [],
                "objects": [obj_brief(o) for o in (objects or [])],
                "gt_values": gt or {},
            },
            "quality_flags": quality or {},
        }
        # BenchClaw unified eval-item fields.  The original aliases (`id`, `sample_id`,
        # `question`, `answer`, `provenance`) are intentionally retained so existing
        # scripts that used the user-provided synthesizer remain compatible.
        capability_ids = list(meta.get("capability", []))
        item.update({
            "item_id": qa_id,
            "source_sample_id": self.sample.sample_id,
            "question_text": question,
            "answer_format": meta.get("format") or answer_type,
            "capability_ids": capability_ids,
            "primary_capability_id": capability_ids[0] if capability_ids else "UNKNOWN",
            "gold_answer": unified_gold_answer(answer, answer_type),
            "scoring": build_unified_scoring(meta.get("scoring", "Exact Match"), answer_type, template_id),
            "evidence_ref": [relative_or_str(image_path)] + [relative_or_str(p) for p in auxiliary_images],
            "evidence_fields": fields or [],
            "answer_derivation": "由 entity_annotations.json 的 GT 字段、实例 bbox/mask/depth/3D 信息，以及脚本内确定性计算生成。",
            "quality_gate": {
                "gt_available": True,
                "answer_unique_or_set_defined": True,
                "evidence_bound": True,
                **(quality or {}),
            },
            "metadata": {
                "generator": "tools/synthesize_static_vlm_benchmark.py",
                "generator_family": "static_embodied_spatial_vlm",
                "original_answer_type": answer_type,
                "original_question_format": meta.get("format"),
                "image": relative_or_str(image_path),
                "auxiliary_images": [relative_or_str(p) for p in auxiliary_images],
                "source_path": self.sample.source_path,
                "gt_values": gt or {},
                "objects": [obj_brief(o) for o in (objects or [])],
            },
        })
        self.items.append(item)
        self.count_by_template[template_id] += 1
        return True


def obj_brief(o: Obj) -> Dict[str, Any]:
    return {
        "object_id": o.object_id,
        "category": o.category,
        "bbox_xyxy": list(o.bbox),
        "centroid_xy": [round(o.cx, 3), round(o.cy, 3)],
        "centroid_normalized_xy": [round(o.nx, 6), round(o.ny, 6)],
        "area_px": o.area,
        "depth_median": None if o.depth is None else round(o.depth, 6),
        "centroid_3d": None if o.xyz is None else [round(v, 6) for v in o.xyz],
        "rough_3d_bbox_size": None if o.size_xyz is None else [round(v, 6) for v in o.size_xyz],
        "confidence": round(o.confidence, 6),
        "yoloe_verified": o.yoloe_verified,
    }


def make_overlay(image_bytes: bytes, objs: Sequence[Obj], labels: Optional[Sequence[str]], out_path: Path) -> None:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=26)
        small_font = ImageFont.truetype("DejaVuSans.ttf", size=14)
    except Exception:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    if labels is None:
        labels = LETTERS[:len(objs)]
    palette = [
        (255, 0, 0), (0, 160, 255), (0, 180, 0), (255, 128, 0),
        (180, 0, 255), (0, 200, 200), (255, 0, 180), (200, 200, 0),
    ]
    for i, (obj, lab) in enumerate(zip(objs, labels)):
        color = palette[i % len(palette)]
        x1, y1, x2, y2 = obj.bbox
        # Make tiny boxes visible.
        pad = 3
        x1p, y1p, x2p, y2p = max(0, x1 - pad), max(0, y1 - pad), min(image.width - 1, x2 + pad), min(image.height - 1, y2 + pad)
        for w in range(4):
            draw.rectangle([x1p - w, y1p - w, x2p + w, y2p + w], outline=color)
        label_text = f"{lab}"
        text_box = draw.textbbox((x1p, y1p), label_text, font=font)
        tw, th = text_box[2] - text_box[0], text_box[3] - text_box[1]
        draw.rectangle([x1p, max(0, y1p - th - 6), x1p + tw + 8, y1p], fill=color)
        draw.text((x1p + 4, max(0, y1p - th - 5)), label_text, fill=(255, 255, 255), font=font)
        # Put category in a small caption, but not bbox values.
        caption = obj.category[:30]
        draw.text((x1p, min(image.height - 16, y2p + 3)), caption, fill=color, font=small_font)
    image.save(out_path, quality=92)


def read_json_from_zip(zf: zipfile.ZipFile, name: str) -> Dict[str, Any]:
    return json.loads(zf.read(name).decode("utf-8"))


def discover_samples(input_path: Path) -> List[Sample]:
    paths: List[Path] = []
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        paths = [input_path]
    elif input_path.is_dir():
        # Accept either a single sample dir or a parent dir containing many samples/zips.
        if (input_path / "entity_annotations.json").exists():
            paths.append(input_path)
        paths.extend(sorted(input_path.rglob("*.zip")))
        for p in sorted(input_path.rglob("entity_annotations.json")):
            if p.parent != input_path:
                paths.append(p.parent)
    else:
        raise FileNotFoundError(f"Input path not found: {input_path}")

    seen = set()
    samples: List[Sample] = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            samples.append(load_sample(p))
        except Exception as exc:
            print(f"[warn] skip {p}: {exc}", file=sys.stderr)
    return samples


def load_sample(path: Path) -> Sample:
    if path.is_file() and path.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(path, "r")
        names = zf.namelist()
        ent_name = next((n for n in names if n.endswith("entity_annotations.json")), None)
        if not ent_name:
            raise ValueError("entity_annotations.json not found in zip")
        ent = read_json_from_zip(zf, ent_name)
        image_name = find_image_name_in_zip(zf, ent)
        image_bytes = zf.read(image_name)
        sample_id = path.stem
        # If the zip is named img_0001.zip and contains img_0001.jpg, keep stem.
        return build_sample(sample_id, str(path), ent, image_bytes, Path(image_name).name, zf, None)
    else:
        ent_path = path / "entity_annotations.json"
        ent = json.loads(ent_path.read_text(encoding="utf-8"))
        image_path = find_image_path_in_dir(path, ent)
        image_bytes = image_path.read_bytes()
        return build_sample(path.name, str(path), ent, image_bytes, image_path.name, None, path)


def find_image_name_in_zip(zf: zipfile.ZipFile, ent: Dict[str, Any]) -> str:
    names = zf.namelist()
    image_basename = Path(ent.get("image_path", "")).name
    if image_basename:
        for n in names:
            if Path(n).name == image_basename:
                return n
    for n in names:
        if Path(n).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and not n.endswith("/"):
            base = Path(n).name.lower()
            if base not in {"depth_map.png", "semantic_entity_segmentation.png", "yoloe_annotated.png"} and "mask" not in n.lower():
                return n
    raise ValueError("RGB image not found in zip")


def find_image_path_in_dir(root: Path, ent: Dict[str, Any]) -> Path:
    image_basename = Path(ent.get("image_path", "")).name
    if image_basename and (root / image_basename).exists():
        return root / image_basename
    for p in sorted(root.iterdir()):
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and p.name not in {"depth_map.png", "semantic_entity_segmentation.png", "yoloe_annotated.png"}:
            return p
    raise ValueError("RGB image not found in directory")


def build_sample(sample_id: str, source_path: str, ent: Dict[str, Any], image_bytes: bytes, image_name: str,
                 zf: Optional[zipfile.ZipFile], root_dir: Optional[Path]) -> Sample:
    width = int(ent.get("image_size", {}).get("width", 0))
    height = int(ent.get("image_size", {}).get("height", 0))
    if not width or not height:
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
    objects: List[Obj] = []
    for raw in ent.get("objects", []):
        bbox = raw.get("bbox_2d", {}).get("xyxy")
        cent = raw.get("bbox_2d", {}).get("centroid_xy")
        ncent = raw.get("bbox_2d", {}).get("centroid_normalized_xy")
        if not bbox or not cent:
            continue
        if not ncent:
            ncent = [cent[0] / width, cent[1] / height]
        conf = raw.get("confidence", {}).get("value", 0.0)
        xyz_raw = raw.get("centroid_3d", {}).get("xyz")
        xyz = tuple(map(float, xyz_raw)) if xyz_raw and len(xyz_raw) == 3 else None
        size_raw = raw.get("rough_3d_bbox", {}).get("size_xyz")
        size_xyz = tuple(map(float, size_raw)) if size_raw and len(size_raw) == 3 else None
        depth = raw.get("depth_median", None)
        if depth is not None:
            try:
                depth = float(depth)
                if not math.isfinite(depth):
                    depth = None
            except Exception:
                depth = None
        objects.append(Obj(
            object_id=str(raw.get("object_id")),
            category=str(raw.get("category")),
            area=int(raw.get("mask", {}).get("area_px", 0)),
            bbox=tuple(map(int, bbox)),
            cx=float(cent[0]),
            cy=float(cent[1]),
            nx=float(ncent[0]),
            ny=float(ncent[1]),
            depth=depth,
            xyz=xyz,
            size_xyz=size_xyz,
            confidence=float(conf or 0.0),
            mask_path=raw.get("mask", {}).get("path"),
            yoloe_verified=bool(raw.get("source", {}).get("yoloe_verified", False)),
        ))
    return Sample(sample_id=sample_id, source_path=source_path, image_size=(width, height), image_bytes=image_bytes,
                  image_name=image_name, entity_json=ent, objects=objects, zip_file=zf, root_dir=root_dir)


def filter_objects(sample: Sample, min_conf: float, min_area: int, require_valid: bool,
                   drop_categories: set[str], max_area_frac: float) -> List[Obj]:
    raw_valid = {str(o.get("object_id")): bool(o.get("valid_for_question_generation", True)) for o in sample.entity_json.get("objects", [])}
    out = []
    img_area = max(1, sample.image_size[0] * sample.image_size[1])
    for o in sample.objects:
        if o.category in drop_categories:
            continue
        if require_valid and not raw_valid.get(o.object_id, True):
            continue
        if o.confidence < min_conf:
            continue
        if o.area < min_area:
            continue
        if max_area_frac > 0 and (o.area / img_area) > max_area_frac:
            continue
        x1, y1, x2, y2 = o.bbox
        if x2 <= x1 or y2 <= y1:
            continue
        out.append(o)
    return out


def category_counts(objs: Sequence[Obj]) -> Counter[str]:
    return Counter(o.category for o in objs)


def category_area(objs: Sequence[Obj]) -> Counter[str]:
    c = Counter()
    for o in objs:
        c[o.category] += o.area
    return c


def unique_best_by(values: Sequence[Tuple[Any, float]], margin_abs: float = 0.0, margin_ratio: float = 1.0,
                   reverse: bool = True) -> Optional[Any]:
    if len(values) < 2:
        return None
    vals = sorted(values, key=lambda x: x[1], reverse=reverse)
    best, second = vals[0], vals[1]
    diff = (best[1] - second[1]) if reverse else (second[1] - best[1])
    ratio_ok = True
    if margin_ratio > 1.0 and second[1] != 0:
        ratio_ok = (best[1] / second[1] >= margin_ratio) if reverse else (second[1] / best[1] >= margin_ratio)
    if diff >= margin_abs and ratio_ok:
        return best[0]
    return None


def as_options(labels: Sequence[str]) -> Dict[str, str]:
    return {LETTERS[i]: labels[i] for i in range(len(labels))}


def answer_letter(options: Dict[str, str], label: str) -> str:
    for k, v in options.items():
        if v == label:
            return k
    raise ValueError(f"label not in options: {label}")


def interval_label(value: float, bins: Sequence[Tuple[float, float, str]]) -> str:
    for lo, hi, lab in bins:
        if lo <= value < hi:
            return lab
    return bins[-1][2]


def total_count_interval(n: int) -> str:
    if n <= 5:
        return "0–5"
    if n <= 20:
        return "6–20"
    if n <= 50:
        return "21–50"
    if n <= 100:
        return "51–100"
    return "大于 100"


def category_count_interval(n: int) -> str:
    if n <= 3:
        return "0–3 类"
    if n <= 8:
        return "4–8 类"
    if n <= 15:
        return "9–15 类"
    return "大于 15 类"


def grid9(obj: Obj) -> str:
    gx = min(2, max(0, int(obj.nx * 3)))
    gy = min(2, max(0, int(obj.ny * 3)))
    return GRID_9_ZH[(gx, gy)]


def pairwise_distance_xyz(a: Obj, b: Obj) -> Optional[float]:
    if a.xyz is None or b.xyz is None:
        return None
    return math.sqrt(sum((a.xyz[i] - b.xyz[i]) ** 2 for i in range(3)))


def bbox_intersection_area(a: Obj, b: Obj) -> int:
    ax1, ay1, ax2, ay2 = a.bbox
    bx1, by1, bx2, by2 = b.bbox
    x1, y1, x2, y2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    return max(0, x2 - x1) * max(0, y2 - y1)


def bbox_gap(a: Obj, b: Obj) -> float:
    ax1, ay1, ax2, ay2 = a.bbox
    bx1, by1, bx2, by2 = b.bbox
    dx = max(0, max(ax1, bx1) - min(ax2, bx2))
    dy = max(0, max(ay1, by1) - min(ay2, by2))
    return math.sqrt(dx * dx + dy * dy)


def choose_pairs(objs: Sequence[Obj], rng: random.Random, n: int = 200) -> Iterable[Tuple[Obj, Obj]]:
    if len(objs) < 2:
        return []
    pairs = []
    tries = min(n, len(objs) * (len(objs) - 1) // 2)
    for _ in range(tries):
        a, b = rng.sample(list(objs), 2)
        pairs.append((a, b))
    return pairs


def choose_k(objs: Sequence[Obj], rng: random.Random, k: int) -> Optional[List[Obj]]:
    if len(objs) < k:
        return None
    # Prefer visually salient objects; randomize among the top area/confidence group.
    pool = sorted(objs, key=lambda o: (o.area, o.confidence), reverse=True)[:max(k * 8, k)]
    return rng.sample(pool, k)


def shuffle_options_with_answer(rng: random.Random, labels: List[str], answer_label: str) -> Tuple[Dict[str, str], str]:
    rng.shuffle(labels)
    options = as_options(labels)
    return options, answer_letter(options, answer_label)


def generate_items_for_sample(sample: Sample, args: argparse.Namespace) -> List[Dict[str, Any]]:
    rng = random.Random(args.seed + stable_hash(sample.sample_id))
    asset_dir = Path(args.asset_dir) / sample.sample_id
    requested = {x.strip() for x in (args.template_ids or "").split(",") if x.strip()}
    if requested:
        allowed_template_ids = requested - DEPRECATED_LOCKED_TEMPLATES
    else:
        allowed_template_ids = set(TEMPLATE_SETS[args.template_set])
    sink = ItemSink(sample, asset_dir, args.max_per_template, rng, allowed_template_ids)
    drop_categories = {x.strip() for x in args.drop_categories.split(",") if x.strip()}
    objs = filter_objects(sample, args.min_conf, args.min_area, args.require_valid, drop_categories, args.max_area_frac)
    objs_depth = [o for o in objs if o.depth is not None]
    objs_xyz = [o for o in objs if o.xyz is not None]
    objs_3d_size = [o for o in objs if o.volume is not None and o.volume > 0]
    counts = category_counts(objs)
    areas = category_area(objs)
    present = sorted(counts)
    neg_pool = [x.strip() for x in args.negative_categories.split(",") if x.strip()]
    absent = [c for c in neg_pool if c not in counts]

    # Category / existence templates.
    gen_T001_T002_T003_T004_T006_T007_T008(sink, rng, objs, present, absent, counts, areas)
    gen_T011_T012_T013_T014_T015_T020(sink, rng, objs, present, absent, counts)

    # 2D templates.
    gen_T021_to_T035(sink, rng, objs, sample.image_size, args)

    # Depth and 3D templates.
    if args.include_depth:
        gen_T036_to_T045(sink, rng, objs_depth, counts)
        gen_T091_T095_T096_T097_T099_T100(sink, rng, objs_depth, counts)
    if args.include_3d:
        gen_T056_T057_T060_T061_T063(sink, rng, objs_xyz, objs_3d_size)

    # Unanswerable / evidence-boundary templates.
    gen_T082_T084_T090(sink, rng, present, absent)
    return sink.items


def stable_hash(text: str) -> int:
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def gen_T001_T002_T003_T004_T006_T007_T008(sink: ItemSink, rng: random.Random, objs: List[Obj],
                                           present: List[str], absent: List[str], counts: Counter[str], areas: Counter[str]) -> None:
    # T001 existence, both positive and negative if possible.
    for cat in rng.sample(present, min(len(present), sink.max_per_template)):
        sink.add("T001", f"当前图像中是否可见 {cat}？", "是", "yes_no", {"A": "是", "B": "否"},
                 fields=["objects.category"], gt={"category": cat, "present": True})
    for cat in rng.sample(absent, min(len(absent), sink.max_per_template)):
        sink.add("T001", f"当前图像中是否可见 {cat}？", "否", "yes_no", {"A": "是", "B": "否"},
                 fields=["objects.category"], gt={"category": cat, "present": False})

    # T002 multi-choice visible categories.
    if len(present) >= 2 and len(absent) >= 2:
        for _ in range(sink.max_per_template):
            pos = rng.sample(present, min(3, len(present)))
            neg = rng.sample(absent, min(2, len(absent)))
            labels = pos + neg
            rng.shuffle(labels)
            opts = as_options(labels)
            answer = sorted([k for k, v in opts.items() if v in pos])
            sink.add("T002", "从候选项中选择当前图像中可见的物体类别，可多选。", answer, "multi_choice", opts,
                     fields=["objects.category"], gt={"visible_categories": pos, "distractors": neg})

    # T003 main visible object by total mask area per category.
    if len(areas) >= 2:
        best = unique_best_by(list(areas.items()), margin_ratio=1.15, reverse=True)
        if best:
            distractors = [c for c in present if c != best]
            labels = [best] + rng.sample(distractors, min(3, len(distractors)))
            opts, ans = shuffle_options_with_answer(rng, labels, best)
            sink.add("T003", "按所有实例的可见 mask 面积合计，当前图像中主要可见的物体类别是哪一个？", ans, "single_choice", opts,
                     fields=["objects.category", "objects.mask.area_px"], gt={"category_area_px": dict(areas), "answer_category": best},
                     quality={"definition": "main = category with largest total visible mask area"})

    # T004 fill blank largest visible category.
    if areas:
        best = max(areas.items(), key=lambda kv: kv[1])[0]
        sink.add("T004", "当前图像中可见面积最大的物体类别是什么？请直接输出类别名称。", best, "text",
                 fields=["objects.category", "objects.mask.area_px"], gt={"category_area_px": dict(areas), "answer_category": best})

    # T006 simultaneous visibility.
    if len(present) >= 2:
        for _ in range(sink.max_per_template):
            a, b = rng.sample(present, 2)
            sink.add("T006", f"当前图像中是否同时可见 {a} 和 {b}？", "是", "yes_no", {"A": "是", "B": "否"},
                     fields=["objects.category"], gt={"category_A": a, "category_B": b, "both_present": True})
    if present and absent:
        for _ in range(sink.max_per_template):
            a = rng.choice(present)
            b = rng.choice(absent)
            sink.add("T006", f"当前图像中是否同时可见 {a} 和 {b}？", "否", "yes_no", {"A": "是", "B": "否"},
                     fields=["objects.category"], gt={"category_A": a, "category_B": b, "both_present": False})

    # T007 matching description.
    if len(present) >= 2 and absent:
        for _ in range(sink.max_per_template):
            p1, p2 = rng.sample(present, 2)
            n1 = rng.choice(absent)
            labels = [
                f"图像中可见 {p1} 和 {p2}",
                f"图像中可见 {p1}，但没有任何可见物体类别",
                f"图像中可见 {n1}，并且 {n1} 是主要物体",
                f"图像中只可见 {p2} 这一类物体",
            ]
            answer_label = labels[0]
            opts, ans = shuffle_options_with_answer(rng, labels, answer_label)
            sink.add("T007", "下列哪一项描述与当前图像中的可见物体类别列表一致？", ans, "single_choice", opts,
                     fields=["objects.category"], gt={"visible_categories": present, "true_description": answer_label})

    # T008 visible category count interval.
    if present:
        n = len(present)
        labels = ["0–3 类", "4–8 类", "9–15 类", "大于 15 类"]
        answer_label = category_count_interval(n)
        opts, ans = shuffle_options_with_answer(rng, labels[:], answer_label)
        sink.add("T008", "当前图像中可见物体类别数量属于哪个区间？", ans, "single_choice", opts,
                 fields=["objects.category"], gt={"num_visible_categories": n})


def gen_T011_T012_T013_T014_T015_T020(sink: ItemSink, rng: random.Random, objs: List[Obj],
                                      present: List[str], absent: List[str], counts: Counter[str]) -> None:
    # T011 count one category, rewritten as interval selection.
    count_bins = [(0, 1, "0 个"), (1, 2, "1 个"), (2, 3, "2 个"), (3, 5, "3–4 个"), (5, float("inf"), "5 个及以上")]
    count_opts = as_options([b[2] for b in count_bins])
    for cat in rng.sample(present, min(len(present), sink.max_per_template)):
        ans_label = interval_label(counts[cat], count_bins)
        ans = answer_letter(count_opts, ans_label)
        sink.add("T011", f"当前图像中可见的 {cat} 数量属于哪个区间？", ans, "single_choice", count_opts,
                 fields=["objects.category"], gt={"category": cat, "count": counts[cat], "bin": ans_label})

    # T012 count comparison.
    cats = [c for c in present if counts[c] > 0]
    for a, b in choose_category_pairs(cats, counts, rng, sink.max_per_template * 3):
        if counts[a] == counts[b]:
            continue
        answer = "是" if counts[a] > counts[b] else "否"
        sink.add("T012", f"当前图像中 {a} 的可见数量是否多于 {b}？", answer, "yes_no", {"A": "是", "B": "否"},
                 fields=["objects.category"], gt={"category_A": a, "count_A": counts[a], "category_B": b, "count_B": counts[b]})

    # T013 most frequent category.
    if len(counts) >= 2:
        sorted_counts = counts.most_common()
        if len(sorted_counts) == 1 or sorted_counts[0][1] != sorted_counts[1][1]:
            best = sorted_counts[0][0]
            labels = [best] + [c for c, _ in sorted_counts[1:4]]
            opts, ans = shuffle_options_with_answer(rng, labels, best)
            sink.add("T013", "当前图像中哪类物体的可见实例数量最多？", ans, "single_choice", opts,
                     fields=["objects.category"], gt={"category_counts": dict(counts), "answer_category": best})

    # T014 sort candidate categories by count.
    if len(cats) >= 4:
        for _ in range(sink.max_per_template):
            cand = rng.sample(cats, 4)
            vals = [(c, counts[c]) for c in cand]
            if len({v for _, v in vals}) < 4:
                continue
            answer = [c for c, _ in sorted(vals, key=lambda kv: kv[1], reverse=True)]
            opts = as_options(cand)
            sink.add("T014", "将候选物体类别按当前图像中的可见数量从多到少排序。请输出类别名称列表。", answer, "ordered_list", opts,
                     fields=["objects.category"], gt={"candidate_counts": dict(vals)})

    # T015 total visible object count interval.
    n = sum(counts.values())
    labels = ["0–5", "6–20", "21–50", "51–100", "大于 100"]
    answer_label = total_count_interval(n)
    opts, ans = shuffle_options_with_answer(rng, labels[:], answer_label)
    sink.add("T015", "当前图像中可见物体实例总数属于哪个区间？", ans, "single_choice", opts,
             fields=["objects.category"], gt={"num_visible_objects": n})

    # T020 JSON counts.
    if len(cats) >= 2:
        for _ in range(sink.max_per_template):
            chosen = rng.sample(cats, min(5, len(cats)))
            answer = {c: counts[c] for c in chosen}
            sink.add("T020", "请输出每个候选类别在当前图像中的可见实例数量，格式为 JSON 对象。", answer, "json", as_options(chosen),
                     fields=["objects.category"], gt={"candidate_counts": answer})


def choose_category_pairs(cats: List[str], counts: Counter[str], rng: random.Random, n: int) -> Iterable[Tuple[str, str]]:
    if len(cats) < 2:
        return []
    out = []
    for _ in range(n):
        out.append(tuple(rng.sample(cats, 2)))
    return out


def gen_T021_to_T035(sink: ItemSink, rng: random.Random, objs: List[Obj], image_size: Tuple[int, int], args: argparse.Namespace) -> None:
    if len(objs) < 2:
        return
    width, height = image_size
    x_margin = width * args.xy_margin_frac
    y_margin = height * args.xy_margin_frac

    # Pairwise left/right/up/down.
    for a, b in choose_pairs(objs, rng, 800):
        if abs(a.cx - b.cx) >= x_margin:
            ans_left = "是" if a.cx < b.cx else "否"
            sink.add("T021", "在标注图中，物体 A 是否位于物体 B 的左侧？", ans_left, "yes_no", {"A": "是", "B": "否"},
                     [a, b], ["objects.bbox_2d.centroid_xy"], {"A_cx": a.cx, "B_cx": b.cx}, [a, b], ["A", "B"], {"margin_px": round(abs(a.cx - b.cx), 3)})
            ans_right = "是" if a.cx > b.cx else "否"
            sink.add("T022", "在标注图中，物体 A 是否位于物体 B 的右侧？", ans_right, "yes_no", {"A": "是", "B": "否"},
                     [a, b], ["objects.bbox_2d.centroid_xy"], {"A_cx": a.cx, "B_cx": b.cx}, [a, b], ["A", "B"], {"margin_px": round(abs(a.cx - b.cx), 3)})
        if abs(a.cy - b.cy) >= y_margin:
            ans_up = "是" if a.cy < b.cy else "否"
            sink.add("T023", "在标注图中，物体 A 是否位于物体 B 的上方？", ans_up, "yes_no", {"A": "是", "B": "否"},
                     [a, b], ["objects.bbox_2d.centroid_xy"], {"A_cy": a.cy, "B_cy": b.cy}, [a, b], ["A", "B"], {"margin_px": round(abs(a.cy - b.cy), 3)})
            ans_down = "是" if a.cy > b.cy else "否"
            sink.add("T024", "在标注图中，物体 A 是否位于物体 B 的下方？", ans_down, "yes_no", {"A": "是", "B": "否"},
                     [a, b], ["objects.bbox_2d.centroid_xy"], {"A_cy": a.cy, "B_cy": b.cy}, [a, b], ["A", "B"], {"margin_px": round(abs(a.cy - b.cy), 3)})
        if all(sink.count_by_template[t] >= sink.max_per_template for t in ["T021", "T022", "T023", "T024"]):
            break

    # Extremes and center among candidates.
    center = (width / 2.0, height / 2.0)
    extreme_templates = [
        ("T025", "哪个标注物体最靠近图像中心？", lambda o: math.hypot(o.cx - center[0], o.cy - center[1]), False),
        ("T026", "哪个标注物体位于图像最左侧？", lambda o: o.cx, False),
        ("T027", "哪个标注物体位于图像最右侧？", lambda o: o.cx, True),
        ("T028", "哪个标注物体位于图像最上方？", lambda o: o.cy, False),
        ("T029", "哪个标注物体位于图像最下方？", lambda o: o.cy, True),
    ]
    for tid, question, key_fn, reverse in extreme_templates:
        for _ in range(sink.max_per_template * 10):
            cand = choose_k(objs, rng, 4)
            if not cand:
                break
            vals = [(i, key_fn(o)) for i, o in enumerate(cand)]
            sorted_vals = sorted(vals, key=lambda kv: kv[1], reverse=reverse)
            if abs(sorted_vals[0][1] - sorted_vals[1][1]) < (x_margin if tid in {"T026", "T027"} else y_margin if tid in {"T028", "T029"} else min(width, height) * 0.03):
                continue
            ans = LETTERS[sorted_vals[0][0]]
            sink.add(tid, question, ans, "single_choice", {LETTERS[i]: cand[i].category for i in range(len(cand))},
                     cand, ["objects.bbox_2d.centroid_xy"], {"values": {LETTERS[i]: round(vals[i][1], 3) for i in range(len(cand))}},
                     cand, LETTERS[:len(cand)])

    # T030 / T031 grid.
    grid_options = {LETTERS[i]: lab for i, lab in enumerate(["左上", "上中", "右上", "左中", "中心", "右中", "左下", "下中", "右下"])}
    for o in rng.sample(objs, min(len(objs), sink.max_per_template * 2)):
        ans = answer_letter(grid_options, grid9(o))
        sink.add("T030", "标注图中的物体 A 位于图像九宫格的哪个区域？", ans, "single_choice", grid_options,
                 [o], ["objects.bbox_2d.centroid_normalized_xy"], {"grid9": grid9(o)}, [o], ["A"])
        sink.add("T031", "从候选区域中选择包含标注物体 A 中心点的区域。", ans, "single_choice", grid_options,
                 [o], ["objects.bbox_2d.centroid_normalized_xy"], {"grid9": grid9(o)}, [o], ["A"])

    # T032 bbox overlap. Use external bbox because exact SAM masks may not be mutually exclusive.
    for a, b in choose_pairs(objs, rng, 800):
        inter = bbox_intersection_area(a, b)
        if inter == 0 and bbox_gap(a, b) > min(width, height) * 0.08:
            ans = "否"
        elif inter > min(a.area, b.area) * 0.05:
            ans = "是"
        else:
            continue
        sink.add("T032", "在标注图中，物体 A 与物体 B 的可见外接框是否重叠？", ans, "yes_no", {"A": "是", "B": "否"},
                 [a, b], ["objects.bbox_2d.xyxy"], {"bbox_intersection_area": inter}, [a, b], ["A", "B"])
        if not sink.can_add("T032"):
            break

    # T033 adjacency/touch by bbox gap.
    for a, b in choose_pairs(objs, rng, 800):
        gap = bbox_gap(a, b)
        if gap <= min(width, height) * 0.015:
            ans = "是"
        elif gap >= min(width, height) * 0.08:
            ans = "否"
        else:
            continue
        sink.add("T033", "在标注图中，物体 A 与物体 B 是否相邻或接触？", ans, "yes_no", {"A": "是", "B": "否"},
                 [a, b], ["objects.bbox_2d.xyxy"], {"bbox_gap_px": round(gap, 3)}, [a, b], ["A", "B"])
        if not sink.can_add("T033"):
            break

    # T034 / T035 sorting.
    for tid, question, key_fn, field in [
        ("T034", "将候选标注物体按图像中从左到右排序。请输出选项字母列表。", lambda o: o.cx, "objects.bbox_2d.centroid_xy"),
        ("T035", "将候选标注物体按图像中从上到下排序。请输出选项字母列表。", lambda o: o.cy, "objects.bbox_2d.centroid_xy"),
    ]:
        for _ in range(sink.max_per_template * 10):
            cand = choose_k(objs, rng, 4)
            if not cand:
                break
            vals = [(LETTERS[i], key_fn(o)) for i, o in enumerate(cand)]
            sorted_vals = sorted(vals, key=lambda kv: kv[1])
            diffs = [abs(sorted_vals[i + 1][1] - sorted_vals[i][1]) for i in range(len(sorted_vals) - 1)]
            if min(diffs) < (x_margin if tid == "T034" else y_margin):
                continue
            answer = [k for k, _ in sorted_vals]
            sink.add(tid, question, answer, "ordered_list", {LETTERS[i]: cand[i].category for i in range(len(cand))},
                     cand, [field], {"values": {LETTERS[i]: round(key_fn(cand[i]), 3) for i in range(len(cand))}}, cand, LETTERS[:len(cand)])


def gen_T036_to_T045(sink: ItemSink, rng: random.Random, objs_depth: List[Obj], counts: Counter[str]) -> None:
    if len(objs_depth) < 2:
        return
    # Pairwise depth comparisons.
    for a, b in choose_pairs(objs_depth, rng, 800):
        if a.depth is None or b.depth is None or abs(a.depth - b.depth) < 0.35:
            continue
        ans = "是" if a.depth < b.depth else "否"
        fields = ["objects.depth_median", "objects.bbox_2d.xyxy"]
        gt = {"A_depth_median": a.depth, "B_depth_median": b.depth, "definition": "smaller depth_median = closer to camera"}
        sink.add("T036", "观察标注图，物体 A 是否比物体 B 更靠近相机？", ans, "yes_no", {"A": "是", "B": "否"},
                 [a, b], fields, gt, [a, b], ["A", "B"], {"depth_margin_m": round(abs(a.depth - b.depth), 3)})
        sink.add("T043", "观察标注图，物体 A 是否比物体 B 更靠近相机？", ans, "yes_no", {"A": "是", "B": "否"},
                 [a, b], fields, gt, [a, b], ["A", "B"], {"depth_margin_m": round(abs(a.depth - b.depth), 3)})
        if all(not sink.can_add(t) for t in ["T036", "T043"]):
            break

    # T037/T038 nearest/farthest, T039 sort.
    for tid, question, reverse in [
        ("T037", "哪个标注物体离相机最近？", False),
        ("T038", "哪个标注物体离相机最远？", True),
    ]:
        for _ in range(sink.max_per_template * 10):
            cand = choose_k(objs_depth, rng, 4)
            if not cand:
                break
            vals = [(i, cand[i].depth) for i in range(len(cand)) if cand[i].depth is not None]
            if len(vals) < 4:
                continue
            sorted_vals = sorted(vals, key=lambda kv: kv[1], reverse=reverse)
            if abs(sorted_vals[0][1] - sorted_vals[1][1]) < 0.35:
                continue
            ans = LETTERS[sorted_vals[0][0]]
            sink.add(tid, question, ans, "single_choice", {LETTERS[i]: cand[i].category for i in range(len(cand))},
                     cand, ["objects.depth_median"], {"depth_median_by_option": {LETTERS[i]: round(cand[i].depth, 4) for i in range(len(cand))}},
                     cand, LETTERS[:len(cand)])

    for _ in range(sink.max_per_template * 10):
        cand = choose_k(objs_depth, rng, 4)
        if not cand:
            break
        vals = [(LETTERS[i], cand[i].depth) for i in range(len(cand))]
        vals_sorted = sorted(vals, key=lambda kv: kv[1])
        if min(abs(vals_sorted[i + 1][1] - vals_sorted[i][1]) for i in range(3)) < 0.25:
            continue
        answer = [k for k, _ in vals_sorted]
        sink.add("T039", "将候选标注物体按从近到远排序。请输出选项字母列表。", answer, "ordered_list",
                 {LETTERS[i]: cand[i].category for i in range(len(cand))}, cand, ["objects.depth_median"],
                 {"depth_median_by_option": {LETTERS[i]: round(cand[i].depth, 4) for i in range(len(cand))}}, cand, LETTERS[:len(cand)])

    # T040 depth interval.
    for o in rng.sample(objs_depth, min(len(objs_depth), sink.max_per_template * 2)):
        lab = interval_label(float(o.depth), DEPTH_BINS)
        opts, ans = shuffle_options_with_answer(rng, [x[2] for x in DEPTH_BINS], lab)
        sink.add("T040", "观察标注图，标注物体 A 到相机的距离属于哪个区间？", ans, "single_choice", opts,
                 [o], ["objects.depth_median"], {"depth_median": o.depth}, [o], ["A"])

    # T041 category threshold existence.
    by_cat = defaultdict(list)
    for o in objs_depth:
        by_cat[o.category].append(o)
    thresholds = [2.0, 3.0, 4.0, 5.0, 8.0]
    for cat, cat_objs in list(by_cat.items()):
        for th in thresholds:
            answer = "是" if any(o.depth is not None and o.depth < th for o in cat_objs) else "否"
            sink.add("T041", f"当前图像中是否存在距离相机小于 {th:g} 米的 {cat}？", answer, "yes_no", {"A": "是", "B": "否"},
                     cat_objs[:10], ["objects.category", "objects.depth_median"],
                     {"category": cat, "threshold_m": th, "depths": [round(o.depth, 4) for o in cat_objs if o.depth is not None]})

    # T042 category-level median depth comparison.
    cats = [c for c, os in by_cat.items() if len(os) >= 1]
    for _ in range(sink.max_per_template * 8):
        if len(cats) < 2:
            break
        a, b = rng.sample(cats, 2)
        da = median([o.depth for o in by_cat[a] if o.depth is not None])
        db = median([o.depth for o in by_cat[b] if o.depth is not None])
        if da is None or db is None or abs(da - db) < 0.35:
            continue
        labels = [a, b]
        answer_label = a if da < db else b
        opts, ans = shuffle_options_with_answer(rng, labels, answer_label)
        sink.add("T042", f"哪类可见物体整体更靠近相机：{a} 还是 {b}？", ans, "single_choice", opts,
                 by_cat[a][:5] + by_cat[b][:5], ["objects.category", "objects.depth_median"],
                 {"category_A_median_depth": da, "category_B_median_depth": db, "answer_category": answer_label})

    # T045 nearest object category.
    nearest = min(objs_depth, key=lambda o: o.depth if o.depth is not None else float("inf"))
    sink.add("T045", f"当前图像中，距离相机最近的标注物体是否属于 {nearest.category}？", "是", "yes_no", {"A": "是", "B": "否"},
             [nearest], ["objects.category", "objects.depth_median"], {"nearest_object": obj_brief(nearest)})
    wrong_cats = [c for c in counts if c != nearest.category]
    if wrong_cats:
        wrong = rng.choice(wrong_cats)
        sink.add("T045", f"当前图像中，距离相机最近的标注物体是否属于 {wrong}？", "否", "yes_no", {"A": "是", "B": "否"},
                 [nearest], ["objects.category", "objects.depth_median"], {"nearest_object": obj_brief(nearest), "queried_category": wrong})


def median(vals: Sequence[Optional[float]]) -> Optional[float]:
    xs = sorted(float(v) for v in vals if v is not None and math.isfinite(float(v)))
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def gen_T056_T057_T060_T061_T063(sink: ItemSink, rng: random.Random, objs_xyz: List[Obj], objs_3d_size: List[Obj]) -> None:
    # T056 camera-coordinate 3D centroid distance interval.
    if len(objs_xyz) >= 2:
        for a, b in choose_pairs(objs_xyz, rng, 800):
            dist = pairwise_distance_xyz(a, b)
            if dist is None or dist < 0.15:
                continue
            lab = interval_label(dist, DIST_BINS)
            opts, ans = shuffle_options_with_answer(rng, [x[2] for x in DIST_BINS], lab)
            sink.add("T056", "在深度恢复的相机坐标下，标注物体 A 与物体 B 的三维质心距离属于哪个区间？", ans, "single_choice", opts,
                     [a, b], ["objects.centroid_3d.xyz"], {"distance_m": dist}, [a, b], ["A", "B"])
            if not sink.can_add("T056"):
                break

    # T057 closer to target C.
    if len(objs_xyz) >= 3:
        for _ in range(sink.max_per_template * 15):
            a, b, c = rng.sample(objs_xyz, 3)
            da = pairwise_distance_xyz(a, c)
            db = pairwise_distance_xyz(b, c)
            if da is None or db is None or abs(da - db) < 0.2:
                continue
            ans = "是" if da < db else "否"
            sink.add("T057", "在深度恢复的相机坐标下，标注物体 A 是否比标注物体 B 更靠近标注物体 C？", ans, "yes_no", {"A": "是", "B": "否"},
                     [a, b, c], ["objects.centroid_3d.xyz"], {"dist_A_C_m": da, "dist_B_C_m": db}, [a, b, c], ["A", "B", "C"])
            if not sink.can_add("T057"):
                break

    # T060/T061/T063 visible 3D bbox size.
    if len(objs_3d_size) >= 4:
        for tid, question, key_fn, field in [
            ("T060", "在候选标注物体中，哪个物体的可见 3D 包围盒体积最大？", lambda o: o.volume, "objects.rough_3d_bbox.size_xyz"),
            ("T061", "在候选标注物体中，哪个物体的可见 3D 包围盒 y 方向尺寸最大？", lambda o: o.height_like, "objects.rough_3d_bbox.size_xyz"),
        ]:
            for _ in range(sink.max_per_template * 10):
                cand = choose_k(objs_3d_size, rng, 4)
                if not cand:
                    break
                vals = [(i, key_fn(o)) for i, o in enumerate(cand)]
                if any(v is None for _, v in vals):
                    continue
                vals_sorted = sorted(vals, key=lambda kv: kv[1], reverse=True)
                if vals_sorted[1][1] <= 0 or vals_sorted[0][1] / vals_sorted[1][1] < 1.2:
                    continue
                ans = LETTERS[vals_sorted[0][0]]
                sink.add(tid, question, ans, "single_choice", {LETTERS[i]: cand[i].category for i in range(len(cand))},
                         cand, [field], {"values_by_option": {LETTERS[i]: round(key_fn(cand[i]), 6) for i in range(len(cand))}}, cand, LETTERS[:len(cand)],
                         {"note": "rough_3d_bbox is visible-surface AABB from monocular depth, not full CAD box"})

        for _ in range(sink.max_per_template * 10):
            cand = choose_k(objs_3d_size, rng, 4)
            if not cand:
                break
            vals = [(LETTERS[i], cand[i].volume) for i in range(len(cand))]
            vals_sorted = sorted(vals, key=lambda kv: kv[1], reverse=True)
            if any(v is None or v <= 0 for _, v in vals_sorted):
                continue
            if min(vals_sorted[i][1] / vals_sorted[i + 1][1] for i in range(len(vals_sorted) - 1)) < 1.1:
                continue
            answer = [k for k, _ in vals_sorted]
            sink.add("T063", "将候选标注物体按可见 3D 包围盒体积从大到小排序。请输出选项字母列表。", answer, "ordered_list",
                     {LETTERS[i]: cand[i].category for i in range(len(cand))}, cand, ["objects.rough_3d_bbox.size_xyz"],
                     {"volume_by_option": {LETTERS[i]: round(cand[i].volume, 6) for i in range(len(cand))}}, cand, LETTERS[:len(cand)],
                     {"note": "rough_3d_bbox is visible-surface AABB from monocular depth, not full CAD box"})


def gen_T082_T084_T090(sink: ItemSink, rng: random.Random, present: List[str], absent: List[str]) -> None:
    """Strict replacement for the old evidence-insufficient templates.

    T082/T084/T090 are hard-locked by DEPRECATED_LOCKED_TEMPLATES because they
    introduce unanswerable/meta-question behavior. This function now only emits
    T085 evidence-conflict items when T085 is enabled.
    """
    if not sink.can_add("T085") or not present:
        return
    options_text: List[str] = []
    true_cats = rng.sample(present, min(2, len(present)))
    for cat in true_cats:
        options_text.append(f"当前图像中可见 {cat}")
    if absent:
        wrong_cat = rng.choice(absent)
        conflict = f"当前图像中可见 {wrong_cat}"
    else:
        wrong_cat = rng.choice(present)
        conflict = f"当前图像中没有可见的 {wrong_cat}"
    labels = options_text + [conflict]
    rng.shuffle(labels)
    opts = as_options(labels)
    ans = answer_letter(opts, conflict)
    sink.add("T085", "下列哪一项与当前图像中的可见物体类别证据冲突？", ans, "single_choice", opts,
             fields=["objects.category"], gt={"visible_categories": present, "conflict_description": conflict})

def gen_T091_T095_T096_T097_T099_T100(sink: ItemSink, rng: random.Random, objs_depth: List[Obj], counts: Counter[str]) -> None:
    if len(objs_depth) < 2:
        return
    # T091 same GT as depth-layer frontness.
    for a, b in choose_pairs(objs_depth, rng, 800):
        if a.depth is None or b.depth is None or abs(a.depth - b.depth) < 0.35:
            continue
        ans = "是" if a.depth < b.depth else "否"
        sink.add("T091", "观察标注图，物体 A 是否比物体 B 更靠近相机？", ans, "yes_no", {"A": "是", "B": "否"},
                 [a, b], ["objects.depth_median"], {"A_depth_median": a.depth, "B_depth_median": b.depth}, [a, b], ["A", "B"])
        if not sink.can_add("T091"):
            break

    # T095 depth layer sort.
    for _ in range(sink.max_per_template * 10):
        cand = choose_k(objs_depth, rng, 4)
        if not cand:
            break
        vals = [(LETTERS[i], cand[i].depth) for i in range(len(cand))]
        vals_sorted = sorted(vals, key=lambda kv: kv[1])
        if min(abs(vals_sorted[i + 1][1] - vals_sorted[i][1]) for i in range(3)) < 0.25:
            continue
        answer = [k for k, _ in vals_sorted]
        sink.add("T095", "将候选标注物体按图像深度层次由前到后排序。请输出选项字母列表。", answer, "ordered_list",
                 {LETTERS[i]: cand[i].category for i in range(len(cand))}, cand, ["objects.depth_median"],
                 {"depth_median_by_option": {LETTERS[i]: round(cand[i].depth, 4) for i in range(len(cand))}}, cand, LETTERS[:len(cand)])

    by_cat = defaultdict(list)
    for o in objs_depth:
        by_cat[o.category].append(o)

    # T096 left side and nearest category.
    for cat, cat_objs in by_cat.items():
        left = [o for o in cat_objs if o.nx < 0.5 and o.depth is not None]
        if len(left) < 2:
            continue
        sorted_left = sorted(left, key=lambda o: o.depth)
        if sorted_left[1].depth - sorted_left[0].depth < 0.25:
            continue
        cand = sorted_left[:min(4, len(sorted_left))]
        answer_obj = cand[0]
        rng.shuffle(cand)
        ans = LETTERS[cand.index(answer_obj)]
        sink.add("T096", f"选择“图像左侧且距离相机最近的 {cat}”。", ans, "single_choice",
                 {LETTERS[i]: cand[i].category for i in range(len(cand))}, cand,
                 ["objects.category", "objects.bbox_2d.centroid_normalized_xy", "objects.depth_median"],
                 {"candidate_depths": {LETTERS[i]: cand[i].depth for i in range(len(cand))}, "answer_object_id": answer_obj.object_id},
                 cand, LETTERS[:len(cand)])

    # T097 right side and largest area.
    right = [o for o in objs_depth if o.nx > 0.5]
    if len(right) >= 4:
        for _ in range(sink.max_per_template * 10):
            cand = rng.sample(sorted(right, key=lambda o: o.area, reverse=True)[:max(20, min(len(right), 20))], 4)
            vals = [(i, cand[i].area) for i in range(4)]
            vals_sorted = sorted(vals, key=lambda kv: kv[1], reverse=True)
            if vals_sorted[1][1] <= 0 or vals_sorted[0][1] / vals_sorted[1][1] < 1.2:
                continue
            ans = LETTERS[vals_sorted[0][0]]
            sink.add("T097", "选择“图像右侧且可见面积最大的标注物体”。", ans, "single_choice",
                     {LETTERS[i]: cand[i].category for i in range(len(cand))}, cand,
                     ["objects.bbox_2d.centroid_normalized_xy", "objects.mask.area_px"],
                     {"area_by_option": {LETTERS[i]: cand[i].area for i in range(4)}}, cand, LETTERS[:4])

    # T099 matching attributes.
    for _ in range(sink.max_per_template * 10):
        cand = choose_k(objs_depth, rng, 4)
        if not cand:
            break
        left_obj = min(range(4), key=lambda i: cand[i].cx)
        right_obj = max(range(4), key=lambda i: cand[i].cx)
        near_obj = min(range(4), key=lambda i: cand[i].depth)
        far_obj = max(range(4), key=lambda i: cand[i].depth)
        if len({left_obj, right_obj, near_obj, far_obj}) < 3:
            continue
        answer = {
            "最靠左": LETTERS[left_obj],
            "最靠右": LETTERS[right_obj],
            "最近": LETTERS[near_obj],
            "最远": LETTERS[far_obj],
        }
        sink.add("T099", "将候选标注物体与空间属性进行匹配。请输出 JSON：{最靠左, 最靠右, 最近, 最远}。", answer, "json",
                 {LETTERS[i]: cand[i].category for i in range(4)}, cand,
                 ["objects.bbox_2d.centroid_xy", "objects.depth_median"],
                 {"centroid_depth_by_option": {LETTERS[i]: {"cx": cand[i].cx, "depth": cand[i].depth} for i in range(4)}}, cand, LETTERS[:4])

    # T100 output object list satisfying category + depth threshold.
    thresholds = [2.0, 3.0, 4.0, 5.0, 8.0]
    for cat, cat_objs in by_cat.items():
        if not cat_objs:
            continue
        th = rng.choice(thresholds)
        answer_ids = sorted([o.object_id for o in cat_objs if o.depth is not None and o.depth < th])
        sink.add("T100", f"输出满足条件的物体 ID 列表：可见、类别为 {cat}、depth_median 小于 {th:g} 米。请输出 JSON 数组。", answer_ids, "json_array",
                 fields=["objects.object_id", "objects.category", "objects.depth_median"],
                 gt={"category": cat, "threshold_m": th, "answer_object_ids": answer_ids})


def write_jsonl(items: Sequence[Dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_report(items: Sequence[Dict[str, Any]], output: Path, samples: Sequence[Sample]) -> None:
    by_t = Counter(item["template_id"] for item in items)
    by_cap = Counter(c for item in items for c in item.get("capability", []))
    report = {
        "num_samples": len(samples),
        "num_items": len(items),
        "items_by_template": dict(sorted(by_t.items())),
        "items_by_capability": dict(sorted(by_cap.items())),
        "notes": [
            "Only templates supported by available GT fields are generated.",
            "World-coordinate, ego-pose, temporal, navmesh, action-state, and traffic-rule templates are intentionally skipped unless those fields are added.",
            "Depth answers come from objects.depth_median / monocular depth export; treat them as dataset GT, not physical laser/LiDAR ground truth unless your upstream pipeline is calibrated.",
            "rough_3d_bbox is a visible-surface AABB derived from depth and masks; it is not a full-object CAD box.",
        ],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate BenchClaw unified static embodied-spatial VLM evaluation items from entity_annotations.json samples.")
    p.add_argument("--input", required=True, help="A sample folder, a .zip sample, or a parent folder containing many samples/zips.")
    p.add_argument("--output", required=True, help="Output JSONL path.")
    p.add_argument("--asset-dir", default=None, help="Directory for copied images and generated overlays. Default: <output_stem>_assets")
    p.add_argument("--report", default=None, help="Optional generation report JSON. Default: <output_stem>_report.json")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-per-template", type=int, default=8)
    p.add_argument("--template-set", choices=sorted(TEMPLATE_SETS), default="strict_core", help="Agent-safe template set. Default strict_core avoids unanswerable, raw numeric, hidden-metadata, and GT-leakage templates.")
    p.add_argument("--template-ids", default="", help="Optional comma-separated allowlist. Deprecated locked templates are still blocked.")
    p.add_argument("--min-conf", type=float, default=0.25)
    p.add_argument("--min-area", type=int, default=80)
    p.add_argument("--max-area-frac", type=float, default=0.35, help="Drop objects whose visible mask occupies more than this image fraction; set <=0 to disable.")
    p.add_argument("--xy-margin-frac", type=float, default=0.06, help="Minimum centroid separation for 2D relation questions, as fraction of image width/height.")
    p.add_argument("--require-valid", action=argparse.BooleanOptionalAction, default=True, help="Use valid_for_question_generation flag when present.")
    p.add_argument("--include-depth", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-3d", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--negative-categories", default=",".join(DEFAULT_NEGATIVE_CATEGORIES), help="Comma-separated absent-category distractor pool.")
    p.add_argument("--drop-categories", default="sky,cloud,clouds,road,ground,terrain,floor,ceiling,wall", help="Comma-separated categories to exclude from generation, e.g. sky,clouds,vegetation.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    if args.asset_dir is None:
        args.asset_dir = str(output.with_suffix("").parent / (output.with_suffix("").name + "_assets"))
    if args.report is None:
        args.report = str(output.with_suffix("").parent / (output.with_suffix("").name + "_report.json"))

    samples = discover_samples(Path(args.input))
    if not samples:
        raise SystemExit("No valid samples found.")
    all_items: List[Dict[str, Any]] = []
    for s in samples:
        items = generate_items_for_sample(s, args)
        all_items.extend(items)
        print(f"[info] {s.sample_id}: objects={len(s.objects)} items={len(items)}")
    if not all_items:
        raise SystemExit("No valid items generated; refusing successful empty output")
    write_jsonl(all_items, output)
    write_report(all_items, Path(args.report), samples)
    print(f"[done] wrote {len(all_items)} items -> {output}")
    print(f"[done] assets -> {args.asset_dir}")
    print(f"[done] report -> {args.report}")


if __name__ == "__main__":
    main()
