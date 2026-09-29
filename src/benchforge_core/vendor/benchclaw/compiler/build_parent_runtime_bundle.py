#!/usr/bin/env python3
"""Initialize the Stage4 data_20 template/metric/runtime bundle.

The script creates the shared bundle skeleton used by the downstream subskills.
It also writes a strict default one-click runtime so the initialized bundle can
already run smoke generation, deterministic scoring, packaging, and validation.
Downstream subskills or local Qwen may specialize the runtime with
dataset-specific adapters and template functions before contract-checking.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent
STAGE4_DIR = SKILL_DIR
PARENT_RUNTIME = SKILL_DIR / "benchclaw_stage4_synthesis_base.py"
IMAGE_PROCESSOR = SKILL_DIR / "process_answer_images.py"
GREY_METRIC_BASE = SKILL_DIR / "grey_metric_eval_base.py"
VISUAL_MARKER_RUNTIME = SKILL_DIR / "visual_marker_runtime.py"
RUNTIME_WRITER = SKILL_DIR / "write_one_click_runtime.py"
REFERENCE_LIBRARY = SKILL_DIR / "reference_library"
DEFAULT_SCHEMA = SKILL_DIR / "benchmark_item.schema.json"

KNOWN_EVIDENCE_FILES = (
    "evidence_index.jsonl",
    "annotation_records.jsonl",
    "privileged_gt.jsonl",
    "SIMULATOR_DATA.jsonl",
    "media_manifest.jsonl",
    "items.jsonl",
    "dataset.jsonl",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path, limit: int = 200000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
            if len(rows) >= limit:
                break
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def discover_evidence_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    files: List[Path] = []
    for name in KNOWN_EVIDENCE_FILES:
        files.extend(sorted(input_path.rglob(name)))
    seen = set()
    out: List[Path] = []
    for path in files:
        resolved = path.resolve()
        if resolved in seen or "__pycache__" in resolved.parts:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def normalize_evidence(input_path: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    files = discover_evidence_files(input_path)
    evidence_rows: List[Dict[str, Any]] = []
    inventory_rows: List[Dict[str, Any]] = []
    for source_idx, path in enumerate(files):
        source_name = f"source_{source_idx:03d}_{path.stem}"
        rows: List[Dict[str, Any]] = []
        try:
            rows = read_jsonl(path)
        except Exception as exc:
            inventory_rows.append(
                {
                    "source_name": source_name,
                    "source_file": str(path),
                    "artifact_root": str(path.parent),
                    "status": "load_error",
                    "error": repr(exc),
                }
            )
            continue
        inventory_rows.append(
            {
                "source_name": source_name,
                "source_file": str(path),
                "artifact_root": str(path.parent),
                "record_count": len(rows),
                "status": "loaded",
            }
        )
        for row_idx, row in enumerate(rows):
            normalized = dict(row)
            normalized.setdefault("source_name", source_name)
            normalized.setdefault("_source_file", str(path))
            normalized.setdefault("root_dir", str(path.parent))
            normalized.setdefault("record_id", str(row.get("record_id") or row.get("id") or row.get("sample_id") or f"{path.stem}_{row_idx:06d}"))
            normalized.setdefault("sample_id", str(row.get("sample_id") or row.get("item_id") or normalized["record_id"]))
            evidence_rows.append(normalized)
    return evidence_rows, inventory_rows


def flatten_fields(value: Any, prefix: str = "", limit: int = 2000) -> Iterable[tuple[str, Any]]:
    if limit <= 0:
        return
    if isinstance(value, dict):
        for key, sub in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_fields(sub, child, limit - 1)
    elif isinstance(value, list):
        if value:
            yield from flatten_fields(value[0], f"{prefix}[]", limit - 1)
        else:
            yield prefix, []
    else:
        yield prefix, value


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def field_family(field_path: str) -> str:
    text = field_path.lower()
    if any(key in text for key in ("bbox", "mask", "centroid", "area", "x", "y")):
        return "spatial"
    if "depth" in text or "distance" in text:
        return "depth"
    if "category" in text or "class" in text or "label" in text:
        return "label"
    if "count" in text or "number" in text:
        return "count"
    if "image" in text or "media" in text or "path" in text:
        return "media"
    if "time" in text or "frame" in text or "step" in text:
        return "temporal"
    return "other"


def qwen_prompt_safe_example(field_path: str, value: Any) -> str:
    lowered = field_path.lower()
    if any(term in lowered for term in ("answer", "gold", "ground_truth", "target", "correct")):
        return "<redacted_hidden_value>"
    if any(term in lowered for term in ("object_id", "actor_id", "entity_id", "instance_id")):
        return "<object_id>"
    if any(term in lowered for term in ("bbox", "box", "mask", "depth", "area")):
        return f"<{field_family(field_path)}_value>"
    if field_family(field_path) == "media" or any(term in lowered for term in ("path", "file", "dir", "root")):
        return "<media_path>"
    if isinstance(value, (dict, list)):
        return f"<{value_type(value)}>"
    text = str(value)
    if len(text) > 120:
        text = text[:117] + "..."
    return json.dumps(text, ensure_ascii=False, default=str)


def write_field_catalog(path: Path, evidence_rows: Sequence[Dict[str, Any]]) -> None:
    counts: Counter[str] = Counter()
    types: Dict[str, Counter[str]] = {}
    examples: Dict[str, Any] = {}
    for row in evidence_rows[:200]:
        for field_path, value in flatten_fields(row):
            if not field_path:
                continue
            counts[field_path] += 1
            types.setdefault(field_path, Counter())[value_type(value)] += 1
            examples.setdefault(field_path, value if not isinstance(value, (dict, list)) else value_type(value))
    lines = [
        "schema_version: benchclaw.stage4.field_catalog.v1",
        f"generated_at: {now_iso()}",
        "fields:",
    ]
    for field_path, count in sorted(counts.items()):
        type_name = types[field_path].most_common(1)[0][0]
        example = qwen_prompt_safe_example(field_path, examples.get(field_path))
        lines.extend(
            [
                f"  - field_path: {field_path}",
                f"    value_type: {type_name}",
                f"    field_family: {field_family(field_path)}",
                f"    observed_records: {count}",
                f"    qwen_prompt_safe_example: {example[:160]}",
            ]
        )
    write_text(path, "\n".join(lines) + "\n")


def write_traceability(path: Path, inventory_rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_name", "source_file", "artifact_root", "status", "record_count"])
        writer.writeheader()
        for row in inventory_rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames or []})


def smoke_test_script() -> str:
    return '''#!/usr/bin/env python3
"""Smoke tests are generated by contract-checking after runtime code exists."""

from __future__ import annotations


def test_default_runtime_surface() -> None:
    assert True
'''


def write_default_one_click_runtime(bundle: Path) -> None:
    if not RUNTIME_WRITER.is_file():
        raise FileNotFoundError(RUNTIME_WRITER)
    spec = importlib.util.spec_from_file_location("benchclaw_stage4_write_one_click_runtime", RUNTIME_WRITER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runtime writer: {RUNTIME_WRITER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write_runtime(bundle, overwrite_manifests=False)
    copy_file(RUNTIME_WRITER, bundle / "scripts" / "write_one_click_runtime.py")


def build_qwen_prompt(bundle: Path) -> str:
    quality_contract_path = bundle / "reference_library" / "BENCHMARK_QUALITY_CONTRACT.md"
    contract_path = bundle / "reference_library" / "ONE_CLICK_SYNTHESIZER_CONTRACT.md"
    format_contract_path = bundle / "reference_library" / "UNIVERSAL_EVALSET_FORMAT_CONTRACT.md"
    quality_contract_text = quality_contract_path.read_text(encoding="utf-8") if quality_contract_path.is_file() else ""
    contract_text = contract_path.read_text(encoding="utf-8") if contract_path.is_file() else ""
    format_contract_text = format_contract_path.read_text(encoding="utf-8") if format_contract_path.is_file() else ""
    return f"""# Local Qwen Prompt: BenchClaw Stage4 One-click Synthesizer

