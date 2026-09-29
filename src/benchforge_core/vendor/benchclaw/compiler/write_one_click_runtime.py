#!/usr/bin/env python3
"""Write default one-click Stage4 runtime scripts into a data_20 bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence


AUDIT_EVALSET_SCRIPT = Path(__file__).with_name("audit_evalset_quality.py")
RAW_ONLY_ANCHORS = {"", "raw_rgb", "safe_rgb", "safe_copy", "natural_rgb", "rgb"}
PRIVATE_GT_FIELD_TOKENS = ("pose", "coordinate", "depth", "distance", "bbox", "mask", "area", "trajectory", "object_id", "scene_id", "frame_id")


DEFAULT_TEMPLATES = [
    {
        "template_id": "BC_D1_001_CATEGORY_VISIBLE_YN",
        "status": "enabled",
        "difficulty_level": "easy",
        "kinship_level": "single_field",
        "capability_tags": ["D1", "visible_category"],
        "answer_type": "yes_no",
        "metric_id": "accuracy",
        "requires_overlay": False,
        "required_evidence_fields": ["objects.category"],
        "reference_template_family": "T5",
        "gt_rule": "category in visible category set",
        "implementation_hint": "gen_category_visible_yn",
        "disable_reason": "",
    },
    {
        "template_id": "BC_D2_001_CATEGORY_COUNT_INTERVAL",
        "status": "enabled",
        "difficulty_level": "easy",
        "kinship_level": "single_field_count",
        "capability_tags": ["D2", "count_interval"],
        "answer_type": "interval_choice",
        "metric_id": "accuracy",
        "requires_overlay": False,
        "required_evidence_fields": ["objects.category"],
        "reference_template_family": "T5",
        "gt_rule": "count(category) mapped to fixed interval bins",
        "implementation_hint": "gen_category_count_interval",
        "disable_reason": "",
    },
    {
        "template_id": "BC_D3_001_LEFT_OF_YN",
        "status": "enabled",
        "difficulty_level": "medium",
        "kinship_level": "pair_spatial",
        "capability_tags": ["D3", "spatial_left_right"],
        "answer_type": "yes_no",
        "metric_id": "accuracy",
        "requires_overlay": True,
        "visual_marker_policy": {"required": True, "marker_type": "bbox_or_point", "labels": ["A", "B"], "question_must_reference_labels": True},
        "required_evidence_fields": ["objects.bbox_2d.centroid_xy"],
        "reference_template_family": "T1",
        "gt_rule": "A.cx < B.cx with margin",
        "implementation_hint": "gen_left_of_yn",
        "disable_reason": "",
    },
    {
        "template_id": "BC_D3_002_ABOVE_YN",
        "status": "enabled",
        "difficulty_level": "medium",
        "kinship_level": "pair_spatial",
        "capability_tags": ["D3", "spatial_up_down"],
        "answer_type": "yes_no",
        "metric_id": "accuracy",
        "requires_overlay": True,
        "visual_marker_policy": {"required": True, "marker_type": "bbox_or_point", "labels": ["A", "B"], "question_must_reference_labels": True},
        "required_evidence_fields": ["objects.bbox_2d.centroid_xy"],
        "reference_template_family": "T1",
        "gt_rule": "A.cy < B.cy with margin",
        "implementation_hint": "gen_above_yn",
        "disable_reason": "",
    },
    {
        "template_id": "BC_D3_005_LEFT_TO_RIGHT_ORDER",
        "status": "enabled",
        "difficulty_level": "hard",
        "kinship_level": "multi_object_order",
        "capability_tags": ["D3", "spatial_ordering"],
        "answer_type": "ordered_list",
        "metric_id": "order_exact_accuracy",
        "requires_overlay": True,
        "visual_marker_policy": {"required": True, "marker_type": "bbox_or_point", "labels": ["A", "B", "C", "D"], "question_must_reference_labels": True},
        "required_evidence_fields": ["objects.bbox_2d.centroid_xy"],
        "reference_template_family": "T7",
        "gt_rule": "sort candidate labels by cx ascending with no near-ties",
        "implementation_hint": "gen_left_to_right_order",
        "disable_reason": "",
    },
    {
        "template_id": "BC_D4_001_LARGEST_VISIBLE_AREA",
        "status": "enabled",
        "difficulty_level": "medium",
        "kinship_level": "multi_object_area",
        "capability_tags": ["D4", "area_compare"],
        "answer_type": "single_choice",
        "metric_id": "accuracy",
        "requires_overlay": True,
        "visual_marker_policy": {"required": True, "marker_type": "bbox_or_point", "labels": ["A", "B", "C", "D"], "question_must_reference_labels": True},
        "required_evidence_fields": ["objects.mask.area_px|objects.bbox_2d.xyxy"],
        "reference_template_family": "T7",
        "gt_rule": "maximum visible area among candidates with margin",
        "implementation_hint": "gen_largest_visible_area",
        "disable_reason": "",
    },
    {
        "template_id": "BC_D5_001_CLOSER_TO_CAMERA_YN",
        "status": "enabled",
        "difficulty_level": "hard",
        "kinship_level": "pair_depth",
        "capability_tags": ["D5", "depth_relation"],
        "answer_type": "yes_no",
        "metric_id": "accuracy",
        "requires_overlay": True,
        "visual_marker_policy": {"required": True, "marker_type": "bbox_or_point", "labels": ["A", "B"], "question_must_reference_labels": True},
        "required_evidence_fields": ["objects.depth_median"],
        "reference_template_family": "T7",
        "gt_rule": "A.depth < B.depth with margin",
        "implementation_hint": "gen_closer_to_camera_yn",
        "disable_reason": "",
    },
    {
        "template_id": "BC_SIM_001_SCENE_TYPE",
        "status": "enabled",
        "difficulty_level": "easy",
        "kinship_level": "single_frame_visual",
        "capability_tags": ["D1", "scene_understanding"],
        "answer_type": "single_choice",
        "metric_id": "accuracy",
        "requires_overlay": False,
        "required_evidence_fields": ["scene_type"],
        "reference_template_family": "frame_scene_type",
        "gt_rule": "scene type label derived from simulator/evidence metadata and checked against RGB view",
        "implementation_hint": "gen_frame_scene_type",
        "disable_reason": "",
    },
    {
        "template_id": "BC_SIM_002_DEPTH_BAND",
        "status": "enabled",
        "difficulty_level": "hard",
        "kinship_level": "rgb_depth_pair",
        "capability_tags": ["D5", "depth_perception"],
        "answer_type": "single_choice",
        "metric_id": "accuracy",
        "requires_overlay": False,
        "required_evidence_fields": ["depth_path"],
        "private_gt_fields_used": ["depth"],
        "required_visible_transform": "rgb_depth_panel",
        "reference_template_family": "frame_depth_visualization",
        "gt_rule": "depth image statistics mapped to coarse near/medium/far band and rendered as RGB-depth panel",
        "implementation_hint": "gen_frame_depth_band",
        "disable_reason": "",
    },
    {
        "template_id": "BC_SIM_003_POSE_ORIENTATION",
        "status": "enabled",
        "difficulty_level": "medium",
        "kinship_level": "pose_map",
        "capability_tags": ["D3", "pose_reasoning"],
        "answer_type": "single_choice",
        "metric_id": "accuracy",
        "requires_overlay": False,
        "required_evidence_fields": ["agent_position", "agent_rotation|viewing_direction"],
        "private_gt_fields_used": ["pose", "coordinate"],
        "required_visible_transform": "pose_map_overlay",
        "reference_template_family": "frame_pose_map",
        "gt_rule": "camera heading is rendered as a neutral arrow on a local map panel",
        "implementation_hint": "gen_frame_pose_orientation",
        "disable_reason": "",
    },
]


GEN_GENERATE_ITEMS = r'''#!/usr/bin/env python3
"""Default strict BenchClaw Stage4 item generator.

This generated runtime is intentionally small and deterministic. Dataset-specific
answer-program-generation may replace it with a richer thin adapter, but this
default already supports the Stage4 public CLI and core static VLM templates.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except Exception:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
    ImageOps = None  # type: ignore


LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
FORBIDDEN_QUESTION_TERMS = (
    "object_id", "bbox", "mask.area", "depth_median", "metadata", "annotation",
    "evidence_index", "GT", "ground truth", "字段", "无法判断", "信息不足", "不能确定",
)
INCOMPLETE_OPTION_RE = re.compile(r"(\bto the (?:left|right) of|\bin front of|\bbehind)$", re.I)
COUNT_BINS = [(0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 4, "3-4"), (5, 8, "5-8"), (9, math.inf, "9及以上")]
RAW_ONLY_ANCHORS = {"", "raw_rgb", "safe_rgb", "safe_copy", "natural_rgb", "rgb", "processed_rgb", "direct_copy"}
PRIVATE_GT_FIELD_TOKENS = ("pose", "coordinate", "depth", "distance", "bbox", "mask", "area", "trajectory", "object_id", "scene_id", "frame_id")


@dataclass(frozen=True)
class Obj:
    object_id: str
    category: str
    bbox: Tuple[int, int, int, int]
    cx: float
    cy: float
    area: int
    depth: Optional[float]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_name(text: Any) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(text or "")).strip("_") or "item"


