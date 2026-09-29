#!/usr/bin/env python3
"""Runtime helpers for GT-driven visual markers in generated benchmark bundles."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

LABEL_ALPHABET = [chr(code) for code in range(ord("A"), ord("Z") + 1)]
TARGET_CONTAINER_KEYS = (
    "visual_marker_targets",
    "visual_targets",
    "marker_targets",
    "referenced_objects",
    "target_objects",
    "objects_to_mark",
)
OBJECT_ID_KEYS = ("object_id", "actor_id", "instance_id", "entity_id", "id")
VISIBILITY_KEYS = ("visible", "is_visible", "visibility", "visibility_status")
FORBIDDEN_OVERLAY_TERMS = {
    "correct",
    "wrong",
    "nearest",
    "farthest",
    "inside",
    "support",
    "occlude",
    "reachable",
    "unreachable",
}
LABEL_TOKEN_RE = re.compile(r"\b([A-Z]|P\d+|S|G)\b")


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_media_paths(media_paths: Sequence[Any], workspace_root: Path) -> List[str]:
    normalized: List[str] = []
    for raw_path in media_paths or []:
        text = str(raw_path or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        path = ((workspace_root / path).resolve() if not path.is_absolute() else path.resolve())
        try:
            path.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError(f"media path must stay inside current workspace: {text} -> {path}") from exc
        normalized.append(str(path))
    return normalized


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_source_inventory(path: Path) -> Dict[str, Dict[str, Any]]:
    inventory: Dict[str, Dict[str, Any]] = {}
    for row in load_jsonl(path):
        name = str(row.get("source_name") or "").strip()
        if name:
            inventory[name] = row
    return inventory


def build_stage3_record_index(source_inventory: Dict[str, Dict[str, Any]], workspace_root: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for source_name, row in source_inventory.items():
        artifact_root = str(row.get("artifact_root") or "").strip()
        if not artifact_root:
            continue
        root = Path(artifact_root)
        root = (workspace_root / root).resolve() if not root.is_absolute() else root.resolve()
        candidates = [
            root / "annotation_records.jsonl",
            root / "privileged_gt.jsonl",
            root / "SIMULATOR_DATA.jsonl",
        ]
        for candidate in candidates:
            for record in load_jsonl(candidate):
                record_id = str(record.get("record_id") or record.get("evidence_id") or "").strip()
                if record_id:
                    index[(source_name, record_id)] = record
    return index


def parse_bbox(value: Any) -> Optional[Dict[str, int]]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            x1, y1, x2, y2 = [int(round(float(x))) for x in value]
            return {"xmin": x1, "ymin": y1, "xmax": x2, "ymax": y2}
        except (TypeError, ValueError):
            return None
    if not isinstance(value, dict):
        return None
    if {"xmin", "ymin", "xmax", "ymax"} <= set(value):
        return {key: int(round(float(value[key]))) for key in ("xmin", "ymin", "xmax", "ymax")}
    if {"x1", "y1", "x2", "y2"} <= set(value):
        return {
            "xmin": int(round(float(value["x1"]))),
            "ymin": int(round(float(value["y1"]))),
            "xmax": int(round(float(value["x2"]))),
            "ymax": int(round(float(value["y2"]))),
        }
    if {"x", "y", "w", "h"} <= set(value):
        x = int(round(float(value["x"])))
        y = int(round(float(value["y"])))
        w = int(round(float(value["w"])))
        h = int(round(float(value["h"])))
        return {"xmin": x, "ymin": y, "xmax": x + w, "ymax": y + h}
    return None


def parse_point(value: Any) -> Optional[Dict[str, int]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            x, y = int(round(float(value[0]))), int(round(float(value[1])))
            return {"x": x, "y": y}
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        if {"x", "y"} <= set(value):
            return {"x": int(round(float(value["x"]))), "y": int(round(float(value["y"])))}
        if {"cx", "cy"} <= set(value):
            return {"x": int(round(float(value["cx"]))), "y": int(round(float(value["cy"])))}
        if {"u", "v"} <= set(value):
            return {"x": int(round(float(value["u"]))), "y": int(round(float(value["v"])))}
    return None


def extract_object_id(target: Dict[str, Any]) -> str:
    for key in OBJECT_ID_KEYS:
        value = target.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def extract_visibility(target: Dict[str, Any]) -> str:
    for key in VISIBILITY_KEYS:
        value = target.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            return "visible" if value else "invisible"
        return str(value)
    return "visible"


def assign_labels(targets: Sequence[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    for idx, target in enumerate(targets):
        explicit = str(target.get("label") or "").strip()
        if explicit:
            labels.append(explicit)
            continue
        if idx < len(LABEL_ALPHABET):
            labels.append(LABEL_ALPHABET[idx])
        else:
            labels.append(f"P{idx + 1}")
    return labels


def collect_explicit_targets(item: Dict[str, Any], record: Dict[str, Any], template_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    for container in (item, item.get("metadata", {}), record, record.get("gt_summary", {}), template_config, template_config.get("visual_marker_policy", {})):
        if not isinstance(container, dict):
            continue
        for key in TARGET_CONTAINER_KEYS:
            value = container.get(key)
            if isinstance(value, list) and value:
                return [entry for entry in value if isinstance(entry, dict)]
    return []


def select_targets_from_visible_objects(
    visible_objects: Sequence[Dict[str, Any]],
    selector_ids: Sequence[Any],
    selector_indexes: Sequence[Any],
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    id_set = {str(value) for value in selector_ids}
    for idx, obj in enumerate(visible_objects):
        object_id = extract_object_id(obj)
        if object_id and object_id in id_set:
            selected.append(dict(obj))
            continue
        if idx in selector_indexes:
            selected.append(dict(obj))
    return selected


def infer_targets_from_record(item: Dict[str, Any], record: Dict[str, Any], template_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    explicit = collect_explicit_targets(item, record, template_config)
    if explicit:
        return explicit

    policy = template_config.get("visual_marker_policy", {}) if isinstance(template_config, dict) else {}
    selector_ids = ensure_list(policy.get("selector_object_ids"))
    selector_indexes = [int(x) for x in ensure_list(policy.get("selector_indexes")) if str(x).strip()]
    if not selector_ids and not selector_indexes:
        return []

    gt_summary = record.get("gt_summary", {}) if isinstance(record.get("gt_summary"), dict) else {}
    containers: List[Sequence[Dict[str, Any]]] = []
    if isinstance(gt_summary.get("visible_actors"), list):
        containers.append(gt_summary["visible_actors"])
    cameras = gt_summary.get("cameras", {})
    if isinstance(cameras, dict):
        for camera in cameras.values():
            visible = camera.get("visible_objects") if isinstance(camera, dict) else None
            if isinstance(visible, dict) and isinstance(visible.get("visible_actors"), list):
                containers.append(visible["visible_actors"])

    for container in containers:
        selected = select_targets_from_visible_objects(container, selector_ids, selector_indexes)
        if selected:
            return selected
    return []


def quality_checks_for_target(target: Dict[str, Any], image_size: Tuple[int, int]) -> List[Dict[str, Any]]:
    width, height = image_size
    issues: List[Dict[str, Any]] = []
    bbox = target.get("bbox")
    point = target.get("point")
    if bbox:
        inside = bbox["xmin"] >= 0 and bbox["ymin"] >= 0 and bbox["xmax"] <= width and bbox["ymax"] <= height and bbox["xmax"] > bbox["xmin"] and bbox["ymax"] > bbox["ymin"]
        if not inside:
            issues.append({"check": "bbox_in_bounds", "status": "fail"})
    if point:
        inside = 0 <= point["x"] < width and 0 <= point["y"] < height
        if not inside:
            issues.append({"check": "point_in_bounds", "status": "fail"})
    if not extract_object_id(target):
        issues.append({"check": "object_id_present", "status": "fail"})
    return issues


def draw_bbox(draw: ImageDraw.ImageDraw, bbox: Dict[str, int], label: str, color: str, font: ImageFont.ImageFont) -> None:
    draw.rectangle([bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]], outline=color, width=3)
    left = max(0, bbox["xmin"])
    top = max(0, bbox["ymin"] - 18)
    draw.rectangle([left, top, left + 24, top + 18], fill=color)
    draw.text((left + 4, top + 2), label, fill="white", font=font)


def draw_point(draw: ImageDraw.ImageDraw, point: Dict[str, int], label: str, color: str, font: ImageFont.ImageFont) -> None:
    radius = 8
    draw.ellipse([point["x"] - radius, point["y"] - radius, point["x"] + radius, point["y"] + radius], outline=color, width=3)
    draw.rectangle([point["x"] + 6, point["y"] - 18, point["x"] + 30, point["y"]], fill=color)
    draw.text((point["x"] + 10, point["y"] - 16), label, fill="white", font=font)


def render_overlay(source_path: Path, targets: Sequence[Dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        colors = ["#D62828", "#1D4ED8", "#2A9D8F", "#F4A261", "#6D28D9", "#111827"]
        for idx, target in enumerate(targets):
            color = colors[idx % len(colors)]
            if target.get("bbox"):
                draw_bbox(draw, target["bbox"], target["label"], color, font)
            elif target.get("point"):
                draw_point(draw, target["point"], target["label"], color, font)
        canvas.save(output_path)


def build_label_entries(targets: Sequence[Dict[str, Any]], image_size: Tuple[int, int]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for target in targets:
        entries.append(
            {
                "label": target.get("label"),
                "object_id": extract_object_id(target),
                "marker_type": target.get("marker_type", "bbox" if target.get("bbox") else "point"),
                "visibility": extract_visibility(target),
                "media_index": int(target.get("media_index", 0) or 0),
                "gt_fields": ensure_list(target.get("gt_fields")),
                "bbox": target.get("bbox"),
                "point": target.get("point"),
                "quality_checks": quality_checks_for_target(target, image_size),
            }
        )
    return entries


def maybe_rewrite_question(question: str, item: Dict[str, Any], record: Dict[str, Any], template_config: Dict[str, Any], label_entries: Sequence[Dict[str, Any]]) -> str:
    for container in (item, record, template_config.get("visual_marker_policy", {}), template_config):
        if not isinstance(container, dict):
            continue
        candidate = str(container.get("question_with_labels") or container.get("visual_marker_question") or "").strip()
        if candidate:
            return candidate
    policy = template_config.get("visual_marker_policy", {}) if isinstance(template_config, dict) else {}
    question_template = str(policy.get("question_template") or "").strip()
    if question_template:
        format_kwargs = {f"label_{idx + 1}": entry["label"] for idx, entry in enumerate(label_entries)}
        return question_template.format(**format_kwargs)
    return question


def collect_label_reference_issues(item: Dict[str, Any], available_labels: Sequence[str], require_label_references: bool) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    available = {str(label) for label in available_labels if str(label).strip()}
    text_fields = {
        "question": str(item.get("question") or ""),
        "answer_derivation": str(item.get("answer_derivation") or ""),
    }
    metadata = item.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ("explanation", "rationale", "analysis"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                text_fields[f"metadata.{key}"] = value

    found_any = False
    for field_name, text in text_fields.items():
        referenced = set(LABEL_TOKEN_RE.findall(text))
        if not referenced:
            continue
        found_any = True
        missing = sorted(label for label in referenced if label not in available)
        if missing:
            issues.append(
                {
                    "check": "label_reference_exists",
                    "status": "fail",
                    "field": field_name,
                    "missing_labels": missing,
                }
            )
    if require_label_references and not found_any:
        issues.append(
            {
                "check": "required_label_reference_present",
                "status": "fail",
                "field": "question",
            }
        )
    return issues


def build_visual_marker_assets(
    *,
    item: Dict[str, Any],
    record: Dict[str, Any],
    template_config: Dict[str, Any],
    workspace_root: Path,
    source_inventory: Optional[Dict[str, Dict[str, Any]]] = None,
    stage3_record_index: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
    visual_marker_dir: Optional[Path] = None,
    enable_visual_marker: bool = True,
) -> Tuple[Dict[str, Any], List[Path]]:
    source_media = normalize_media_paths(
        ensure_list(item.get("source_media") or record.get("workspace_media") or record.get("workspace_observations") or item.get("media")),
        workspace_root,
    )
    item["source_media"] = source_media
    item["media"] = list(source_media)
    metadata = item.setdefault("metadata", {})
    policy = template_config.get("visual_marker_policy", {}) if isinstance(template_config, dict) else {}
    marker_root = Path(visual_marker_dir) if visual_marker_dir else workspace_root / "tmp_visual_markers"
    marker_root.mkdir(parents=True, exist_ok=True)

    augmented_record = dict(record)
    key = (str(record.get("source_name") or ""), str(record.get("evidence_id") or record.get("record_id") or ""))
    if stage3_record_index and key in stage3_record_index:
        for k, value in stage3_record_index[key].items():
            augmented_record.setdefault(k, value)
    if source_inventory:
        src_meta = source_inventory.get(str(record.get("source_name") or ""))
        if src_meta:
            augmented_record.setdefault("_artifact_root", src_meta.get("artifact_root"))

    raw_targets = infer_targets_from_record(item, augmented_record, template_config)
    manifests: List[Path] = []
    statuses: List[str] = []
    if not enable_visual_marker:
        statuses.append("disabled")
    elif not raw_targets:
        statuses.append("no_gt_targets")

    grouped_targets: Dict[int, List[Dict[str, Any]]] = {}
    for target, label in zip(raw_targets, assign_labels(raw_targets)):
        target = dict(target)
        target["label"] = label
        target["bbox"] = parse_bbox(target.get("bbox") or target.get("bbox_2d") or target.get("bbox2d"))
        target["point"] = parse_point(target.get("point") or target.get("point2d") or target.get("centroid"))
        target["marker_type"] = target.get("marker_type") or ("bbox" if target.get("bbox") else "point" if target.get("point") else "unsupported")
        media_index = int(target.get("media_index", 0) or 0)
        grouped_targets.setdefault(media_index, []).append(target)

    output_media: List[str] = []
    map_paths: List[str] = []
    label_entries_by_item: List[Dict[str, Any]] = []

    for media_index, source_path_text in enumerate(source_media):
        source_path = Path(source_path_text)
        if not source_path.is_file():
            raise FileNotFoundError(f"source image missing: {source_path}")
        targets = grouped_targets.get(media_index, [])
        question_image_path = source_path
        status = statuses[0] if statuses else "ready"
        with Image.open(source_path) as image:
            image_size = image.size
        label_entries = build_label_entries(targets, image_size)
        label_entries_by_item.extend(label_entries)

        if enable_visual_marker and targets and all(entry["quality_checks"] == [] for entry in label_entries):
            question_image_path = marker_root / "question_media" / f"{item.get('item_id', 'item')}_{media_index:02d}{source_path.suffix or '.png'}"
            render_overlay(source_path, targets, question_image_path)
            status = "overlay_generated"
        elif enable_visual_marker and targets:
            status = "quality_check_failed"

        output_media.append(str(question_image_path.resolve()))
        manifest_path = marker_root / "maps" / f"{item.get('item_id', 'item')}_{media_index:02d}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "item_id": item.get("item_id"),
            "template_id": item.get("template_id"),
            "source_name": record.get("source_name"),
            "source_image": str(source_path),
            "question_image": str(question_image_path.resolve()),
            "status": status,
            "labels": label_entries,
            "quality_checks": {
                "overlay_exists": question_image_path.exists(),
                "forbidden_overlay_terms": sorted(FORBIDDEN_OVERLAY_TERMS),
            },
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifests.append(manifest_path)
        map_paths.append(str(manifest_path.resolve()))

    item["media"] = output_media
    item["question"] = maybe_rewrite_question(str(item.get("question") or ""), item, augmented_record, template_config, label_entries_by_item)
    require_label_references = bool(policy.get("require_label_references"))
    label_reference_issues = collect_label_reference_issues(
        item,
        [entry.get("label") for entry in label_entries_by_item],
        require_label_references,
    )
    if label_reference_issues:
        statuses = ["quality_check_failed"]
    manifest_statuses = [load_json(path).get("status", "") for path in manifests]
    if "quality_check_failed" in manifest_statuses:
        overall_status = "quality_check_failed"
    elif any(status == "overlay_generated" for status in manifest_statuses):
        overall_status = "overlay_generated"
    else:
        overall_status = statuses[0] if statuses else "ready"
    if label_reference_issues:
        overall_status = "quality_check_failed"
    metadata["visual_marker"] = {
        "enabled": bool(enable_visual_marker),
        "status": overall_status,
        "map_paths": map_paths,
        "label_count": len(label_entries_by_item),
        "question_media_mode": "processed_if_available_else_original",
        "label_reference_checks": label_reference_issues,
    }
    return item, manifests