You are writing dataset-specific runtime code for BenchClaw Stage4.

Read and obey both contracts below. The first contract defines general benchmark
quality; the second defines the one-click runtime surface. Produce complete
Python files for:

- scripts/generate_items.py
- scripts/score_predictions.py
- scripts/package_evalset.py
- scripts/audit_evalset_quality.py
- scripts/check_difficulty_mix.py
- scripts/validate_bundle.py

The code must be a strict one-click evalset synthesizer in the style of
a strict standalone benchmark synthesizer, but it must consume this bundle's
manifests and must not fork the Stage4 DAG.

It must assemble contributor outputs from:

- contrib/gt_adapter/adapter_contract.json
- contrib/asset_builder/asset_builder_contract.json
- contrib/template_registry/template_registry.json
- contrib/metric_registry/metric_registry.json

It must generate canonical audit items and package both:

- Stage5-safe package: data/test.jsonl, images/, ground_truth/, metrics/
- universal audit format: benchmark_items.jsonl, template_registry.json,
  generation_report.json, benchmark_assets/

Bundle path: {bundle}

Required manifest inputs:

- stage4_execution_plan.yaml
- evidence_index.jsonl
- field_catalog.yaml
- gt_kinship/*
- image_processing/image_manifest.jsonl
- template_manifest.jsonl
- metric_manifest.jsonl
- contrib/*/*_contract.json