def stable_hash(text: str) -> int:
    value = 2166136261
    for ch in text:
        value ^= ord(ch)
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_present(record: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    lowered = {str(k).lower(): k for k in record}
    for key in keys:
        actual = lowered.get(key.lower())
        if actual is not None:
            return record.get(actual)
    return default


def parse_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_bbox(value: Any) -> Optional[Tuple[int, int, int, int]]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            x1, y1, x2, y2 = [int(round(float(x))) for x in value]
        except Exception:
            return None
        return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None
    if not isinstance(value, dict):
        return None
    if "xyxy" in value:
        return parse_bbox(value.get("xyxy"))
    if {"xmin", "ymin", "xmax", "ymax"} <= set(value):
        return parse_bbox([value["xmin"], value["ymin"], value["xmax"], value["ymax"]])
    if {"x1", "y1", "x2", "y2"} <= set(value):
        return parse_bbox([value["x1"], value["y1"], value["x2"], value["y2"]])
    if {"x", "y", "w", "h"} <= set(value):
        return parse_bbox([value["x"], value["y"], float(value["x"]) + float(value["w"]), float(value["y"]) + float(value["h"])])
    return None


def extract_objects(record: Dict[str, Any]) -> List[Obj]:
    raw_objects: List[Dict[str, Any]] = []
    for key in ("objects", "visible_objects", "candidate_objects", "annotations"):
        value = record.get(key)
        if isinstance(value, list):
            raw_objects = [obj for obj in value if isinstance(obj, dict)]
            break
    if not raw_objects and isinstance(record.get("gt_summary"), dict):
        value = record["gt_summary"].get("objects") or record["gt_summary"].get("visible_actors")
        if isinstance(value, list):
            raw_objects = [obj for obj in value if isinstance(obj, dict)]
    out: List[Obj] = []
    for idx, raw in enumerate(raw_objects):
        category = str(first_present(raw, ("category", "class", "label", "name"), "") or "").strip()
        if not category:
            continue
        bbox = None
        for key in ("bbox_xyxy", "bbox", "bbox2d", "bbox_2d", "box"):
            bbox = parse_bbox(raw.get(key))
            if bbox:
                break
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox
        centroid = first_present(raw, ("centroid_xy", "center", "center_xy"), None)
        if isinstance(centroid, (list, tuple)) and len(centroid) >= 2:
            cx, cy = float(centroid[0]), float(centroid[1])
        else:
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        area_raw = raw.get("area_px")
        if area_raw is None and isinstance(raw.get("mask"), dict):
            area_raw = raw["mask"].get("area_px")
        area = int(parse_float(area_raw) or max(1, (x2 - x1) * (y2 - y1)))
        depth = parse_float(first_present(raw, ("depth_median", "depth", "distance"), None))
        out.append(Obj(str(first_present(raw, ("object_id", "id", "instance_id"), idx)), category, bbox, cx, cy, area, depth))
    return out


def record_id(record: Dict[str, Any], idx: int) -> str:
    return str(record.get("sample_id") or record.get("record_id") or record.get("item_id") or record.get("id") or f"record_{idx:06d}")


def resolve_path(path_text: Any, bundle: Path, evidence_path: Path, record: Dict[str, Any]) -> Optional[Path]:
    text = str(path_text or "").strip()
    if not text or text.startswith(("http://", "https://", "file://", "data:")):
        return None
    path = Path(text).expanduser()
    roots = [bundle, bundle.parent, evidence_path.parent, Path(str(record.get("root_dir") or evidence_path.parent)).expanduser(), Path.cwd()]
    candidates = [path] if path.is_absolute() else [root / path for root in roots]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved.is_file():
            return resolved
    return None


def raw_image_path(record: Dict[str, Any]) -> Any:
    for key in ("image_path", "rgb_path", "image", "workspace_image", "file_path"):
        if record.get(key):
            return record.get(key)
    media = record.get("media")
    if isinstance(media, str):
        return media
    if isinstance(media, dict):
        return media.get("path") or media.get("image_path") or media.get("rgb_path")
    if isinstance(media, list) and media:
        first = media[0]
        if isinstance(first, dict):
            return first.get("path") or first.get("image_path")
        return first
    return ""


def record_depth_path(record: Dict[str, Any]) -> Any:
    for key in ("depth_path", "depth_image", "workspace_depth"):
        if record.get(key):
            return record.get(key)
    return ""


def record_heading(record: Dict[str, Any]) -> str:
    return str(record.get("viewing_direction") or record.get("heading") or record.get("orientation") or "").strip().lower()


def scene_type_label(value: Any) -> str:
    text = str(value or "").strip().replace("_", " ")
    if not text:
        return ""
    return text


def estimate_depth_band(depth_path: Any, bundle: Path, evidence_path: Path, record: Dict[str, Any]) -> str:
    path = resolve_path(depth_path, bundle, evidence_path, record)
    if not path or Image is None or ImageOps is None:
        return ""
    try:
        with Image.open(path) as img:
            gray = ImageOps.exif_transpose(img).convert("L")
            pixels = list(gray.resize((64, 64)).getdata())
    except Exception:
        return ""
    if not pixels:
        return ""
    pixels = sorted(int(p) for p in pixels)
    median = pixels[len(pixels) // 2]
    if median <= 85:
        return "near"
    if median <= 170:
        return "medium"
    return "far"


def load_image_manifest(bundle: Path) -> Dict[str, List[Dict[str, Any]]]:
    by_sample: Dict[str, List[Dict[str, Any]]] = {}
    for row in load_jsonl(bundle / "image_processing" / "image_manifest.jsonl"):
        if str(row.get("status") or "accepted") != "accepted":
            continue
        sample_id = str(row.get("sample_id") or "")
        by_sample.setdefault(sample_id, []).append(row)
    return by_sample


def manifest_path(row: Dict[str, Any], bundle: Path) -> Optional[Path]:
    text = str(row.get("model_input_path") or row.get("path") or "")
    if not text:
        return None
    path = Path(text)
    candidates = [path] if path.is_absolute() else [bundle.parent / path, bundle / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def anchor_type(row: Dict[str, Any]) -> str:
    support = row.get("answerability_support") if isinstance(row.get("answerability_support"), dict) else {}
    return str(row.get("composer") or row.get("visible_asset_type") or support.get("anchor_type") or "").strip().lower()


def manifest_private_fields(row: Dict[str, Any]) -> set:
    support = row.get("answerability_support") if isinstance(row.get("answerability_support"), dict) else {}
    fields = support.get("supports_private_gt_fields") or row.get("supports_private_gt_fields") or []
    if isinstance(fields, str):
        fields = [fields]
    return {str(field).lower() for field in fields if str(field).strip()}


def template_private_fields(template: Dict[str, Any]) -> set:
    fields = list(template.get("private_gt_fields_used") or [])
    required = [str(value).lower() for value in template.get("required_evidence_fields", [])]
    fields.extend(value for value in required if any(token in value for token in PRIVATE_GT_FIELD_TOKENS))
    return {str(field).lower() for field in fields if str(field).strip()}


def manifest_score(row: Dict[str, Any], template: Optional[Dict[str, Any]]) -> int:
    atype = anchor_type(row)
    # The spatial generators draw their own selected A/B/... markers. Start from
    # the clean RGB copy so unused markers from the generic preview cannot leak in.
    if template and template.get("requires_overlay"):
        return 1000 if atype in {"safe_copy", "processed_rgb", "safe_rgb", "rgb"} else -1000
    score = 0
    if atype in {"bbox_label_overlay", "point_label_overlay", "candidate_panel"}:
        score += 80
    elif atype in {"rgb_depth_panel", "depth_visualization", "rgb_depth_pair"}:
        score += 70
    elif atype in {"pose_map_overlay", "trajectory_panel"}:
        score += 65
    elif atype in {"safe_copy", "processed_rgb", "safe_rgb", "rgb"}:
        score += 10
    else:
        score += 30
    if template:
        private = template_private_fields(template)
        supported = manifest_private_fields(row)
        if private:
            if private & supported:
                score += 100
            if atype in RAW_ONLY_ANCHORS or atype in {"processed_rgb"}:
                score -= 200
        if template.get("requires_overlay") and atype not in {"bbox_label_overlay", "point_label_overlay", "candidate_panel"}:
            score -= 200
    return score


def manifest_anchor_for_record(record: Dict[str, Any], idx: int, bundle: Path, evidence_path: Path, image_manifest: Dict[str, List[Dict[str, Any]]], template: Optional[Dict[str, Any]], allow_raw_fallback: bool = False) -> Tuple[Optional[Path], str]:
    sample_id = record_id(record, idx)
    candidates = sorted(image_manifest.get(sample_id, []), key=lambda row: manifest_score(row, template), reverse=True)
    for row in candidates:
        path = manifest_path(row, bundle)
        if path:
            return path, anchor_type(row) or "processed_rgb"
    if not allow_raw_fallback:
        return None, ""
    return resolve_path(raw_image_path(record), bundle, evidence_path, record), "raw_rgb"


def image_for_record(record: Dict[str, Any], idx: int, bundle: Path, evidence_path: Path, image_manifest: Dict[str, List[Dict[str, Any]]], template: Optional[Dict[str, Any]] = None, allow_raw_fallback: bool = False) -> Optional[Path]:
    path, _anchor = manifest_anchor_for_record(record, idx, bundle, evidence_path, image_manifest, template, allow_raw_fallback)
    return path


def ensure_rgb(path: Path):
    if Image is None or ImageOps is None:
        return None
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")


def make_overlay(source: Path, objs: Sequence[Obj], labels: Sequence[str], out_path: Path) -> Optional[Path]:
    if Image is None or ImageDraw is None or ImageFont is None:
        return None
    image = ensure_rgb(source)
    if image is None:
        return None
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
    except Exception:
        font = ImageFont.load_default()
    colors = ["#D62828", "#1D4ED8", "#2A9D8F", "#F4A261", "#6D28D9", "#111827"]
    for idx, obj in enumerate(objs):
        x1, y1, x2, y2 = obj.bbox
        color = colors[idx % len(colors)]
        label = labels[idx]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
        text_box = draw.textbbox((x1, y1), label, font=font)
        tw, th = text_box[2] - text_box[0], text_box[3] - text_box[1]
        top = max(0, y1 - th - 8)
        draw.rectangle([x1, top, x1 + tw + 10, top + th + 8], fill=color)
        draw.text((x1 + 5, top + 3), label, fill="white", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=92)
    return out_path


def interval_label(value: int) -> str:
    for lo, hi, label in COUNT_BINS:
        if lo <= value <= hi:
            return label
    return COUNT_BINS[-1][2]


def as_options(labels: Sequence[str]) -> Dict[str, str]:
    return {LETTERS[i]: labels[i] for i in range(len(labels))}


def answer_for_option(options: Dict[str, str], value: str) -> str:
    for key, option_value in options.items():
        if option_value == value:
            return key
    raise ValueError(value)


def normalized_option_surface(value: str) -> str:
    text = str(value).casefold().strip()
    text = re.sub(r"\bthe target\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def marker_labels_referenced(question: str, options: Dict[str, str], labels: Sequence[str]) -> bool:
    haystack = " ".join([question, *options.values()])
    for label in labels:
        token = re.escape(str(label))
        if not re.search(rf"(?<![A-Za-z0-9]){token}(?![A-Za-z0-9])", haystack):
            return False
    return True


def validate_item(item: Dict[str, Any]) -> None:
    for key in ("item_id", "media", "question", "options", "answer", "answer_type", "template_id", "metric_id", "difficulty_level", "answerability_proof"):
        if item.get(key) in (None, "", [], {}):
            raise ValueError(f"missing {key}")
    question = str(item["question"])
    for term in FORBIDDEN_QUESTION_TERMS:
        if term in question:
            raise ValueError(f"forbidden question term {term}")
    values = list(item.get("options", {}).values())
    if len(values) != len(set(values)):
        raise ValueError("duplicated option text")
    normalized_values = [normalized_option_surface(value) for value in values]
    if len(normalized_values) != len(set(normalized_values)):
        raise ValueError("normalized duplicate option text")
    incomplete_keys = [key for key, value in item.get("options", {}).items() if INCOMPLETE_OPTION_RE.search(str(value).strip())]
    if incomplete_keys:
        raise ValueError(f"incomplete option text: {incomplete_keys}")
    answer = item["answer"]
    option_keys = set(item["options"])
    if isinstance(answer, list):
        if any(a not in option_keys for a in answer):
            raise ValueError("answer list not in options")
    elif answer not in option_keys:
        raise ValueError("answer not in options")
    elif INCOMPLETE_OPTION_RE.search(str(item["options"].get(answer, "")).strip()):
        raise ValueError("gold answer points to incomplete option text")
    proof = item.get("answerability_proof") or {}
    anchor_type = str(proof.get("visible_anchor_type") or proof.get("anchor_type") or "").lower()
    private_fields = [str(value).lower() for value in proof.get("private_gt_fields_used_for_answer", []) if str(value).strip()]
    if private_fields and anchor_type in RAW_ONLY_ANCHORS:
        raise ValueError("private-GT item lacks a non-raw visible transform")


class Sink:
    def __init__(self, bundle: Path, image_path: Path, sample_id: str, seed: int, anchor_type: str = "") -> None:
        self.bundle = bundle
        self.image_path = image_path
        self.sample_id = sample_id
        self.anchor_type = anchor_type
        self.rng = random.Random(seed + stable_hash(sample_id))
        self.items: List[Dict[str, Any]] = []
        self.filtered: List[Dict[str, Any]] = []
        self.overlay_dir = bundle / "generated_media" / safe_name(sample_id)
        self.seen = set()

    def add(self, *, template: Dict[str, Any], question: str, answer: Any, answer_type: str, options: Dict[str, str], objects: Sequence[Obj], evidence: Dict[str, Any], media_path: Optional[Path] = None, gt_values: Optional[Dict[str, Any]] = None) -> bool:
        signature = json.dumps([template["template_id"], question, answer, options, [o.object_id for o in objects]], ensure_ascii=False, sort_keys=True)
        if signature in self.seen:
            return False
        self.seen.add(signature)
        item_id = f"{safe_name(self.sample_id)}_{template['template_id']}_{len(self.items)+1:04d}"
        anchor_labels = LETTERS[: len(objects)]
        if template.get("requires_overlay"):
            if media_path is None or Path(media_path).resolve() == self.image_path.resolve():
                raise ValueError("requires_overlay template did not produce a processed marker image")
            if objects and not marker_labels_referenced(question, options, anchor_labels):
                raise ValueError("requires_overlay template does not reference visual marker labels in question/options")
        path = media_path or self.image_path
        private_fields = list(template.get("private_gt_fields_used") or [])
        if not private_fields:
            required_fields = [str(value).lower() for value in template.get("required_evidence_fields", [])]
            private_fields = [value for value in required_fields if any(token in value for token in PRIVATE_GT_FIELD_TOKENS)]
        anchor_type = str(
            template.get("required_visible_transform")
            or template.get("visible_anchor_source")
            or ("bbox_label_overlay" if template.get("requires_overlay") else self.anchor_type or "safe_rgb")
        )
        answerability_proof = {
            "visible_media": [str(path)],
            "visible_anchor_type": anchor_type,
            "question_references_visible_anchor": True,
            "private_gt_fields_used_for_answer": private_fields,
            "why_visible_anchor_is_sufficient": template.get("gt_rule") or "deterministic answer rule over visible anchored evidence",
        }
        item = {
            "item_id": item_id,
            "id": item_id,
            "sample_id": self.sample_id,
            "source": evidence.get("source_name", evidence.get("scene", "unspecified")),
            "media": [str(path)],
            "image": str(path),
            "source_media": [str(self.image_path)],
            "question": question,
            "options": options,
            "answer": answer,
            "answer_type": answer_type,
            "metric_id": template["metric_id"],
            "template_id": template["template_id"],
            "capability_tags": template.get("capability_tags") or [],
            "difficulty_level": template.get("difficulty_level") or "easy",
            "question_format": answer_type,
            "evidence_refs": [str(evidence.get("record_id") or evidence.get("sample_id") or self.sample_id)],
            "answerability_proof": answerability_proof,
            "metadata": {
                "difficulty_level": template.get("difficulty_level") or "easy",
                "template_gt_rule": template.get("gt_rule"),
                "objects": [
                    {
                        "visual_label": anchor_labels[idx] if idx < len(anchor_labels) else "",
                        "object_id": obj.object_id,
                        "category": obj.category,
                        "bbox_xyxy": list(obj.bbox),
                        "centroid_xy": [round(obj.cx, 3), round(obj.cy, 3)],
                        "area_px": obj.area,
                        "depth": obj.depth,
                    }
                    for idx, obj in enumerate(objects)
                ],
                "question_anchor_policy": {
                    "requires_processed_marker_image": bool(template.get("requires_overlay")),
                    "marker_labels": anchor_labels,
                    "model_visible_reference": anchor_type,
                },
                "answerability_proof": answerability_proof,
                "gt_values": gt_values or {},
            },
        }
        validate_item(item)
        self.items.append(item)
        return True

    def overlay(self, template_id: str, objs: Sequence[Obj], labels: Sequence[str]) -> Optional[Path]:
        return make_overlay(self.image_path, objs, labels, self.overlay_dir / f"{template_id}_{len(self.items)+1:04d}.jpg")


def pick_pair(objs: Sequence[Obj], rng: random.Random, axis: str, margin: float) -> Optional[Tuple[Obj, Obj]]:
    if len(objs) < 2:
        return None
    pool = list(objs)
    for _ in range(200):
        a, b = rng.sample(pool, 2)
        delta = abs((a.cx - b.cx) if axis == "x" else (a.cy - b.cy))
        if delta >= margin:
            return a, b
    return None


def pick_k(objs: Sequence[Obj], rng: random.Random, k: int) -> Optional[List[Obj]]:
    if len(objs) < k:
        return None
    pool = sorted(objs, key=lambda o: (o.area, o.category), reverse=True)[: max(k, min(len(objs), k * 6))]
    return rng.sample(pool, k)


def gen_category_visible_yn(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    counts = Counter(o.category for o in objs)
    if not counts:
        return
    category = sink.rng.choice(sorted(counts))
    sink.add(template=template, question=f"当前图像中是否可见 {category}？", answer="A", answer_type="yes_no", options={"A": "是", "B": "否"}, objects=[], evidence=record, gt_values={"category": category, "present": True})


def gen_category_count_interval(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    counts = Counter(o.category for o in objs)
    if not counts:
        return
    category = sink.rng.choice(sorted(counts))
    label = interval_label(counts[category])
    labels = [row[2] for row in COUNT_BINS]
    sink.rng.shuffle(labels)
    options = as_options(labels)
    sink.add(template=template, question=f"当前图像中可见的 {category} 数量属于哪个区间？", answer=answer_for_option(options, label), answer_type="interval_choice", options=options, objects=[], evidence=record, gt_values={"category": category, "count": counts[category], "interval": label})


def gen_left_of_yn(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    pair = pick_pair(objs, sink.rng, "x", 20.0)
    if not pair:
        return
    a, b = pair
    media = sink.overlay(template["template_id"], [a, b], ["A", "B"])
    answer = "A" if a.cx < b.cx else "B"
    sink.add(template=template, question="在标注图中，标注物体 A 是否位于标注物体 B 的左侧？", answer=answer, answer_type="yes_no", options={"A": "是", "B": "否"}, objects=[a, b], evidence=record, media_path=media, gt_values={"A_cx": a.cx, "B_cx": b.cx})


def gen_above_yn(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    pair = pick_pair(objs, sink.rng, "y", 20.0)
    if not pair:
        return
    a, b = pair
    media = sink.overlay(template["template_id"], [a, b], ["A", "B"])
    answer = "A" if a.cy < b.cy else "B"
    sink.add(template=template, question="在标注图中，标注物体 A 是否位于标注物体 B 的上方？", answer=answer, answer_type="yes_no", options={"A": "是", "B": "否"}, objects=[a, b], evidence=record, media_path=media, gt_values={"A_cy": a.cy, "B_cy": b.cy})


def gen_left_to_right_order(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    cand = pick_k(objs, sink.rng, min(4, len(objs)))
    if not cand or len(cand) < 3:
        return
    ordered = sorted([(LETTERS[i], obj.cx) for i, obj in enumerate(cand)], key=lambda x: x[1])
    if min(ordered[i+1][1] - ordered[i][1] for i in range(len(ordered)-1)) < 12:
        return
    media = sink.overlay(template["template_id"], cand, LETTERS[:len(cand)])
    sink.add(template=template, question="将候选标注物体按图像中从左到右排序。", answer=[k for k, _ in ordered], answer_type="ordered_list", options={LETTERS[i]: f"标注物体 {LETTERS[i]}" for i in range(len(cand))}, objects=cand, evidence=record, media_path=media, gt_values={"cx_by_option": {LETTERS[i]: cand[i].cx for i in range(len(cand))}})


def gen_largest_visible_area(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    cand = pick_k([o for o in objs if o.area > 0], sink.rng, min(4, len(objs)))
    if not cand or len(cand) < 2:
        return
    ranked = sorted([(LETTERS[i], obj.area) for i, obj in enumerate(cand)], key=lambda x: x[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] / max(1, ranked[1][1]) < 1.10:
        return
    media = sink.overlay(template["template_id"], cand, LETTERS[:len(cand)])
    sink.add(template=template, question="在候选标注物体中，哪个在图像中的可见面积最大？", answer=ranked[0][0], answer_type="single_choice", options={LETTERS[i]: f"标注物体 {LETTERS[i]}" for i in range(len(cand))}, objects=cand, evidence=record, media_path=media, gt_values={"area_by_option": {LETTERS[i]: cand[i].area for i in range(len(cand))}})


def gen_closer_to_camera_yn(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    depth_objs = [o for o in objs if o.depth is not None]
    if len(depth_objs) < 2:
        return
    for _ in range(100):
        a, b = sink.rng.sample(depth_objs, 2)
        if abs(float(a.depth) - float(b.depth)) >= 0.2:
            media = sink.overlay(template["template_id"], [a, b], ["A", "B"])
            answer = "A" if float(a.depth) < float(b.depth) else "B"
            sink.add(template=template, question="观察标注图，标注物体 A 是否比标注物体 B 更靠近相机？", answer=answer, answer_type="yes_no", options={"A": "是", "B": "否"}, objects=[a, b], evidence=record, media_path=media, gt_values={"A_depth": a.depth, "B_depth": b.depth})
            return


def gen_frame_scene_type(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    label = scene_type_label(record.get("scene_type") or record.get("environment_type") or record.get("category"))
    if not label:
        return
    options = ["residential interior", "historic interior", "artistic room", "outdoor or open area", "industrial or utility space"]
    if label not in options:
        options = [label, *[x for x in options if x != label]][:4]
    else:
        options = [label, *[x for x in options if x != label]][:4]
    sink.rng.shuffle(options)
    option_map = as_options(options)
    sink.add(
        template=template,
        question="Which coarse scene category best matches the visible RGB view?",
        answer=answer_for_option(option_map, label),
        answer_type="single_choice",
        options=option_map,
        objects=[],
        evidence=record,
        gt_values={"scene_type": label},
    )


def gen_frame_depth_band(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    band = estimate_depth_band(record_depth_path(record), sink.bundle, Path(str(record.get("_source_file") or ".")), record)
    if not band:
        return
    labels = {"near": "mostly near surfaces", "medium": "mixed mid-range surfaces", "far": "mostly far/open depth"}
    options = list(labels.values())
    sink.rng.shuffle(options)
    option_map = as_options(options)
    sink.add(
        template=template,
        question="Using the RGB-depth panel, which depth pattern best describes the visible scene?",
        answer=answer_for_option(option_map, labels[band]),
        answer_type="single_choice",
        options=option_map,
        objects=[],
        evidence=record,
        gt_values={"depth_band": band},
    )


def gen_frame_pose_orientation(sink: Sink, template: Dict[str, Any], record: Dict[str, Any], objs: List[Obj]) -> None:
    heading = record_heading(record)
    if heading not in {"north", "south", "east", "west"}:
        return
    labels = {"north": "north/upward direction", "south": "south/downward direction", "east": "east/rightward direction", "west": "west/leftward direction"}
    options = list(labels.values())
    sink.rng.shuffle(options)
    option_map = as_options(options)
    sink.add(
        template=template,
        question="In the pose/map panel, which direction does the camera heading arrow indicate?",
        answer=answer_for_option(option_map, labels[heading]),
        answer_type="single_choice",
        options=option_map,
        objects=[],
        evidence=record,
        gt_values={"viewing_direction": heading},
    )


GENERATOR_BY_HINT = {
    "gen_category_visible_yn": gen_category_visible_yn,
    "gen_category_count_interval": gen_category_count_interval,
    "gen_left_of_yn": gen_left_of_yn,
    "gen_above_yn": gen_above_yn,
    "gen_left_to_right_order": gen_left_to_right_order,
    "gen_largest_visible_area": gen_largest_visible_area,
    "gen_closer_to_camera_yn": gen_closer_to_camera_yn,
    "gen_frame_scene_type": gen_frame_scene_type,
    "gen_frame_depth_band": gen_frame_depth_band,
    "gen_frame_pose_orientation": gen_frame_pose_orientation,
}


def load_templates(bundle: Path) -> List[Dict[str, Any]]:
    rows = [row for row in load_jsonl(bundle / "template_manifest.jsonl") if str(row.get("status") or "enabled").lower() not in {"disabled", "blocked", "fail"}]
    return rows


def generate(args: argparse.Namespace) -> None:
    bundle = Path(args.bundle).expanduser().resolve()
    evidence_path = Path(args.evidence_index).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    rows = load_jsonl(evidence_path)
    templates = load_templates(bundle)
    if args.template_id:
        templates = [t for t in templates if t.get("template_id") == args.template_id]
    if not templates:
        raise SystemExit("No enabled templates available.")
    image_manifest = load_image_manifest(bundle)
    allow_raw_fallback = bool(args.allow_raw_fallback)
    all_items: List[Dict[str, Any]] = []
    filtered: List[Dict[str, Any]] = []
    for idx, record in enumerate(rows):
        sample_id = record_id(record, idx)
        for template in templates:
            image, selected_anchor_type = manifest_anchor_for_record(record, idx, bundle, evidence_path, image_manifest, template, allow_raw_fallback=allow_raw_fallback)
            if not image or not image.is_file():
                filtered.append({"sample_id": sample_id, "template_id": template.get("template_id"), "reason": "missing_processed_media"})
                continue
            objs = extract_objects(record)
            sink = Sink(bundle, image, sample_id, args.seed + idx, selected_anchor_type)
            hint = str(template.get("implementation_hint") or "")
            fn = GENERATOR_BY_HINT.get(hint)
            if not fn:
                filtered.append({"sample_id": sample_id, "template_id": template.get("template_id"), "reason": "unsupported_implementation_hint", "implementation_hint": hint})
                continue
            before = len(sink.items)
            try:
                fn(sink, template, record, objs)
            except Exception as exc:
                filtered.append({"sample_id": sample_id, "template_id": template.get("template_id"), "reason": "generator_exception", "detail": repr(exc)})
            if len(sink.items) == before:
                filtered.append({"sample_id": sample_id, "template_id": template.get("template_id"), "reason": "template_not_supported_by_record"})
            all_items.extend(sink.items)
            if args.limit > 0 and len(all_items) >= args.limit:
                break
        if args.limit > 0 and len(all_items) >= args.limit:
            all_items = all_items[: args.limit]
            break
    write_jsonl(out_path, all_items)
    if args.filtered_output:
        write_jsonl(Path(args.filtered_output).expanduser(), filtered)
    report = {"items": len(all_items), "filtered": len(filtered), "templates": [t.get("template_id") for t in templates], "out": str(out_path)}
    if args.report:
        write_json(Path(args.report).expanduser(), report)
    print(json.dumps(report, ensure_ascii=False))
    if not all_items:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate strict BenchClaw Stage4 items.")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--evidence-index", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260624)
    parser.add_argument("--template-id", default="")
    parser.add_argument("--filtered-output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--allow-raw-fallback", action="store_true", help="Compatibility escape hatch; contract-checking should keep this disabled.")
    return parser.parse_args()


if __name__ == "__main__":
    generate(parse_args())
'''


GEN_SCORE_PREDICTIONS = r'''#!/usr/bin/env python3
"""Deterministic scorer for generated BenchClaw Stage4 items."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


PRED_KEYS = ("prediction", "pred", "answer", "model_answer", "response", "output")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item_id(item: Dict[str, Any]) -> str:
    return str(item.get("item_id") or item.get("id") or item.get("eval_id") or "")


def norm(value: Any) -> str:
    return str(value or "").strip().upper()


def prediction_value(row: Dict[str, Any]) -> Any:
    for key in PRED_KEYS:
        if key in row:
            return row.get(key)
    return None


def load_gold(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    out: Dict[str, Any] = {}
    for row in load_jsonl(Path(path).expanduser()):
        iid = item_id(row)
        if iid:
            out[iid] = row.get("answer") if "answer" in row else row.get("gold_answer")
    return out


def build_prediction_map(predictions: List[Dict[str, Any]], expected_ids: List[str]) -> Dict[str, Any]:
    expected = set(expected_ids)
    pred_by_id: Dict[str, Any] = {}
    duplicate_ids: List[str] = []
    unknown_ids: List[str] = []
    missing_id_rows = 0
    for idx, row in enumerate(predictions):
        iid = item_id(row)
        if not iid:
            if idx < len(expected_ids):
                iid = expected_ids[idx]
            else:
                missing_id_rows += 1
                continue
        if iid in pred_by_id:
            duplicate_ids.append(iid)
        if iid not in expected:
            unknown_ids.append(iid)
        pred_by_id[iid] = prediction_value(row)
    missing_ids = [iid for iid in expected_ids if iid not in pred_by_id]
    if duplicate_ids or unknown_ids or missing_ids or missing_id_rows:
        raise ValueError(
            json.dumps(
                {
                    "duplicate_prediction_ids": sorted(set(duplicate_ids))[:20],
                    "unknown_prediction_ids": sorted(set(unknown_ids))[:20],
                    "missing_prediction_ids": missing_ids[:20],
                    "missing_prediction_count": len(missing_ids),
                    "missing_id_rows": missing_id_rows,
                    "expected_predictions": len(expected_ids),
                    "received_predictions": len(predictions),
                },
                ensure_ascii=False,
            )
        )
    return pred_by_id


def choice_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [norm(x) for x in value]
    text = norm(value)
    if not text:
        return []
    if "," in text:
        return [x.strip().upper() for x in text.split(",") if x.strip()]
    return [text]


def pairwise_order_score(gold: List[str], pred: List[str]) -> float:
    if gold == pred:
        return 1.0
    rank = {value: idx for idx, value in enumerate(pred)}
    total = 0
    correct = 0
    for i, left in enumerate(gold):
        for right in gold[i + 1:]:
            total += 1
            if left in rank and right in rank and rank[left] < rank[right]:
                correct += 1
    return correct / total if total else 0.0


def score_item(item: Dict[str, Any], prediction: Any, gold_override: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    gold = gold_override.get(item_id(item), item.get("answer"))
    answer_type = str(item.get("answer_type") or "").lower()
    if answer_type == "multi_choice":
        gold_set, pred_set = set(choice_list(gold)), set(choice_list(prediction))
        if not gold_set and not pred_set:
            return 1.0, {"gold": sorted(gold_set), "prediction": sorted(pred_set)}
        denom = len(gold_set | pred_set)
        return (len(gold_set & pred_set) / denom if denom else 0.0), {"gold": sorted(gold_set), "prediction": sorted(pred_set)}
    if answer_type == "ordered_list":
        gold_order, pred_order = choice_list(gold), choice_list(prediction)
        return pairwise_order_score(gold_order, pred_order), {"gold_order": gold_order, "pred_order": pred_order}
    gold_choice = choice_list(gold)[:1]
    pred_choice = choice_list(prediction)[:1]
    return float(bool(gold_choice and pred_choice and gold_choice[0] == pred_choice[0])), {"gold": gold_choice, "prediction": pred_choice}


def main() -> int:
    parser = argparse.ArgumentParser(description="Score BenchClaw predictions deterministically.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--out", "--output", dest="out", required=True)
    parser.add_argument("--gold", "--answers", dest="gold", default="")
    parser.add_argument("--score-items", default="")
    args = parser.parse_args()
    items = load_jsonl(Path(args.items).expanduser())
    preds = load_jsonl(Path(args.predictions).expanduser())
    gold_override = load_gold(args.gold)
    expected_ids = [item_id(item) for item in items]
    if len(expected_ids) != len(set(expected_ids)):
        raise SystemExit("items contain duplicate ids")
    pred_by_id = build_prediction_map(preds, expected_ids)
    rows = []
    scores = []
    for idx, item in enumerate(items):
        iid = item_id(item)
        prediction = pred_by_id[iid]
        score, detail = score_item(item, prediction, gold_override)
        scores.append(float(score))
        rows.append({"item_id": iid, "template_id": item.get("template_id"), "difficulty_level": item.get("difficulty_level"), "score": score, "prediction": prediction, "detail": detail})
    summary = {
        "n": len(rows),
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "median_score": statistics.median(scores) if scores else 0.0,
        "min_score": min(scores) if scores else 0.0,
        "max_score": max(scores) if scores else 0.0,
        "score_items": rows,
    }
    write_json(Path(args.out).expanduser(), summary)
    if args.score_items:
        write_jsonl(Path(args.score_items).expanduser(), rows)
    print(json.dumps({"n": summary["n"], "mean_score": summary["mean_score"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


GEN_PACKAGE_EVALSET = r'''#!/usr/bin/env python3
"""Package generated BenchClaw items into model-visible evalset layout."""

from __future__ import annotations

import argparse
import zlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List


HIDDEN_KEYS = {
    "answer",
    "answerability_proof",
    "metadata",
    "provenance",
    "evidence_refs",
    "evidence_ref",
    "source_media",
    "gold_answer",
    "gt",
    "ground_truth",
    "rgb_source",
    "source_path",
    "source_record",
    "scene",
    "scene_type",
    "category",
    "agent_state",
    "depth_stats",
    "navmesh_loaded",
}
RAW_ONLY_ANCHORS = {"", "raw_rgb", "safe_rgb", "safe_copy", "natural_rgb", "rgb", "processed_rgb", "direct_copy"}
WEAK_VISIBLE_ANCHORS = {
    "rgb_question_overlay",
    "question_overlay",
    "text_overlay",
    "caption_overlay",
    "label_bar",
    "metadata_strip",
    "template_overlay",
    "metadata_overlay",
}
STRONG_VISIBLE_ANCHORS = {
    "bbox_label_overlay",
    "point_label_overlay",
    "candidate_panel",
    "rgb_depth_panel",
    "depth_visualization",
    "rgb_depth_pair",
    "pose_map_overlay",
    "trajectory_panel",
    "crop",
    "rgb_crop",
    "crop_panel",
    "region_overlay",
    "heatmap_overlay",
    "multi_view_grid",
}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item_id(item: Dict[str, Any]) -> str:
    return str(item.get("item_id") or item.get("id") or item.get("eval_id") or "")


def resolve_media(raw: str, bundle: Path, items_dir: Path) -> Path:
    path = Path(str(raw)).expanduser()
    candidates = [path] if path.is_absolute() else [items_dir / path, bundle / path, bundle.parent / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(raw)


def media_values(item: Dict[str, Any]) -> List[str]:
    value = item.get("media") or item.get("images") or item.get("image")
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if value:
        return [str(value)]
    return []


def answerability_proof(item: Dict[str, Any]) -> Dict[str, Any]:
    proof = item.get("answerability_proof")
    if isinstance(proof, dict):
        return proof
    metadata = item.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("answerability_proof"), dict):
        return metadata["answerability_proof"]
    return {}


def proof_anchor_type(proof: Dict[str, Any]) -> str:
    return str(
        proof.get("visible_anchor_type")
        or proof.get("anchor_type")
        or proof.get("visible_transform")
        or proof.get("model_visible_anchor_type")
        or ""
    ).strip().lower()


def manifest_rows_by_resolved_path(bundle: Path) -> Dict[str, List[Dict[str, Any]]]:
    rows_by_path: Dict[str, List[Dict[str, Any]]] = {}
    manifest = bundle / "image_processing" / "image_manifest.jsonl"
    if not manifest.is_file():
        return rows_by_path
    root = (bundle / "image_processing" / "images").resolve()
    for row in load_jsonl(manifest):
        if str(row.get("status") or "accepted") != "accepted":
            continue
        raw_path = str(row.get("model_input_path") or row.get("path") or row.get("image") or row.get("filename") or "")
        candidates: List[Path] = []
        if raw_path:
            path = Path(raw_path)
            candidates.extend([path] if path.is_absolute() else [bundle / raw_path, bundle.parent / raw_path, root / raw_path])
        filename = str(row.get("filename") or "")
        if filename:
            candidates.append(root / filename)
        for candidate in candidates:
            if candidate.is_file():
                rows_by_path.setdefault(str(candidate.resolve()), []).append(row)
    return rows_by_path


def manifest_anchor_types(bundle: Path, src: Path, manifest_by_path: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    rows = manifest_by_path.get(str(src.resolve()), [])
    anchors: List[str] = []
    for row in rows:
        support = row.get("answerability_support") if isinstance(row.get("answerability_support"), dict) else {}
        anchor = str(row.get("composer") or row.get("visible_asset_type") or support.get("anchor_type") or "").strip().lower()
        if anchor:
            anchors.append(anchor)
    return anchors


def enforce_processed_media(rows: List[Dict[str, Any]], bundle: Path, items_path: Path) -> None:
    failures: List[Dict[str, Any]] = []
    manifest_by_path = manifest_rows_by_resolved_path(bundle)
    for idx, item in enumerate(rows):
        iid = item_id(item) or f"item_{idx:06d}"
        proof = answerability_proof(item)
        anchor = proof_anchor_type(proof)
        if anchor in RAW_ONLY_ANCHORS or anchor in WEAK_VISIBLE_ANCHORS or anchor not in STRONG_VISIBLE_ANCHORS:
            failures.append({"item_id": iid, "reason": "raw_weak_or_unrecognized_anchor", "anchor_type": anchor})
            continue
        if not media_values(item):
            failures.append({"item_id": iid, "reason": "missing_media"})
            continue
        for raw in media_values(item):
            src = resolve_media(raw, bundle, items_path.parent)
            try:
                src.relative_to((bundle / "image_processing" / "images").resolve())
            except Exception:
                failures.append({"item_id": iid, "reason": "media_not_from_image_processing_images", "media": str(src)})
                continue
            manifest_anchors = manifest_anchor_types(bundle, src, manifest_by_path)
            if not manifest_anchors:
                failures.append({"item_id": iid, "reason": "media_missing_from_image_manifest", "media": str(src)})
                continue
            if not any(anchor_type in STRONG_VISIBLE_ANCHORS for anchor_type in manifest_anchors):
                failures.append(
                    {
                        "item_id": iid,
                        "reason": "manifest_anchor_not_strong_processed",
                        "media": str(src),
                        "manifest_anchor_types": manifest_anchors,
                    }
                )
    if failures:
        raise SystemExit(
            "Refusing to package EVALSET_DATASET with unprocessed/raw media: "
            + json.dumps({"failures": failures[:20], "count": len(failures)}, ensure_ascii=False)
        )


def scoring_for(item: Dict[str, Any]) -> str:
    answer_type = str(item.get("answer_type") or item.get("question_type") or "single_choice")
    if answer_type == "ordered_list":
        return "Exact Order + Pairwise Accuracy"
    if answer_type == "multi_choice":
        return "Set Exact Match + F1"
    return "Exact Match"


def load_jsonl_optional(path: Path) -> List[Dict[str, Any]]:
    return load_jsonl(path) if path.is_file() else []


def write_audit_format(audit_out: Path, rows: List[Dict[str, Any]], bundle: Path, items_path: Path) -> None:
    asset_dir = audit_out / "benchmark_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    audit_rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(rows):
        iid = item_id(item) or f"item_{idx:06d}"
        audit_images: List[str] = []
        for media_idx, raw in enumerate(media_values(item)):
            src = resolve_media(raw, bundle, items_path.parent)
            suffix = src.suffix.lower() or ".jpg"
            dst_name = f"{iid}_{media_idx:02d}{suffix}"
            dst = asset_dir / dst_name
            shutil.copy2(src, dst)
            audit_images.append(f"benchmark_assets/{dst_name}")
        provenance = dict(item.get("provenance") or {})
        if not provenance:
            provenance = {
                "source_media": item.get("source_media") or media_values(item),
                "evidence_refs": item.get("evidence_refs") or [],
                "gt_values": (item.get("metadata") or {}).get("gt_values", {}) if isinstance(item.get("metadata"), dict) else {},
                "template_gt_rule": (item.get("metadata") or {}).get("template_gt_rule") if isinstance(item.get("metadata"), dict) else item.get("template_gt_rule"),
            }
        quality_flags = dict(item.get("quality_flags") or {})
        quality_flags.setdefault("uses_only_available_gt", True)
        quality_flags.setdefault("deterministic_unique_answer", True)
        quality_flags.setdefault("model_visible_anchor_present", bool(item.get("answerability_proof") or (isinstance(item.get("metadata"), dict) and item["metadata"].get("answerability_proof"))))
        audit_rows.append(
            {
                "id": iid,
                "sample_id": str(item.get("sample_id") or iid),
                "scene_id": str(item.get("scene_id") or item.get("scene") or item.get("sample_id") or ""),
                "split": str(item.get("split") or "test"),
                "image": audit_images[0] if audit_images else "",
                "images": audit_images,
                "source_image_count": len(audit_images),
                "input_modalities": item.get("input_modalities") or ["rgb"],
                "sequence_semantics": item.get("sequence_semantics") or ("multi_image" if len(audit_images) > 1 else "single_capture"),
                "template_id": item.get("template_id"),
                "capability_id": (item.get("capability_tags") or item.get("capability_id") or ["unknown"])[0] if isinstance(item.get("capability_tags"), list) else item.get("capability_id", "unknown"),
                "capability_name": item.get("capability_name") or "",
                "question_type": item.get("question_type") or item.get("answer_type") or "single_choice",
                "question_type_name": item.get("question_type_name") or str(item.get("answer_type") or "single_choice"),
                "question": item.get("question"),
                "options": item.get("options"),
                "answer": item.get("answer"),
                "answer_type": item.get("answer_type"),
                "scoring": item.get("scoring") or scoring_for(item),
                "metric_id": item.get("metric_id"),
                "difficulty_level": item.get("difficulty_level") or (item.get("metadata") or {}).get("difficulty_level") if isinstance(item.get("metadata"), dict) else item.get("difficulty_level"),
                "provenance": provenance,
                "answerability_proof": item.get("answerability_proof") or (item.get("metadata") or {}).get("answerability_proof") if isinstance(item.get("metadata"), dict) else item.get("answerability_proof"),
                "quality_flags": quality_flags,
            }
        )
    write_jsonl(audit_out / "benchmark_items.jsonl", audit_rows)
    template_rows = load_jsonl_optional(bundle / "template_manifest.jsonl")
    metric_rows = load_jsonl_optional(bundle / "metric_manifest.jsonl")
    registry_src = bundle / "contrib" / "template_registry" / "template_registry.json"
    registry_payload: Dict[str, Any]
    if registry_src.is_file():
        try:
            registry_payload = json.loads(registry_src.read_text(encoding="utf-8"))
        except Exception:
            registry_payload = {}
    else:
        registry_payload = {}
    if not registry_payload or registry_payload.get("status") == "initialized":
        registry_payload = {
            "schema_version": "benchclaw.universal_evalset.template_registry.v1",
            "library_name": "stage4_generated_templates",
            "templates": {str(row.get("template_id")): row for row in template_rows if row.get("template_id")},
            "metrics": {str(row.get("template_id")): row for row in metric_rows if row.get("template_id")},
        }
    write_json(audit_out / "template_registry.json", registry_payload)
    by_template = Counter(str(row.get("template_id") or "unknown") for row in audit_rows)
    by_capability = Counter(str(row.get("capability_id") or "unknown") for row in audit_rows)
    by_question_type = Counter(str(row.get("question_type") or "unknown") for row in audit_rows)
    by_difficulty = Counter(str(row.get("difficulty_level") or "unknown") for row in audit_rows)
    report = {
        "schema_version": "benchclaw.universal_evalset.generation_report.v1",
        "status": "passed" if audit_rows else "failed",
        "num_items": len(audit_rows),
        "items_by_template": dict(sorted(by_template.items())),
        "items_by_capability": dict(sorted(by_capability.items())),
        "items_by_question_type": dict(sorted(by_question_type.items())),
        "items_by_difficulty": dict(sorted(by_difficulty.items())),
        "quality_checks": {
            "all_items_have_answer": all(row.get("answer") not in (None, "", [], {}) for row in audit_rows),
            "all_items_have_provenance": all(bool(row.get("provenance")) for row in audit_rows),
            "all_items_have_quality_flags": all(bool(row.get("quality_flags")) for row in audit_rows),
            "assets_copied_to_benchmark_assets": bool(audit_rows) and all(str(path).startswith("benchmark_assets/") for row in audit_rows for path in row.get("images", [])),
        },
        "format_note": "Universal audit format derived from the same accepted audit items as the Stage5 package.",
    }
    write_json(audit_out / "generation_report.json", report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Package BenchClaw evalset.")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--items", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--audit-format-out", default="")
    args = parser.parse_args()
    bundle = Path(args.bundle).expanduser().resolve()
    items_path = Path(args.items).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    rows = load_jsonl(items_path)
    enforce_processed_media(rows, bundle, items_path)
    image_dir = out / "images"
    data_dir = out / "data"
    gt_dir = out / "ground_truth"
    metrics_dir = out / "metrics"
    cards_dir = out / "cards"
    image_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    gt_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    cards_dir.mkdir(parents=True, exist_ok=True)
    visible_rows = []
    answer_rows = []
    audit_rows = []
    for idx, item in enumerate(rows):
        iid = item_id(item) or f"item_{idx:06d}"
        copied_media = []
        for media_idx, raw in enumerate(media_values(item)):
            src = resolve_media(raw, bundle, items_path.parent)
            suffix = src.suffix.lower() or ".jpg"
            dst_name = f"{iid}_{media_idx:02d}{suffix}"
            dst = image_dir / dst_name
            shutil.copy2(src, dst)
            copied_media.append(f"./images/{dst_name}")
        visible = {k: v for k, v in item.items() if k not in HIDDEN_KEYS and not str(k).startswith(("gt_", "gold_"))}
        visible["item_id"] = iid
        visible["id"] = iid
        visible["media"] = copied_media
        if copied_media:
            visible["image"] = copied_media[0]
        visible_rows.append(visible)
        answer_rows.append({"item_id": iid, "answer": item.get("answer"), "template_id": item.get("template_id"), "metric_id": item.get("metric_id"), "evidence_refs": item.get("evidence_refs"), "metadata": item.get("metadata")})
        audit_item = dict(item)
        proof = dict(audit_item.get("answerability_proof") or {})
        if proof:
            proof["visible_media"] = copied_media
            audit_item["answerability_proof"] = proof
            metadata = dict(audit_item.get("metadata") or {})
            metadata["answerability_proof"] = proof
            audit_item["metadata"] = metadata
        audit_rows.append(audit_item)
    write_jsonl(data_dir / "test.jsonl", visible_rows)
    write_jsonl(gt_dir / "answers.jsonl", answer_rows)
    write_jsonl(gt_dir / "audit_items_with_answers.jsonl", audit_rows)
    scorer_src = bundle / "scripts" / "score_predictions.py"
    if scorer_src.is_file():
        shutil.copy2(scorer_src, metrics_dir / "score_predictions.py")
    audit_src = bundle / "scripts" / "audit_evalset_quality.py"
    if audit_src.is_file():
        shutil.copy2(audit_src, metrics_dir / "audit_evalset_quality.py")
    write_json(out / "manifest.json", {"num_items": len(rows), "data": "data/test.jsonl", "answers": "ground_truth/answers.jsonl", "audit": "ground_truth/audit_items_with_answers.jsonl", "metrics": "metrics/score_predictions.py"})
    (out / "README.md").write_text(
        "# BenchClaw Evalset\n\n"
        "Model-visible data is in `data/test.jsonl`; local media are under `images/`; hidden answers and audit rows are under `ground_truth/`.\n"
        "Do not provide `ground_truth/` to evaluated models. Use `metrics/score_predictions.py` for deterministic offline scoring.\n",
        encoding="utf-8",
    )
    (cards_dir / "benchmark_card.md").write_text(
        "# BenchClaw Benchmark Card\n\n"
        "## Source\n\n"
        "This package was synthesized from Stage3 evidence selected by the Stage4 plan. Source provenance, evidence refs, and answerability proofs are preserved only in hidden audit files.\n\n"
        "## Task And Visible Input\n\n"
        "Evaluated models receive only `data/test.jsonl` and referenced `./images/...` media. Each item must be answerable from those model-visible anchors; private GT is used only to derive hidden answers and audits.\n\n"
        "## Hidden GT Boundary\n\n"
        "`ground_truth/answers.jsonl` and `ground_truth/audit_items_with_answers.jsonl` contain answers, evidence refs, provenance, and answerability proofs. They must not be included in prompts or model-visible files.\n\n"
        "## Metric And Scorer\n\n"
        "Primary scoring is deterministic and offline. Run `python metrics/score_predictions.py --items data/test.jsonl --predictions <predictions.jsonl> --gold ground_truth/answers.jsonl --out <report.json>`.\n\n"
        "## Distribution\n\n"
        f"- Items: {len(rows)}\n"
        "- Model-visible data: data/test.jsonl\n"
        "- Hidden answers: ground_truth/answers.jsonl\n"
        "- Audit rows: ground_truth/audit_items_with_answers.jsonl\n"
        "- Metrics: metrics/score_predictions.py\n\n"
        "## Limitations And Usage Boundary\n\n"
        "This card is generated at packaging time. Consult the Stage4 reports for exact collection or synthesis settings, disabled templates, rejected media, and known limitations before public release.\n",
        encoding="utf-8",
    )
    audit_script = metrics_dir / "audit_evalset_quality.py"
    if audit_script.is_file():
        subprocess.run(
            [sys.executable, str(audit_script), "--evalset", str(out), "--out", str(out / "quality_audit_report.json")],
            check=True,
        )
    if args.audit_format_out:
        write_audit_format(Path(args.audit_format_out).expanduser().resolve(), rows, bundle, items_path)
    print(json.dumps({"items": len(rows), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


GEN_CHECK_DIFFICULTY = r'''#!/usr/bin/env python3
"""Check easy/medium/hard difficulty mix."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
    return rows


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def difficulty(item: Dict[str, Any]) -> str:
    value = item.get("difficulty_level") or item.get("difficulty")
    if not value and isinstance(item.get("metadata"), dict):
        value = item["metadata"].get("difficulty_level")
    return str(value or "").lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check difficulty mix.")
    parser.add_argument("--items", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--min-easy", type=float, default=0.20)
    parser.add_argument("--min-medium", type=float, default=0.25)
    parser.add_argument("--min-hard", type=float, default=0.20)
    args = parser.parse_args()
    rows = load_jsonl(Path(args.items).expanduser())
    counts = Counter(difficulty(row) for row in rows)
    total = len(rows)
    ratios = {key: (counts.get(key, 0) / total if total else 0.0) for key in ("easy", "medium", "hard")}
    if total < 5:
        status = "LIMITED_PASS" if total > 0 and all(difficulty(row) in {"easy", "medium", "hard"} for row in rows) else "FAIL"
    else:
        status = "PASS" if ratios["easy"] >= args.min_easy and ratios["medium"] >= args.min_medium and ratios["hard"] >= args.min_hard else "FAIL"
    report = {"status": status, "total": total, "counts": dict(counts), "ratios": ratios, "minimums": {"easy": args.min_easy, "medium": args.min_medium, "hard": args.min_hard}}
    if args.out:
        write_json(Path(args.out).expanduser(), report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if status in {"PASS", "LIMITED_PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


GEN_VALIDATE_BUNDLE = r'''#!/usr/bin/env python3
"""Validate a Stage4 data_20 bundle at a lightweight contract level."""

from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
from pathlib import Path


REQUIRED = [
    "evidence_index.jsonl",
    "template_manifest.jsonl",
    "metric_manifest.jsonl",
    "scripts/generate_items.py",
    "scripts/score_predictions.py",
    "scripts/package_evalset.py",
    "scripts/audit_evalset_quality.py",
    "scripts/check_difficulty_mix.py",
    "scripts/validate_bundle.py",
    "scripts/one_click_generate_evalset.py",
    "contrib/gt_adapter/adapter_contract.json",
    "contrib/asset_builder/asset_builder_contract.json",
    "contrib/template_registry/template_registry.json",
    "contrib/metric_registry/metric_registry.json",
    "contrib/item_validator/item_validator_contract.json",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage4 data_20 bundle.")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--items", default="", help="Optional generated audit-item JSONL to validate.")
    parser.add_argument("--package", default="", help="Optional packaged evalset directory to validate.")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    bundle = Path(args.bundle).expanduser().resolve()
    checks = []
    for rel in REQUIRED:
        path = bundle / rel
        checks.append({"path": rel, "ok": path.is_file() and path.stat().st_size > 0})
    for rel in [r for r in REQUIRED if r.endswith(".py")]:
        path = bundle / rel
        ok = False
        detail = ""
        try:
            py_compile.compile(str(path), doraise=True)
            ok = True
        except Exception as exc:
            detail = repr(exc)
        checks.append({"path": rel, "check": "py_compile", "ok": ok, "detail": detail})
    if args.items:
        item_path = Path(args.items).expanduser().resolve()
        item_count = 0
        has_answers = False
        has_media = False
        try:
            with item_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    item_count += 1
                    has_answers = has_answers or bool(row.get("answer"))
                    has_media = has_media or bool(row.get("media") or row.get("image"))
            checks.append({"path": str(item_path), "check": "items_nonempty", "ok": item_count > 0, "count": item_count})
            checks.append({"path": str(item_path), "check": "audit_answers_present", "ok": has_answers})
            checks.append({"path": str(item_path), "check": "media_present", "ok": has_media})
        except Exception as exc:
            checks.append({"path": str(item_path), "check": "items_readable", "ok": False, "detail": repr(exc)})
    if args.package:
        package = Path(args.package).expanduser().resolve()
        for rel in ("data/test.jsonl", "ground_truth/answers.jsonl", "ground_truth/audit_items_with_answers.jsonl", "metrics/score_predictions.py", "manifest.json"):
            path = package / rel
            checks.append({"path": str(path), "check": "package_file", "ok": path.is_file() and path.stat().st_size > 0})
        visible_path = package / "data" / "test.jsonl"
        if visible_path.is_file():
            leaked = False
            try:
                with visible_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        leaked = leaked or any(key in row for key in ("answer", "source_media", "metadata", "evidence_refs"))
                checks.append({"path": str(visible_path), "check": "no_model_visible_answer_leakage", "ok": not leaked})
            except Exception as exc:
                checks.append({"path": str(visible_path), "check": "visible_readable", "ok": False, "detail": repr(exc)})
        audit_script = bundle / "scripts" / "audit_evalset_quality.py"
        if audit_script.is_file():
            audit_report = bundle / "self_test" / "evalset_quality_audit_report.json"
            proc = subprocess.run([sys.executable, str(audit_script), "--evalset", str(package), "--out", str(audit_report)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            checks.append({"path": str(package), "check": "evalset_quality_audit", "ok": proc.returncode == 0, "report": str(audit_report), "stdout_tail": proc.stdout[-1000:], "stderr_tail": proc.stderr[-1000:]})
        else:
            checks.append({"path": str(audit_script), "check": "evalset_quality_audit_script", "ok": False})
    status = "PASS" if all(row["ok"] for row in checks) else "FAIL"
    report = {"status": status, "checks": checks}
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


GEN_ONE_CLICK = r'''#!/usr/bin/env python3
"""One-click wrapper around the canonical Stage4 runtime scripts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and package a BenchClaw evalset in one command.")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--evidence-index", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260624)
    parser.add_argument("--audit-format-out", default="")
    args = parser.parse_args()
    bundle = Path(args.bundle).expanduser().resolve()
    evidence = Path(args.evidence_index).expanduser().resolve() if args.evidence_index else bundle / "evidence_index.jsonl"
    out = Path(args.out).expanduser().resolve()
    work = out / "_work"
    items = work / "items.jsonl"
    filtered = work / "filtered_items.jsonl"
    gen = [sys.executable, str(bundle / "scripts" / "generate_items.py"), "--bundle", str(bundle), "--evidence-index", str(evidence), "--out", str(items), "--limit", str(args.limit), "--seed", str(args.seed), "--filtered-output", str(filtered)]
    subprocess.run(gen, check=True)
    package_cmd = [sys.executable, str(bundle / "scripts" / "package_evalset.py"), "--bundle", str(bundle), "--items", str(items), "--out", str(out)]
    if args.audit_format_out:
        package_cmd.extend(["--audit-format-out", str(Path(args.audit_format_out).expanduser().resolve())])
    subprocess.run(package_cmd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_default_contrib_contracts(bundle: Path) -> None:
    metric_rows = []
    for row in DEFAULT_TEMPLATES:
        metric_rows.append(
            {
                "template_id": row["template_id"],
                "answer_type": row["answer_type"],
                "metric_id": row["metric_id"],
                "primary_metric": True,
                "prediction_parser": "choice_key" if row["answer_type"] != "ordered_list" else "ordered_keys",
                "score_function": "score_exact_choice" if row["answer_type"] != "ordered_list" else "score_pairwise_order",
            }
        )
    contracts = {
        "contrib/gt_adapter/adapter_contract.json": {
            "schema_version": "benchclaw.stage4.gt_adapter.v1",
            "status": "default_runtime_baseline",
            "canonical_record_id_fields": ["sample_id", "record_id", "item_id", "id"],
            "canonical_media_fields": ["image_path", "rgb_path", "media", "image"],
            "field_families": {
                "objects": {
                    "source_paths": ["objects", "visible_objects", "candidate_objects", "annotations", "gt_summary.objects"],
                    "canonical_fields": ["category", "bbox_xyxy", "centroid_xy", "area_px", "depth"],
                    "private_by_default": ["object_id", "bbox_xyxy", "area_px", "depth"],
                }
            },
            "safe_prompt_sample_policy": "redacted_compact_examples_only",
        },
        "contrib/asset_builder/asset_builder_contract.json": {
            "schema_version": "benchclaw.stage4.asset_builder.v1",
            "status": "default_runtime_baseline",
            "manifest": "image_processing/image_manifest.jsonl",
            "asset_root": "image_processing/images",
            "supported_composers": ["safe_copy", "bbox_label_overlay", "multi_view_grid", "candidate_panel"],
            "final_evalset_eligible_composers": [
                "bbox_label_overlay",
                "point_label_overlay",
                "candidate_panel",
                "rgb_depth_panel",
                "pose_map_overlay",
                "trajectory_panel",
                "crop_panel",
                "region_overlay",
                "heatmap_overlay",
                "multi_view_grid",
            ],
            "raw_or_weak_composers_forbidden_in_final_evalset": [
                "safe_copy",
                "processed_rgb",
                "direct_copy",
                "raw_rgb",
                "rgb",
                "rgb_question_overlay",
                "question_overlay",
                "text_overlay",
                "metadata_strip",
            ],
            "neutral_label_policy": ["A", "B", "C", "D", "View 1", "Step 1"],
            "model_visible_path_policy": "bundle_relative_then_packaged_as ./images/...",
        },
        "contrib/template_registry/template_registry.json": {
            "schema_version": "benchclaw.stage4.template_registry.v1",
            "status": "default_runtime_baseline",
            "library_name": "benchclaw_default_static_vlm_templates",
            "templates": {row["template_id"]: row for row in DEFAULT_TEMPLATES},
        },
        "contrib/metric_registry/metric_registry.json": {
            "schema_version": "benchclaw.stage4.metric_registry.v1",
            "status": "default_runtime_baseline",
            "scorer_cli": "scripts/score_predictions.py --items <items> --predictions <predictions> --gold <answers> --out <report>",
            "metrics": {row["metric_id"]: row for row in metric_rows},
        },
        "contrib/item_validator/item_validator_contract.json": {
            "schema_version": "benchclaw.stage4.item_validator.v1",
            "status": "default_runtime_baseline",
            "validator_surfaces": ["scripts/validate_bundle.py", "scripts/audit_evalset_quality.py"],
            "checks": [
                "answerability_proof_present",
                "model_visible_hidden_gt_removed",
                "complete_prediction_set_required",
                "audit_format_projection_available",
            ],
        },
    }
    for rel, payload in contracts.items():
        path = bundle / rel
        if not path.is_file() or path.stat().st_size == 0:
            write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_runtime(bundle: Path, *, overwrite_manifests: bool = False) -> None:
    scripts = bundle / "scripts"
    write_text(scripts / "generate_items.py", GEN_GENERATE_ITEMS)
    write_text(scripts / "score_predictions.py", GEN_SCORE_PREDICTIONS)
    write_text(scripts / "package_evalset.py", GEN_PACKAGE_EVALSET)
    if AUDIT_EVALSET_SCRIPT.is_file():
        write_text(scripts / "audit_evalset_quality.py", AUDIT_EVALSET_SCRIPT.read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(AUDIT_EVALSET_SCRIPT)
    write_text(scripts / "check_difficulty_mix.py", GEN_CHECK_DIFFICULTY)
    write_text(scripts / "validate_bundle.py", GEN_VALIDATE_BUNDLE)
    write_text(scripts / "one_click_generate_evalset.py", GEN_ONE_CLICK)
    if overwrite_manifests or not (bundle / "template_manifest.jsonl").is_file() or (bundle / "template_manifest.jsonl").stat().st_size == 0:
        write_jsonl(bundle / "template_manifest.jsonl", DEFAULT_TEMPLATES)
    if overwrite_manifests or not (bundle / "metric_manifest.jsonl").is_file() or (bundle / "metric_manifest.jsonl").stat().st_size == 0:
        metric_rows = []
        for row in DEFAULT_TEMPLATES:
            metric_rows.append(
                {
                    "template_id": row["template_id"],
                    "answer_type": row["answer_type"],
                    "metric_id": row["metric_id"],
                    "primary_metric": True,
                    "prediction_parser": "choice_key" if row["answer_type"] != "ordered_list" else "ordered_keys",
                    "score_function": "score_exact_choice" if row["answer_type"] != "ordered_list" else "score_pairwise_order",
                    "qwen_generation_notes": ["deterministic offline scorer"],
                }
            )
        write_jsonl(bundle / "metric_manifest.jsonl", metric_rows)
    contract_path = bundle / "synthesizer_contract.json"
    if contract_path.is_file():
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    else:
        payload = {}
    payload.update(
        {
            "status": "default_runtime_written",
            "runtime_writer": "write_one_click_runtime.py",
            "consumed_contributors": [
                "contrib/gt_adapter/adapter_contract.json",
                "contrib/asset_builder/asset_builder_contract.json",
                "contrib/template_registry/template_registry.json",
                "contrib/metric_registry/metric_registry.json",
                "contrib/item_validator/item_validator_contract.json",
            ],
            "output_formats": {
                "audit_format": "benchmark_items.jsonl + template_registry.json + generation_report.json + benchmark_assets/",
                "stage5_package": "data/test.jsonl + images/ + ground_truth/ + metrics/",
            },
        }
    )
    contract_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_default_contrib_contracts(bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write default one-click runtime scripts into a Stage4 data_20 bundle.")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--overwrite-manifests", action="store_true")
    args = parser.parse_args(argv)
    write_runtime(Path(args.bundle).expanduser().resolve(), overwrite_manifests=args.overwrite_manifests)
    print(json.dumps({"bundle": str(Path(args.bundle).expanduser().resolve()), "status": "runtime_written"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
