#!/usr/bin/env python3
"""CDM/IRT analysis for BenchClaw grey-batch validation.

The script intentionally uses only the Python standard library. It consumes
item-level model score files produced by grey_batch_eval.py or equivalent CSV /
JSONL files, builds a model-by-item response matrix, and writes:

- item_parameters.csv
- model_ability.csv
- capability_mastery.csv
- item_level_findings.jsonl
- cdm_irt_summary.json
- cdm_irt_report.md

The IRT estimates are conservative Rasch-style proxy estimates. They are useful
for grey-batch diagnostics, not a replacement for a full production IRT fit
with large respondent and item counts.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCORE_FILE_PATTERNS = (
    "*score_items.jsonl",
    "*score_items.csv",
    "score_items.jsonl",
    "score_items.csv",
    "scores/*.jsonl",
    "scores/*.csv",
)

ID_KEYS = ("eval_id", "item_id", "id", "question_id")
MODEL_KEYS = ("model", "model_id", "model_name", "predictor", "system")
TIER_KEYS = ("tier", "model_tier", "difficulty_tier", "group")
SCORE_KEYS = ("score", "accuracy", "correct", "is_correct", "passed")
TEMPLATE_KEYS = ("template_id", "template", "template_name")
FORMAT_KEYS = ("question_format", "answer_format_id", "answer_format", "format")
ANSWER_TYPE_KEYS = ("answer_type", "answer_kind")
CAPABILITY_KEYS = ("capability_tags", "capability", "capabilities", "skills", "skill_tags")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(obj)
    return rows


def load_csv(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_rows(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return load_jsonl(path)
    if suffix == ".csv":
        return load_csv(path)
    raise ValueError(f"Unsupported input format: {path}")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def first_value(row: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def nested_get(row: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = row
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)
    text = str(value).strip().casefold()
    if text in {"true", "yes", "y", "correct", "pass", "passed"}:
        return 1.0
    if text in {"false", "no", "n", "incorrect", "fail", "failed"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def as_list(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, dict):
        return [str(k).strip() for k, v in value.items() if v and str(k).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            return as_list(parsed)
        except Exception:
            pass
    return [part.strip() for part in text.replace(";", ",").replace("|", ",").split(",") if part.strip()]


def safe_mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def safe_stdev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(vx * vy)


def logit(p: float) -> float:
    eps = 1e-6
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


def discover_score_files(values: Sequence[str], roots: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for value in values:
        for match in glob.glob(value, recursive=True):
            path = Path(match).expanduser()
            if path.is_file():
                files.append(path.resolve())
    for root_value in roots:
        root = Path(root_value).expanduser().resolve()
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for pattern in SCORE_FILE_PATTERNS:
            files.extend(path.resolve() for path in root.glob(pattern) if path.is_file())
    seen = set()
    out: List[Path] = []
    for path in files:
        if path not in seen and path.suffix.lower() in {".jsonl", ".csv"}:
            out.append(path)
            seen.add(path)
    return out


def load_item_metadata(paths: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    for value in paths:
        path = Path(value).expanduser()
        if not path.is_file():
            continue
        for row in load_rows(path):
            item_id = str(first_value(row, ID_KEYS, "") or "")
            if not item_id:
                continue
            metadata[item_id] = row
            base_id = str(row.get("id") or row.get("item_id") or "")
            if base_id and base_id not in metadata:
                metadata[base_id] = row
    return metadata


def score_record_from_row(row: Dict[str, Any], source_file: Path, row_index: int) -> Optional[Dict[str, Any]]:
    item_id = str(first_value(row, ID_KEYS, "") or "")
    score = first_value(row, SCORE_KEYS, None)
    score_value = coerce_float(score)
    if not item_id or score_value is None:
        return None
    model = str(first_value(row, MODEL_KEYS, "") or "")
    if not model:
        parent_hint = source_file.stem.replace("_score_items", "")
        model = parent_hint or "UNKNOWN_MODEL"
    tier = str(first_value(row, TIER_KEYS, "") or "")
    return {
        "item_id": item_id,
        "model": model,
        "tier": tier,
        "score": max(0.0, min(1.0, score_value)),
        "template_id": str(first_value(row, TEMPLATE_KEYS, "") or ""),
        "question_format": str(first_value(row, FORMAT_KEYS, "") or ""),
        "answer_type": str(first_value(row, ANSWER_TYPE_KEYS, "") or ""),
        "source_file": str(source_file),
        "row_index": row_index,
        "raw": row,
    }


def merge_metadata(records: List[Dict[str, Any]], item_meta: Dict[str, Dict[str, Any]]) -> None:
    for rec in records:
        meta = item_meta.get(rec["item_id"]) or item_meta.get(str((rec.get("raw") or {}).get("id") or ""))
        if not meta:
            continue
        if not rec.get("template_id"):
            rec["template_id"] = str(first_value(meta, TEMPLATE_KEYS, "") or "")
        if not rec.get("question_format"):
            rec["question_format"] = str(first_value(meta, FORMAT_KEYS, "") or "")
        if not rec.get("answer_type"):
            rec["answer_type"] = str(first_value(meta, ANSWER_TYPE_KEYS, "") or "")
        rec["capabilities"] = capabilities_of(meta)


def capabilities_of(row: Dict[str, Any]) -> List[str]:
    caps: List[str] = []
    for key in CAPABILITY_KEYS:
        caps.extend(as_list(row.get(key)))
    meta = row.get("metadata")
    if isinstance(meta, dict):
        for key in CAPABILITY_KEYS:
            caps.extend(as_list(meta.get(key)))
    caps.extend(as_list(nested_get(row, "grey_eval.capability")))
    # Deduplicate while preserving order.
    seen = set()
    out: List[str] = []
    for cap in caps:
        cap = cap.strip()
        if cap and cap not in seen:
            out.append(cap)
            seen.add(cap)
    return out


def build_records(score_files: Sequence[Path], item_meta: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in score_files:
        for idx, row in enumerate(load_rows(path), 1):
            rec = score_record_from_row(row, path, idx)
            if rec:
                records.append(rec)
    merge_metadata(records, item_meta)
    for rec in records:
        if not rec.get("capabilities"):
            fallback = rec.get("question_format") or rec.get("template_id") or "UNKNOWN_CAPABILITY"
            rec["capabilities"] = [str(fallback)]
    return records


def response_tables(records: Sequence[Dict[str, Any]], threshold: float) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, int]]]:
    partial: Dict[str, Dict[str, float]] = defaultdict(dict)
    binary: Dict[str, Dict[str, int]] = defaultdict(dict)
    # If duplicate model-item rows exist, keep the last deterministic sorted record.
    for rec in sorted(records, key=lambda x: (x["model"], x["item_id"], x["source_file"], x["row_index"])):
        model = rec["model"]
        item = rec["item_id"]
        score = float(rec["score"])
        partial[model][item] = score
        binary[model][item] = 1 if score >= threshold else 0
    return partial, binary


def item_metadata(records: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    meta: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        item = rec["item_id"]
        if item not in meta:
            meta[item] = {
                "item_id": item,
                "template_id": rec.get("template_id") or "UNKNOWN",
                "question_format": rec.get("question_format") or "UNKNOWN",
                "answer_type": rec.get("answer_type") or "UNKNOWN",
                "capabilities": rec.get("capabilities") or [],
            }
    return meta


def model_ability_rows(partial: Dict[str, Dict[str, float]], binary: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    means: List[float] = []
    for model, scores in partial.items():
        if scores:
            means.append(sum(scores.values()) / len(scores))
    global_mean = safe_mean(means) or 0.0
    global_sd = safe_stdev(means) or 0.0
    for model in sorted(partial):
        scores = list(partial[model].values())
        bits = list(binary[model].values())
        n = len(scores)
        correct = sum(bits)
        mean_score = safe_mean(scores) or 0.0
        theta = logit((correct + 0.5) / (n + 1.0)) if n else 0.0
        rows.append(
            {
                "model": model,
                "n_items": n,
                "mean_score": round(mean_score, 6),
                "binary_accuracy": round(correct / n, 6) if n else "",
                "rasch_theta_proxy": round(theta, 6),
                "z_score": round((mean_score - global_mean) / global_sd, 6) if global_sd else "",
            }
        )
    return rows


def item_parameter_rows(
    partial: Dict[str, Dict[str, float]],
    binary: Dict[str, Dict[str, int]],
    meta: Dict[str, Dict[str, Any]],
    low_discrimination: float,
) -> List[Dict[str, Any]]:
    models = sorted(partial)
    total_scores: Dict[str, float] = {
        model: sum(partial[model].values()) / len(partial[model]) if partial[model] else 0.0
        for model in models
    }
    rows: List[Dict[str, Any]] = []
    for item in sorted(meta):
        score_pairs = [(model, partial[model][item]) for model in models if item in partial[model]]
        bit_pairs = [(model, binary[model][item]) for model in models if item in binary[model]]
        scores = [score for _, score in score_pairs]
        bits = [bit for _, bit in bit_pairs]
        n = len(scores)
        p_partial = safe_mean(scores)
        p_binary = safe_mean([float(x) for x in bits])
        total_without = []
        item_bits = []
        for model, bit in bit_pairs:
            own = partial[model].get(item, 0.0)
            denom = max(1, len(partial[model]) - 1)
            total_without.append((sum(partial[model].values()) - own) / denom)
            item_bits.append(float(bit))
        discr = pearson(item_bits, total_without)
        difficulty = -logit((sum(bits) + 0.5) / (len(bits) + 1.0)) if bits else None
        flags = []
        if n < 3:
            flags.append("too_few_model_responses")
        if p_binary is not None and p_binary >= 0.95:
            flags.append("too_easy")
        if p_binary is not None and p_binary <= 0.05:
            flags.append("too_hard")
        if discr is not None and discr < 0:
            flags.append("negative_discrimination")
        elif discr is not None and discr < low_discrimination:
            flags.append("low_discrimination")
        if discr is None:
            flags.append("discrimination_unestimated")
        m = meta[item]
        rows.append(
            {
                "item_id": item,
                "template_id": m.get("template_id", "UNKNOWN"),
                "question_format": m.get("question_format", "UNKNOWN"),
                "answer_type": m.get("answer_type", "UNKNOWN"),
                "capabilities": ",".join(m.get("capabilities") or []),
                "n_model_responses": n,
                "mean_score": round(p_partial, 6) if p_partial is not None else "",
                "p_value_binary": round(p_binary, 6) if p_binary is not None else "",
                "rasch_difficulty_proxy": round(difficulty, 6) if difficulty is not None else "",
                "point_biserial_discrimination": round(discr, 6) if discr is not None else "",
                "flags": ",".join(flags),
            }
        )
    return rows


def capability_rows(
    partial: Dict[str, Dict[str, float]],
    binary: Dict[str, Dict[str, int]],
    meta: Dict[str, Dict[str, Any]],
    mastery_threshold: float,
) -> List[Dict[str, Any]]:
    cap_items: Dict[str, List[str]] = defaultdict(list)
    for item, m in meta.items():
        caps = m.get("capabilities") or [m.get("question_format") or m.get("template_id") or "UNKNOWN"]
        for cap in caps:
            cap_items[str(cap)].append(item)
    rows: List[Dict[str, Any]] = []
    for model in sorted(partial):
        for cap in sorted(cap_items):
            items = [item for item in cap_items[cap] if item in partial[model]]
            scores = [partial[model][item] for item in items]
            bits = [binary[model][item] for item in items if item in binary[model]]
            mean_score = safe_mean(scores)
            mastery = (mean_score is not None and mean_score >= mastery_threshold)
            rows.append(
                {
                    "model": model,
                    "capability": cap,
                    "n_items": len(items),
                    "mean_score": round(mean_score, 6) if mean_score is not None else "",
                    "binary_accuracy": round(sum(bits) / len(bits), 6) if bits else "",
                    "mastery_threshold": mastery_threshold,
                    "mastery_status": "mastered" if mastery else "not_mastered",
                }
            )
    return rows


def template_rows(item_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in item_rows:
        groups[str(row.get("template_id") or "UNKNOWN")].append(row)
    rows: List[Dict[str, Any]] = []
    for template_id, group in sorted(groups.items()):
        p_values = [float(r["p_value_binary"]) for r in group if r.get("p_value_binary") not in ("", None)]
        discr_values = [
            float(r["point_biserial_discrimination"])
            for r in group
            if r.get("point_biserial_discrimination") not in ("", None)
        ]
        flag_counter = Counter()
        for row in group:
            for flag in str(row.get("flags") or "").split(","):
                if flag:
                    flag_counter[flag] += 1
        rows.append(
            {
                "template_id": template_id,
                "n_items": len(group),
                "mean_p_value": round(safe_mean(p_values) or 0.0, 6) if p_values else "",
                "mean_discrimination": round(safe_mean(discr_values) or 0.0, 6) if discr_values else "",
                "flag_summary": json.dumps(dict(flag_counter), ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def findings_from_items(item_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for row in item_rows:
        flags = [flag for flag in str(row.get("flags") or "").split(",") if flag]
        for flag in flags:
            severity = "warning"
            if flag in {"negative_discrimination", "too_few_model_responses"}:
                severity = "error"
            findings.append(
                {
                    "finding_type": "cdm_irt_item_diagnostic",
                    "severity": severity,
                    "item_id": row.get("item_id"),
                    "template_id": row.get("template_id"),
                    "question_format": row.get("question_format"),
                    "issue": flag,
                    "evidence": {
                        "p_value_binary": row.get("p_value_binary"),
                        "point_biserial_discrimination": row.get("point_biserial_discrimination"),
                        "n_model_responses": row.get("n_model_responses"),
                    },
                    "recommendation": recommendation_for_flag(flag),
                }
            )
    return findings


def recommendation_for_flag(flag: str) -> str:
    if flag == "too_easy":
        return "Increase distractor strength or use harder evidence cases before full synthesis."
    if flag == "too_hard":
        return "Check answer derivation, image visibility, and question wording; keep only if intentionally difficult."
    if flag == "negative_discrimination":
        return "Review GT, scoring, and ambiguity; high-ability models are underperforming low-ability models on this item."
    if flag == "low_discrimination":
        return "Prefer items with clearer capability signal or stronger contrast between models."
    if flag == "too_few_model_responses":
        return "Collect more model responses before interpreting IRT/CDM statistics."
    return "Review item before full synthesis."


def analysis_status(n_models: int, n_items: int, n_records: int, min_models: int, min_items: int) -> Dict[str, Any]:
    warnings: List[str] = []
    if n_models < min_models:
        warnings.append(f"Only {n_models} models/respondents; IRT estimates are diagnostic only.")
    if n_items < min_items:
        warnings.append(f"Only {n_items} items; item parameter estimates are unstable.")
    if n_records == 0:
        warnings.append("No usable score records were found.")
    return {
        "usable_for_full_irt": n_models >= min_models and n_items >= min_items and n_records > 0,
        "n_models": n_models,
        "n_items": n_items,
        "n_score_records": n_records,
        "minimum_recommended_models": min_models,
        "minimum_recommended_items": min_items,
        "warnings": warnings,
        "method": "Rasch proxy estimates + point-biserial item discrimination + capability mastery aggregation",
    }


def write_report(
    path: Path,
    status: Dict[str, Any],
    item_rows: Sequence[Dict[str, Any]],
    model_rows: Sequence[Dict[str, Any]],
    capability_rows_data: Sequence[Dict[str, Any]],
) -> None:
    flagged = sum(1 for row in item_rows if row.get("flags"))
    best_models = sorted(model_rows, key=lambda r: float(r.get("mean_score") or 0.0), reverse=True)[:5]
    top_caps = sorted(
        capability_rows_data,
        key=lambda r: (str(r.get("capability")), -float(r.get("mean_score") or 0.0)),
    )[:10]
    lines = [
        "# CDM/IRT Grey-Batch Analysis",
        "",
        "## Status",
        "",
        f"- usable_for_full_irt: `{status['usable_for_full_irt']}`",
        f"- models/respondents: `{status['n_models']}`",
        f"- items: `{status['n_items']}`",
        f"- score records: `{status['n_score_records']}`",
        f"- method: {status['method']}",
        "",
    ]
    if status["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in status["warnings"])
        lines.append("")
    lines.extend(
        [
            "## Item Diagnostics",
            "",
            f"- flagged_items: `{flagged}`",
            "- See `item_parameters.csv` and `item_level_findings.jsonl`.",
            "",
            "## Top Model Ability Proxies",
            "",
        ]
    )
    for row in best_models:
        lines.append(f"- {row['model']}: mean_score={row['mean_score']}, theta={row['rasch_theta_proxy']}")
    lines.extend(["", "## Capability Mastery Sample", ""])
    for row in top_caps:
        lines.append(
            f"- {row['model']} / {row['capability']}: mean_score={row['mean_score']}, status={row['mastery_status']}"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run CDM/IRT diagnostics over grey-batch item-level model scores.")
    p.add_argument("--scores", action="append", default=[], help="Score file path or glob. May be repeated.")
    p.add_argument("--score-root", action="append", default=[], help="Directory to search for score item files. May be repeated.")
    p.add_argument("--items", action="append", default=[], help="Optional gold/generated items JSONL/CSV for metadata.")
    p.add_argument("--out-dir", required=True, help="Output directory.")
    p.add_argument("--threshold", type=float, default=0.5, help="Score threshold used to binarize item responses.")
    p.add_argument("--min-models", type=int, default=5)
    p.add_argument("--min-items", type=int, default=30)
    p.add_argument("--mastery-threshold", type=float, default=0.7)
    p.add_argument("--low-discrimination", type=float, default=0.1)
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    score_files = discover_score_files(args.scores, args.score_root)
    item_meta = load_item_metadata(args.items)
    records = build_records(score_files, item_meta)
    partial, binary = response_tables(records, args.threshold)
    meta = item_metadata(records)

    item_rows = item_parameter_rows(partial, binary, meta, args.low_discrimination)
    model_rows = model_ability_rows(partial, binary)
    cap_rows = capability_rows(partial, binary, meta, args.mastery_threshold)
    tmpl_rows = template_rows(item_rows)
    findings = findings_from_items(item_rows)
    status = analysis_status(len(partial), len(meta), len(records), args.min_models, args.min_items)

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "inputs": {
            "score_files": [str(path) for path in score_files],
            "item_metadata_files": args.items,
            "threshold": args.threshold,
        },
        "status": status,
        "counts": {
            "models": len(partial),
            "items": len(meta),
            "score_records": len(records),
            "flagged_items": sum(1 for row in item_rows if row.get("flags")),
            "findings": len(findings),
        },
        "outputs": {
            "item_parameters": str(out_dir / "item_parameters.csv"),
            "model_ability": str(out_dir / "model_ability.csv"),
            "capability_mastery": str(out_dir / "capability_mastery.csv"),
            "template_diagnostics": str(out_dir / "template_diagnostics.csv"),
            "item_level_findings": str(out_dir / "item_level_findings.jsonl"),
            "report": str(out_dir / "cdm_irt_report.md"),
        },
    }

    write_csv(
        out_dir / "item_parameters.csv",
        item_rows,
        [
            "item_id",
            "template_id",
            "question_format",
            "answer_type",
            "capabilities",
            "n_model_responses",
            "mean_score",
            "p_value_binary",
            "rasch_difficulty_proxy",
            "point_biserial_discrimination",
            "flags",
        ],
    )
    write_csv(out_dir / "model_ability.csv", model_rows, ["model", "n_items", "mean_score", "binary_accuracy", "rasch_theta_proxy", "z_score"])
    write_csv(out_dir / "capability_mastery.csv", cap_rows, ["model", "capability", "n_items", "mean_score", "binary_accuracy", "mastery_threshold", "mastery_status"])
    write_csv(out_dir / "template_diagnostics.csv", tmpl_rows, ["template_id", "n_items", "mean_p_value", "mean_discrimination", "flag_summary"])
    write_jsonl(out_dir / "item_level_findings.jsonl", findings)
    status_label = "PASS" if status.get("usable_for_full_irt") else "LIMITED_PASS" if records else "FAIL"
    status_payload = {
        "status": status_label,
        "usable_for_full_irt": bool(status.get("usable_for_full_irt")),
        "n_models": status.get("n_models"),
        "n_items": status.get("n_items"),
        "n_score_records": status.get("n_score_records"),
        "warnings": status.get("warnings", []),
        "matrix_source": "proxy_or_external_score_matrix",
    }
    write_json(out_dir / "status.json", status_payload)
    write_json(out_dir / "cdm_irt_summary.json", summary)
    write_report(out_dir / "cdm_irt_report.md", status, item_rows, model_rows, cap_rows)

    print(json.dumps({"out_dir": str(out_dir), **summary["counts"], "usable_for_full_irt": status["usable_for_full_irt"], "status": status_label}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