Reference design summary from uav_spatial_eval_synthesizer.py:

- Every item must follow evidence -> model-visible anchor -> deterministic
  answer -> hidden audit -> deterministic scorer -> package audit.
- Keep a curated template registry instead of broad unsupported templates.
- Normalize raw evidence into small dataclasses before generation.
- Use one deterministic gen_* function per template.
- Generate neutral processed anchors for instance-level questions: bbox labels,
  point labels, crop/panel views, multi-view grids, or trajectory panels.
- For object, region, trajectory, view, step, grounding, ordering, area, depth,
  or candidate templates, bind the question to GT through `visual_marker_policy`
  and processed model-visible assets; question/options must reference those
  visible anchors rather than raw GT ids, bbox fields, or unmarked descriptions.
- Reject duplicate option text, unanswerable questions, bare numeric answers,
  hidden GT terms in questions, malformed/incomplete choice text, normalized
  duplicate choices, shortcut-solvable answer patterns, and ambiguous object
  references.
- Write audit items with answers, then package a model-visible JSONL with
  answers/provenance removed and images copied under ./images/.
- When --audit-format-out is provided, also write the universal audit format
  using the same accepted audit items. Do not copy LIBERO-specific templates
  unless the current dataset plan actually enabled equivalent temporal tasks.
- Run strict validation before accepting every item.

Acceptance commands:

```bash
python -m py_compile scripts/generate_items.py scripts/score_predictions.py scripts/package_evalset.py scripts/audit_evalset_quality.py scripts/check_difficulty_mix.py scripts/validate_bundle.py
python scripts/generate_items.py --bundle . --evidence-index evidence_index.jsonl --out self_test/dry_run_items.jsonl --limit 1 --seed 20260624 --filtered-output self_test/filtered_items.jsonl
python scripts/score_predictions.py --items self_test/dry_run_items.jsonl --predictions self_test/perfect_predictions.jsonl --out self_test/perfect_score_report.json
python scripts/package_evalset.py --bundle . --items self_test/dry_run_items.jsonl --out self_test/package_smoke
python scripts/package_evalset.py --bundle . --items self_test/dry_run_items.jsonl --out self_test/package_smoke --audit-format-out self_test/audit_format_smoke
python scripts/audit_evalset_quality.py --evalset self_test/package_smoke --out self_test/evalset_quality_audit_report.json
```

## Benchmark Quality Contract

{quality_contract_text}

## One-click Runtime Contract

{contract_text}

## Universal Evalset Format Contract

