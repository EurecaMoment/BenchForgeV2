#!/usr/bin/env python3
"""Audit a packaged BenchClaw evalset for benchmark-validity failures."""

from __future__ import annotations

import argparse
import zlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


HIDDEN_VISIBLE_KEYS = {
    "answer",
    "answers",
    "answerability_proof",
    "audit",
    "agent_state",
    "category",
    "depth_stats",
    "gold_answer",
    "ground_truth",
    "gt",
    "metadata",
    "navmesh_loaded",
    "provenance",
    "evidence_refs",
    "evidence_ref",
    "rgb_source",
    "scene",
    "scene_type",
    "source_media",
    "source_path",
    "source_record",
}
AUDIT_KEYS = {"evidence_refs", "evidence", "audit", "audit_trail", "source", "provenance", "metadata"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
INCOMPLETE_CHOICE_RE = re.compile(r"(\bto the (?:left|right) of|\bin front of|\bbehind)$", re.I)
RELATION_CHOICE_RE = re.compile(r"\b(to the left of|to the right of|behind|in front of)\b", re.I)
NAV_QUESTION_RE = re.compile(
    r"\b(next navigational landmark|next movement|optimal continuation|shortest path|which path|route|navigation path|revised route|alternative route|where should the agent proceed)\b",
    re.I,
)
PRIVATE_GT_QUESTION_RE = re.compile(
    r"\b(simulator coordinate|coordinate x|x-zone|camera position|agent state|agent_state|pose|navmesh|navigation mesh|trajectory|center viewing ray|depth|distance band|bbox|mask|object id|frame id|scene id)\b",
    re.I,
)
MODEL_VISIBLE_PRIVATE_GT_LEAK_RE = re.compile(
    r"\b("
    r"agent rotation|agent position|agent coordinates|quaternion|"
    r"heading of approximately|heading is approximately|degrees from north|"
    r"x-z displacement|x minus z|x-coordinate|z-coordinate|positive x|positive z|"
    r"navigation mesh is available|navmesh is available|"
    r"depth sensor|per-pixel depth|gt field|ground truth"
    r")\b",
    re.I,
)
PRIVATE_GT_FIELDS = {
    "simulator_pose",
    "simulator_coordinate",
    "coordinate",
    "pose",
    "depth",
    "distance",
    "bbox",
    "mask",
    "area",
    "trajectory",
    "object_id",
    "scene_id",
    "frame_id",
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
    # gate-repair 2026-09-17 minimal alignment (full-synthesis): the A1 amendment
    # adds neutral_label_image to asset_builder_contract.final_evalset_eligible_composers
    # (falsifiable: dims+>=8 uniform-header rows+content corr>=0.5 vs declared source,
    # rerun PASS) and the bundle copy of this auditor lists it; stale-set bug in this
    # copy. Criteria otherwise untouched. Evidence+incident: workspace93
    # stage4/nodes/full-synthesis/run_logs/gaterepair.log | NODE_REPORT addendum.
    "neutral_label_image",
}
ROOT_ANSWER_BEARING_JSONL = {"dataset.jsonl", "items.jsonl", "audit_items.jsonl", "audit_items_with_answers.jsonl"}
CARD_REQUIRED_TERMS = ("source", "task", "metric", "scorer", "hidden", "visible")


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.is_file():
        return rows, [{"line": 0, "error": "missing_file"}]
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception as exc:
                errors.append({"line": line_no, "error": repr(exc)})
                continue
            if not isinstance(payload, dict):
                errors.append({"line": line_no, "error": "expected_object"})
                continue
            payload.setdefault("_line_no", line_no)
            rows.append(payload)
    return rows, errors


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item_id(row: dict[str, Any]) -> str:
    return str(row.get("item_id") or row.get("id") or row.get("eval_id") or "")


def question_text(row: dict[str, Any]) -> str:
    return str(row.get("question_text") or row.get("question") or row.get("prompt") or "")


def option_mapping(row: dict[str, Any]) -> dict[str, str]:
    raw = row.get("choices") if "choices" in row else row.get("options")
    if isinstance(raw, dict):
        return {str(key).upper(): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return {letters[idx]: str(value) for idx, value in enumerate(raw) if idx < len(letters)}
    return {}


def answer_value(row: dict[str, Any]) -> Any:
    for key in ("answer", "gold_answer", "ground_truth", "gt"):
        if key in row:
            return row.get(key)
    return None


def normalize_choice_surface(value: str) -> str:
    text = value.casefold().strip()
    text = re.sub(r"\bthe target\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def resolve_media(evalset_root: Path, raw_path: str) -> Path | None:
    text = str(raw_path or "").strip()
    if not text or text.startswith(("http://", "https://", "file://", "data:")):
        return None
    if not text.startswith("./images/") or os.path.isabs(text):
        return None
    path = (evalset_root / text[2:]).resolve()
    try:
        path.relative_to(evalset_root.resolve())
    except Exception:
        return None
    return path


def media_paths(row: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("image_path", "image", "media", "images", "image_refs"):
        if key in row:
            values.append(row.get(key))
    out: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key in ("path", "image", "image_path", "uri"):
                if key in value:
                    walk(value[key])

    for value in values:
        walk(value)
    return [x for x in dict.fromkeys(out) if x]


def image_decode_ok(path: Path) -> tuple[bool, str]:
    if path.suffix.lower() not in IMAGE_EXTS:
        return True, "not_image"
    try:
        head = path.read_bytes()[:16]
    except Exception as exc:
        return False, f"read_error:{exc!r}"
    if head.startswith(b"\xff\xd8\xff"):
        return True, "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True, "png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return True, "gif"
    if head.startswith(b"BM"):
        return True, "bmp"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return True, "webp"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return True, "tiff"
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            image.verify()
        return True, "pil_ok"
    except Exception as exc:
        return False, f"decode_failed:{exc!r}"


def image_quality(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"size_bytes": path.stat().st_size if path.exists() else 0}
    if path.suffix.lower() not in IMAGE_EXTS:
        info.update({"status": "not_image"})
        return info
    try:
        from PIL import Image, ImageStat  # type: ignore

        with Image.open(path) as image:
            gray = image.convert("L")
            stat = ImageStat.Stat(gray)
            extrema = gray.getextrema()
            info.update(
                {
                    "status": "checked",
                    "width": image.width,
                    "height": image.height,
                    "luma_mean": float(stat.mean[0]),
                    "luma_stddev": float(stat.stddev[0]),
                    "luma_min": int(extrema[0]),
                    "luma_max": int(extrema[1]),
                    "blank_or_near_blank": stat.stddev[0] < 1.0 or extrema[0] == extrema[1],
                    "low_information": stat.stddev[0] < 12.0,
                    "tiny_file": info["size_bytes"] < 512,
                }
            )
    except Exception as exc:
        info.update({"status": "quality_check_failed", "error": repr(exc)})
    return info


def add_failure(failures: list[dict[str, Any]], issue: str, severity: str, evidence: dict[str, Any], recommendation: str) -> None:
    failures.append({"issue": issue, "severity": severity, "evidence": evidence, "recommendation": recommendation})


def root_answer_bearing_jsonl_findings(evalset_root: Path) -> list[dict[str, Any]]:
    # data_22_full_benchmark_dataset may intentionally keep an internal
    # answer-bearing dataset.jsonl. EVALSET_DATASET and package-smoke outputs must
    # keep answer-bearing rows only under ground_truth/.
    if evalset_root.name == "data_22_full_benchmark_dataset":
        return []
    findings: list[dict[str, Any]] = []
    for path in sorted(evalset_root.glob("*.jsonl")):
        if path.name not in ROOT_ANSWER_BEARING_JSONL:
            continue
        rows, errors = load_jsonl(path)
        if errors:
            findings.append({"file": path.name, "error": errors[:3]})
            continue
        for row in rows[:200]:
            bad_keys = sorted(key for key in row if key in HIDDEN_VISIBLE_KEYS or str(key).startswith(("gt_", "gold_")))
            if bad_keys:
                findings.append({"file": path.name, "line": row.get("_line_no"), "keys": bad_keys})
                break
    return findings


def answerability_proof(row: dict[str, Any]) -> dict[str, Any]:
    proof = row.get("answerability_proof")
    if isinstance(proof, dict):
        return proof
    metadata = row.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("answerability_proof"), dict):
        return metadata["answerability_proof"]
    audit = row.get("audit")
    if isinstance(audit, dict) and isinstance(audit.get("answerability_proof"), dict):
        return audit["answerability_proof"]
    return {}


def proof_anchor_type(proof: dict[str, Any]) -> str:
    return str(
        proof.get("visible_anchor_type")
        or proof.get("anchor_type")
        or proof.get("visible_transform")
        or proof.get("model_visible_anchor_type")
        or ""
    ).strip().lower()


def proof_private_fields(proof: dict[str, Any]) -> set[str]:
    fields = proof.get("private_gt_fields_used_for_answer") or proof.get("private_gt_fields_used") or []
    if isinstance(fields, str):
        fields = [fields]
    if not isinstance(fields, list):
        return set()
    return {str(field).strip().lower() for field in fields if str(field).strip()}


def load_processing_manifest_by_filename(evalset_root: Path) -> dict[str, list[dict[str, Any]]]:
    workspace_root = evalset_root.parent
    candidates = [
        workspace_root / "stage4" / "artifacts" / "data_20_template_metric_code_bundle" / "image_processing" / "image_manifest.jsonl",
        evalset_root / "image_manifest.jsonl",
        evalset_root / "manifest.jsonl",
    ]
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in candidates:
        rows, errors = load_jsonl(path)
        if errors or not rows:
            continue
        for row in rows:
            names = [
                row.get("filename"),
                row.get("processed_image"),
                row.get("image"),
                row.get("image_path"),
                row.get("model_input_path"),
                row.get("workspace_path"),
                row.get("path"),
            ]
            for value in names:
                if not value:
                    continue
                by_name[Path(str(value)).name].append(row)
        if by_name:
            break
    return by_name


def manifest_anchor_type(row: dict[str, Any]) -> str:
    support = row.get("answerability_support") if isinstance(row.get("answerability_support"), dict) else {}
    overlay = row.get("overlay") if isinstance(row.get("overlay"), dict) else {}
    if overlay and not (row.get("composer") or row.get("visible_asset_type")):
        return "metadata_strip"
    return str(row.get("composer") or row.get("visible_asset_type") or support.get("anchor_type") or "").strip().lower()


def audit_scorer(evalset_root: Path, test_rows: list[dict[str, Any]], answer_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scorer = evalset_root / "metrics" / "score_predictions.py"
    if not scorer.is_file() or not test_rows or not answer_rows:
        return []
    first_answer = answer_rows[0]
    pred_path = evalset_root / "_audit_one_prediction.jsonl"
    out_path = evalset_root / "_audit_one_prediction_score.json"
    pred_path.write_text(
        json.dumps({"item_id": item_id(first_answer), "answer": answer_value(first_answer)}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    commands = [
        [sys.executable, str(scorer), "--items", str(evalset_root / "data" / "test.jsonl"), "--predictions", str(pred_path), "--gold", str(evalset_root / "ground_truth" / "answers.jsonl"), "--out", str(out_path)],
        [sys.executable, str(scorer), "--predictions", str(pred_path), "--answers", str(evalset_root / "ground_truth" / "answers.jsonl"), "--output", str(out_path)],
    ]
    findings: list[dict[str, Any]] = []
    ran = False
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=str(evalset_root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        except Exception:
            continue
        if proc.returncode not in (0, 1):
            continue
        ran = True
        payload: dict[str, Any] = {}
        if out_path.is_file():
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        text = proc.stdout + "\n" + proc.stderr
        mean_score = payload.get("mean_score", payload.get("exact_match_accuracy"))
        matched = payload.get("matched_items")
        if len(test_rows) > 1 and proc.returncode == 0 and (mean_score == 1.0 or mean_score == 1) and matched in (None, 1):
            findings.append(
                {
                    "issue": "scorer_allows_partial_predictions_full_score",
                    "severity": "error",
                    "evidence": {"command": command, "score_payload": payload, "stdout_tail": text[-500:]},
                    "recommendation": "Scorer must require exactly one prediction for every benchmark item, reject missing/duplicate/unknown ids, and divide by total gold items.",
                }
            )
            break
    for path in (pred_path, out_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    if not ran:
        findings.append(
            {
                "issue": "scorer_cli_not_auditable",
                "severity": "warning",
                "evidence": {"scorer": str(scorer)},
                "recommendation": "Expose a deterministic scorer CLI supporting --items/--predictions/--gold/--out or documented aliases.",
            }
        )
    return findings


def audit(evalset_root: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    test_rows, test_errors = load_jsonl(evalset_root / "data" / "test.jsonl")
    answer_rows, answer_errors = load_jsonl(evalset_root / "ground_truth" / "answers.jsonl")
    audit_rows, audit_errors = load_jsonl(evalset_root / "ground_truth" / "audit_items_with_answers.jsonl")
    for name, errors in (("test_jsonl", test_errors), ("answers_jsonl", answer_errors)):
        if errors:
            add_failure(failures, f"{name}_parse_error", "error", {"errors": errors[:5]}, "Fix JSONL syntax before packaging.")
    if audit_errors:
        add_failure(failures, "audit_items_missing_or_unreadable", "error", {"errors": audit_errors[:5]}, "Write ground_truth/audit_items_with_answers.jsonl with full audit rows.")

    required_files = ["README.md", "manifest.json", "data/test.jsonl", "ground_truth/answers.jsonl", "ground_truth/audit_items_with_answers.jsonl", "metrics/score_predictions.py"]
    missing_required = [rel for rel in required_files if not (evalset_root / rel).is_file() or (evalset_root / rel).stat().st_size == 0]
    if missing_required:
        add_failure(failures, "required_evalset_files_missing", "error", {"missing": missing_required}, "Package a complete evalset with manifest, scorer, visible data, hidden answers, and audit rows.")
    root_answer_leaks = root_answer_bearing_jsonl_findings(evalset_root)
    if root_answer_leaks:
        add_failure(
            failures,
            "root_answer_bearing_jsonl",
            "error",
            {"files": root_answer_leaks[:20], "count": len(root_answer_leaks)},
            "Do not place answer-bearing dataset/items JSONL at the evalset root. Keep answers only under ground_truth/ or internal Stage4 artifacts.",
        )
    card_path = evalset_root / "cards" / "benchmark_card.md"
    card_text = card_path.read_text(encoding="utf-8", errors="replace") if card_path.is_file() else ""
    missing_card_terms = [term for term in CARD_REQUIRED_TERMS if term not in card_text.casefold()]
    if len(card_text.strip()) < 500 or missing_card_terms:
        add_failure(
            failures,
            "benchmark_card_too_thin",
            "error",
            {"path": str(card_path), "chars": len(card_text.strip()), "missing_terms": missing_card_terms},
            "Benchmark card must document source, tasks, visible/hidden boundary, metric/scorer CLI, limitations, license/usage boundary, and distribution.",
        )

    ids_test = [item_id(row) for row in test_rows]
    ids_answer = [item_id(row) for row in answer_rows]
    if len(set(ids_test)) != len(ids_test):
        add_failure(failures, "duplicate_test_item_ids", "error", {"duplicates": [key for key, count in Counter(ids_test).items() if count > 1][:20]}, "Regenerate stable unique item ids.")
    if set(ids_test) != set(ids_answer):
        add_failure(failures, "test_answer_id_mismatch", "error", {"test_minus_answers": len(set(ids_test) - set(ids_answer)), "answers_minus_test": len(set(ids_answer) - set(ids_test))}, "Ensure test and hidden answer sidecar have the same item ids.")

    answer_by_id = {item_id(row): row for row in answer_rows}
    hidden_key_rows: list[dict[str, Any]] = []
    incomplete_choice_items = 0
    correct_incomplete_items = 0
    normalized_duplicate_items = 0
    nav_relation_mismatch = 0
    shortcut_predictions: list[dict[str, Any]] = []
    image_issue_rows: list[dict[str, Any]] = []
    private_gt_question_leaks: list[dict[str, Any]] = []
    image_hash_scenes: dict[str, set[str]] = defaultdict(set)
    image_use: Counter[str] = Counter()
    for row in test_rows:
        iid = item_id(row)
        bad_keys = sorted(key for key in row if key in HIDDEN_VISIBLE_KEYS or str(key).startswith(("gt_", "gold_")))
        if bad_keys:
            hidden_key_rows.append({"item_id": iid, "keys": bad_keys})
        question = question_text(row)
        if MODEL_VISIBLE_PRIVATE_GT_LEAK_RE.search(question):
            private_gt_question_leaks.append({"item_id": iid, "line": row.get("_line_no"), "question": question[:240]})
        options = option_mapping(row)
        if options:
            normalized = [normalize_choice_surface(value) for value in options.values()]
            if len(normalized) != len(set(normalized)):
                normalized_duplicate_items += 1
            incomplete = [key for key, value in options.items() if INCOMPLETE_CHOICE_RE.search(value.strip())]
            if incomplete:
                incomplete_choice_items += 1
                if len(incomplete) == 1:
                    shortcut_predictions.append({"item_id": iid, "answer": incomplete[0]})
            gold = str(answer_value(answer_by_id.get(iid, {})) or "").strip().upper()
            if gold in options and INCOMPLETE_CHOICE_RE.search(options[gold].strip()):
                correct_incomplete_items += 1
            if NAV_QUESTION_RE.search(question_text(row)) and all(RELATION_CHOICE_RE.search(value) for value in options.values()):
                nav_relation_mismatch += 1
        for raw_path in media_paths(row):
            resolved = resolve_media(evalset_root, raw_path)
            if resolved is None or not resolved.is_file():
                image_issue_rows.append({"item_id": iid, "path": raw_path, "issue": "missing_or_bad_relative_path"})
                continue
            if resolved.is_symlink():
                image_issue_rows.append({"item_id": iid, "path": raw_path, "issue": "symlink"})
                continue
            ok, note = image_decode_ok(resolved)
            if not ok:
                image_issue_rows.append({"item_id": iid, "path": raw_path, "issue": note})
                continue
            quality = image_quality(resolved)
            if quality.get("blank_or_near_blank") or quality.get("tiny_file"):
                image_issue_rows.append({"item_id": iid, "path": raw_path, "issue": "blank_or_tiny_image", "quality": quality})
                continue
            if quality.get("low_information"):
                add_failure(
                    failures,
                    "low_information_image",
                    "warning",
                    {"item_id": iid, "path": raw_path, "quality": quality},
                    "Inspect low-information image; filter unless the benchmark explicitly targets blank/occluded observations.",
                )
            digest = str(resolved)  # path reuse, not content identity
            scene = str(row.get("scene") or row.get("scene_id") or "")
            if scene:
                image_hash_scenes[digest].add(scene)
            image_use[str(resolved.relative_to(evalset_root))] += 1

    if hidden_key_rows:
        add_failure(failures, "model_visible_hidden_keys", "error", {"rows": hidden_key_rows[:20], "count": len(hidden_key_rows)}, "Remove answers, GT, metadata, provenance and audit fields from data/test.jsonl.")
    if private_gt_question_leaks:
        add_failure(
            failures,
            "model_visible_question_leaks_private_gt",
            "error",
            {"rows": private_gt_question_leaks[:20], "count": len(private_gt_question_leaks)},
            "Remove simulator/private GT facts from model-visible questions. Render pose/depth/coordinates/navmesh into visible panels or overlays instead of stating values in text.",
        )
    if correct_incomplete_items:
        add_failure(failures, "gold_answer_is_incomplete_option", "error", {"count": correct_incomplete_items, "total": len(test_rows)}, "Regenerate options so the correct answer has the same complete grammar surface as distractors.")
    if incomplete_choice_items:
        add_failure(failures, "incomplete_option_text", "error", {"count": incomplete_choice_items, "total": len(test_rows)}, "Reject choices ending with dangling spatial prepositions such as 'to the left of' or 'behind'.")
    if shortcut_predictions and len(shortcut_predictions) == len(test_rows):
        add_failure(failures, "surface_form_shortcut_predicts_all_answers", "error", {"count": len(shortcut_predictions)}, "No benchmark should be solvable by selecting a uniquely malformed option.")
    if normalized_duplicate_items:
        add_failure(failures, "normalized_duplicate_options", "error", {"count": normalized_duplicate_items}, "Reject options that become duplicates after removing filler phrases such as 'the target'.")
    if nav_relation_mismatch:
        add_failure(failures, "navigation_question_relation_choice_mismatch", "warning", {"count": nav_relation_mismatch}, "Navigation/path questions should offer route/landmark/action options, not only static relation sentences.")
    if image_issue_rows:
        add_failure(failures, "image_path_or_decode_failure", "error", {"rows": image_issue_rows[:20], "count": len(image_issue_rows)}, "Use real local ./images/... media that can be decoded.")
    cross_scene_hashes = {digest: sorted(scenes) for digest, scenes in image_hash_scenes.items() if len(scenes) > 1}
    if cross_scene_hashes:
        add_failure(failures, "same_image_path_used_for_multiple_scenes", "error", {"groups": list(cross_scene_hashes.values())[:20], "count": len(cross_scene_hashes)}, "Do not reuse the same image path under multiple scene identities. Content duplicates are not checked here.")

    answers_missing_audit = [item_id(row) for row in answer_rows if not any(key in row for key in AUDIT_KEYS)]
    if answers_missing_audit:
        add_failure(failures, "answers_missing_audit_context", "error", {"count": len(answers_missing_audit), "sample": answers_missing_audit[:20]}, "answers.jsonl must include evidence_refs/provenance/metadata or equivalent audit context.")
    if audit_rows and set(item_id(row) for row in audit_rows) != set(ids_test):
        add_failure(failures, "audit_items_id_mismatch", "error", {"audit_count": len(audit_rows), "test_count": len(test_rows)}, "Audit item sidecar must cover every model-visible item.")
    audit_by_id = {item_id(row): row for row in audit_rows}
    processing_manifest = load_processing_manifest_by_filename(evalset_root)
    missing_proof: list[dict[str, Any]] = []
    raw_only_visible_anchor: list[dict[str, Any]] = []
    missing_or_weak_manifest_anchor: list[dict[str, Any]] = []
    weak_private_gt_proof: list[dict[str, Any]] = []
    for row in test_rows:
        iid = item_id(row)
        audit_row = audit_by_id.get(iid, {})
        proof = answerability_proof(audit_row)
        if not proof:
            missing_proof.append({"item_id": iid, "line": row.get("_line_no")})
            continue
        visible_media = proof.get("visible_media") or proof.get("model_visible_media") or media_paths(row)
        if isinstance(visible_media, str):
            visible_media = [visible_media]
        question_refs_anchor = proof.get("question_references_visible_anchor")
        unresolved_proof_media = [path for path in visible_media if not isinstance(path, str) or resolve_media(evalset_root, path) is None or not resolve_media(evalset_root, path).is_file()]
        if not visible_media or unresolved_proof_media or question_refs_anchor is False:
            missing_proof.append({"item_id": iid, "line": row.get("_line_no"), "reason": "proof does not identify resolvable visible media/anchor", "unresolved_media": unresolved_proof_media[:5]})
            continue
        anchor = proof_anchor_type(proof)
        if anchor in RAW_ONLY_ANCHORS or anchor in WEAK_VISIBLE_ANCHORS or anchor not in STRONG_VISIBLE_ANCHORS:
            raw_only_visible_anchor.append(
                {
                    "item_id": iid,
                    "line": row.get("_line_no"),
                    "anchor_type": anchor,
                    "reason": "raw_or_weak_or_unrecognized_visible_anchor",
                    "media": visible_media[:5],
                }
            )
        for media in visible_media:
            if not isinstance(media, str):
                continue
            filename = Path(media).name
            manifest_rows = processing_manifest.get(filename, [])
            manifest_anchors = [manifest_anchor_type(manifest_row) for manifest_row in manifest_rows]
            if not manifest_rows:
                missing_or_weak_manifest_anchor.append(
                    {
                        "item_id": iid,
                        "line": row.get("_line_no"),
                        "media": media,
                        "reason": "missing_processing_manifest_row",
                    }
                )
                continue
            if not any(anchor_name in STRONG_VISIBLE_ANCHORS for anchor_name in manifest_anchors):
                missing_or_weak_manifest_anchor.append(
                    {
                        "item_id": iid,
                        "line": row.get("_line_no"),
                        "media": media,
                        "reason": "manifest_anchor_not_strong_processed",
                        "manifest_anchor_types": manifest_anchors,
                    }
                )
        private_fields = proof_private_fields(proof)
        question_uses_private_terms = bool(PRIVATE_GT_QUESTION_RE.search(question_text(row)))
        if (private_fields & PRIVATE_GT_FIELDS or question_uses_private_terms) and (
            anchor in RAW_ONLY_ANCHORS or anchor in WEAK_VISIBLE_ANCHORS or anchor not in STRONG_VISIBLE_ANCHORS
        ):
            weak_private_gt_proof.append(
                {
                    "item_id": iid,
                    "line": row.get("_line_no"),
                    "anchor_type": anchor,
                    "private_fields": sorted(private_fields),
                    "question": question_text(row)[:200],
                }
            )
    if missing_proof:
        add_failure(
            failures,
            "missing_answerability_proof",
            "error",
            {"rows": missing_proof[:20], "count": len(missing_proof)},
            "Every audit item must state which model-visible media/anchor makes the answer decidable.",
        )
    if weak_private_gt_proof:
        add_failure(
            failures,
            "private_gt_not_rendered_as_visible_anchor",
            "error",
            {"rows": weak_private_gt_proof[:20], "count": len(weak_private_gt_proof)},
            "Questions based on private GT such as pose/depth/coordinates/trajectory/object ids require a visible transform, not raw RGB-only evidence.",
        )
    if raw_only_visible_anchor:
        add_failure(
            failures,
            "evalset_images_not_processed",
            "error",
            {"rows": raw_only_visible_anchor[:20], "count": len(raw_only_visible_anchor)},
            "Every EVALSET_DATASET image must come from a strong processed visible anchor such as bbox_label_overlay, rgb_depth_panel, pose_map_overlay, trajectory_panel, candidate_panel, crop/panel, or region overlay. question_overlay/text bars/raw copies are not acceptable.",
        )
    if missing_or_weak_manifest_anchor:
        add_failure(
            failures,
            "evalset_images_missing_strong_processing_manifest",
            "error",
            {"rows": missing_or_weak_manifest_anchor[:20], "count": len(missing_or_weak_manifest_anchor)},
            "Every final image must have a corresponding image_processing manifest row with a strong composer/visible_asset_type. Metadata strips, frame labels, missing composer fields, and raw copies are not valid.",
        )

    failures.extend(audit_scorer(evalset_root, test_rows, answer_rows))
    severity_counts = Counter(row["severity"] for row in failures)
    status = "FAIL" if severity_counts.get("error", 0) else "PASS"
    return {
        "schema_version": "benchclaw.evalset_quality_audit.v1",
        "status": status,
        "summary": {
            "test_items": len(test_rows),
            "answer_items": len(answer_rows),
            "audit_items": len(audit_rows),
            "unique_images_referenced": len(image_use),
            "failure_count": len(failures),
            "severity_counts": dict(severity_counts),
        },
        "findings": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit packaged BenchClaw EVALSET_DATASET quality.")
    parser.add_argument("--evalset", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = audit(Path(args.evalset).expanduser().resolve())
    if args.out:
        write_json(Path(args.out).expanduser(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