{format_contract_text}
"""


def write_synthesizer_contract(bundle: Path, status: str) -> None:
    write_json(
        bundle / "synthesizer_contract.json",
        {
            "schema_version": "benchclaw.stage4.one_click_synthesizer.v1",
            "status": status,
            "generated_at": now_iso(),
            "references": [
                "reference_library/BENCHMARK_QUALITY_CONTRACT.md",
                "reference_library/ONE_CLICK_SYNTHESIZER_CONTRACT.md",
                "reference_library/UNIVERSAL_EVALSET_FORMAT_CONTRACT.md",
            ],
            "reference": "reference_library/ONE_CLICK_SYNTHESIZER_CONTRACT.md",
            "format_reference": "reference_library/UNIVERSAL_EVALSET_FORMAT_CONTRACT.md",
            "canonical_generator": "scripts/generate_items.py",
            "required_cli": ["--bundle", "--evidence-index", "--out", "--limit", "--seed", "--template-id", "--filtered-output"],
            "consumed_contributors": [
                "contrib/gt_adapter/adapter_contract.json",
                "contrib/asset_builder/asset_builder_contract.json",
                "contrib/template_registry/template_registry.json",
                "contrib/metric_registry/metric_registry.json",
                "contrib/item_validator/item_validator_contract.json",
            ],
            "output_formats": {
                "audit_format": "audit_format/benchmark_items.jsonl + template_registry.json + generation_report.json + benchmark_assets/",
                "stage5_package": "data/test.jsonl + images/ + ground_truth/ + metrics/",
            },
            "qwen_role": "code_author_only",
            "acceptance_gate": "contract-checking",
            "hard_constraints": [
                "deterministic_answers",
                "no_llm_judge_primary_metric",
                "no_model_visible_hidden_gt",
                "neutral_overlays_for_instance_questions",
                "model_visible_anchor_required",
                "hidden_audit_reproducibility_required",
                "perfect_and_negative_scoring_smoke",
                "complete_prediction_set_required",
                "no_surface_form_answer_shortcuts",
                "evalset_quality_audit_pass",
            ],
        },
    )


def write_initial_contributor_contracts(bundle: Path) -> None:
    contracts = {
        "contrib/gt_adapter/adapter_contract.json": {
            "schema_version": "benchclaw.stage4.gt_adapter.v1",
            "status": "initialized",
            "owner_subskill": "gt-kinship-analysis",
            "field_catalog": "field_catalog.yaml",
            "evidence_index": "evidence_index.jsonl",
        },
        "contrib/asset_builder/asset_builder_contract.json": {
            "schema_version": "benchclaw.stage4.asset_builder.v1",
            "status": "initialized",
            "owner_subskill": "answer-image-processing",
            "manifest": "image_processing/image_manifest.jsonl",
            "supported_composers": ["safe_copy", "bbox_label_overlay", "multi_view_grid", "candidate_panel"],
            "final_evalset_eligible_composers": ["bbox_label_overlay", "multi_view_grid", "candidate_panel", "rgb_depth_panel", "pose_map_overlay", "trajectory_panel", "crop_panel", "region_overlay", "heatmap_overlay"],
            "raw_or_weak_composers_forbidden_in_final_evalset": ["safe_copy", "processed_rgb", "direct_copy", "raw_rgb", "rgb", "question_overlay", "text_overlay"],
        },
        "contrib/template_registry/template_registry.json": {
            "schema_version": "benchclaw.stage4.template_registry.v1",
            "status": "initialized",
            "owner_subskill": "template-compilation",
            "templates_source": "template_manifest.jsonl",
        },
        "contrib/metric_registry/metric_registry.json": {
            "schema_version": "benchclaw.stage4.metric_registry.v1",
            "status": "initialized",
            "owner_subskill": "metric-compilation",
            "metrics_source": "metric_manifest.jsonl",
            "scorer_cli": "scripts/score_predictions.py --items <items> --predictions <predictions> --gold <answers> --out <report>",
        },
        "contrib/item_validator/item_validator_contract.json": {
            "schema_version": "benchclaw.stage4.item_validator.v1",
            "status": "initialized",
            "owner_subskill": "contract-checking",
            "validator_surfaces": ["scripts/validate_bundle.py", "scripts/audit_evalset_quality.py"],
        },
    }
    for rel, payload in contracts.items():
        write_json(bundle / rel, payload)


def build_bundle(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    bundle = Path(args.bundle).expanduser().resolve()
    schema = Path(args.schema).expanduser().resolve() if args.schema else DEFAULT_SCHEMA
    if not input_path.exists():
        raise FileNotFoundError(f"input not found: {input_path}")

    for rel in (
        "scripts",
        "contracts",
        "tests",
        "self_test",
        "image_processing/images",
        "gt_kinship",
        "contrib/gt_adapter",
        "contrib/asset_builder",
        "contrib/template_registry",
        "contrib/metric_registry",
        "contrib/item_validator",
    ):
        (bundle / rel).mkdir(parents=True, exist_ok=True)

    evidence_rows, inventory_rows = normalize_evidence(input_path)
    if not evidence_rows:
        raise RuntimeError(f"no evidence records found under {input_path}")

    write_jsonl(bundle / "evidence_index.jsonl", evidence_rows)
    write_jsonl(bundle / "source_inventory.jsonl", inventory_rows)
    write_field_catalog(bundle / "field_catalog.yaml", evidence_rows)
    write_traceability(bundle / "traceability.csv", inventory_rows)
    copy_file(schema, bundle / "contracts" / "benchmark_item.schema.json")
    copy_file(PARENT_RUNTIME, bundle / "scripts" / "benchclaw_stage4_synthesis_base.py")
    copy_file(IMAGE_PROCESSOR, bundle / "scripts" / "process_answer_images.py")
    copy_file(GREY_METRIC_BASE, bundle / "scripts" / "grey_metric_eval_base.py")
    copy_file(VISUAL_MARKER_RUNTIME, bundle / "scripts" / "visual_marker_runtime.py")
    copy_tree(REFERENCE_LIBRARY, bundle / "reference_library")
    write_initial_contributor_contracts(bundle)

    write_json(
        bundle / "difficulty_mix_contract.json",
        {
            "schema_version": "benchclaw.stage4.difficulty_mix.v1",
            "minimum_ratios": {"easy": 0.20, "medium": 0.25, "hard": 0.20},
            "unknown_difficulty_allowed": False,
        },
    )
    write_text(
        bundle / "synthesis_plan.yaml",
        "schema_version: benchclaw.stage4.synthesis_plan.v1\n"
        "status: initialized\n"
        "next_required_subskills:\n"
        "  - gt-kinship-analysis\n"
        "  - answer-image-processing\n"
        "  - template-compilation\n"
        "  - metric-compilation\n"
        "  - answer-program-generation\n"
        "  - contract-checking\n",
    )
    write_jsonl(bundle / "template_manifest.jsonl", [])
    write_jsonl(bundle / "metric_manifest.jsonl", [])
    write_json(
        bundle / "code_manifest.json",
        {
            "schema_version": "benchclaw.stage4.code_manifest.v1",
            "status": "initialized_default_one_click_runtime",
            "generated_at": now_iso(),
            "scripts": {
                "parent_runtime": "scripts/benchclaw_stage4_synthesis_base.py",
                "generate_items": "scripts/generate_items.py",
                "score_predictions": "scripts/score_predictions.py",
                "package_evalset": "scripts/package_evalset.py",
                "audit_evalset_quality": "scripts/audit_evalset_quality.py",
                "check_difficulty_mix": "scripts/check_difficulty_mix.py",
                "validate_bundle": "scripts/validate_bundle.py",
                "one_click_generate_evalset": "scripts/one_click_generate_evalset.py",
            },
        },
    )
    write_synthesizer_contract(bundle, "initialized")
    write_text(bundle / "qwen_one_click_synthesizer_prompt.md", build_qwen_prompt(bundle))
    write_text(
        bundle / "README.md",
        "# data_20_template_metric_code_bundle\n\n"
        "This bundle was initialized by build_parent_runtime_bundle.py. It contains a strict default one-click runtime that downstream Stage4 subskills may specialize with dataset-specific templates, metrics, answer-image artifacts, and self-test reports.\n",
    )
    write_default_one_click_runtime(bundle)
    write_text(bundle / "tests" / "smoke_test.py", smoke_test_script())

    print(
        json.dumps(
            {
                "bundle": str(bundle),
                "evidence_records": len(evidence_rows),
                "source_files": len(inventory_rows),
                "status": "initialized_default_one_click_runtime",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def legacy_build_parent_runtime() -> int:
    """Maintain the old no-argument behavior for local parent-code refreshes."""
    output_dir = SKILL_DIR / "subskills" / "template-compilation" / "parent_code"
    output_dir.mkdir(parents=True, exist_ok=True)
    if not PARENT_RUNTIME.exists():
        raise FileNotFoundError(PARENT_RUNTIME)
    print(f"[build_parent_runtime_bundle] Parent runtime already present: {PARENT_RUNTIME}")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize BenchClaw Stage4 data_20 template/metric/runtime bundle.")
    parser.add_argument("--input", default="", help="Stage3 annotated root or evidence JSONL.")
    parser.add_argument("--bundle", default="", help="Output data_20_template_metric_code_bundle directory.")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Benchmark item schema path.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.input and not args.bundle:
        return legacy_build_parent_runtime()
    if not args.input or not args.bundle:
        raise SystemExit("--input and --bundle are required together")
    return build_bundle(args)


if __name__ == "__main__":
    raise SystemExit(main())
