#!/usr/bin/env python3
"""Run per-template grey-batch synthesis from a data_20 code bundle."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def discover_templates(bundle: Path, explicit: Sequence[str]) -> List[str]:
    if explicit:
        return sorted({x for x in explicit if x})
    candidates: List[str] = []
    for manifest_name in ("template_manifest.jsonl", "metric_manifest.jsonl"):
        for row in load_jsonl(bundle / manifest_name):
            status = str(row.get("status") or row.get("template_status") or "enabled").lower()
            tid = str(row.get("template_id") or row.get("id") or "")
            if tid and status not in {"disabled", "blocked", "fail"}:
                candidates.append(tid)
    if candidates:
        return sorted(set(candidates))
    plan = bundle / "synthesis_plan.yaml"
    if plan.is_file():
        text = plan.read_text(encoding="utf-8")
        candidates.extend(re.findall(r"template_id:\s*([A-Za-z0-9_.:\-]+)", text))
    return sorted(set(candidates))


def default_evidence_index(bundle: Path) -> Optional[Path]:
    for rel in ("evidence_index.jsonl", "source_inventory.jsonl"):
        path = bundle / rel
        if path.is_file():
            return path
    return None


def run_template(
    python_exe: str,
    generator: Path,
    bundle: Path,
    evidence_index: Path,
    out_dir: Path,
    template_id: str,
    limit: int,
    seed: int,
) -> Dict[str, Any]:
    template_dir = out_dir / "per_template" / template_id
    items_path = template_dir / "items.jsonl"
    filtered_path = template_dir / "filtered_items.jsonl"
    stdout_path = template_dir / "stdout.log"
    stderr_path = template_dir / "stderr.log"
    template_dir.mkdir(parents=True, exist_ok=True)

    base_cmd = [
        python_exe,
        str(generator),
        "--bundle",
        str(bundle),
        "--evidence-index",
        str(evidence_index),
        "--out",
        str(items_path),
        "--limit",
        str(limit),
        "--seed",
        str(seed),
        "--template-id",
        template_id,
    ]
    # Many generated scripts support this option per the Stage4 contract.
    cmd = base_cmd + ["--filtered-output", str(filtered_path)]

    started = time.time()
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0 and "filtered-output" in (proc.stderr or "") and "unrecognized" in (proc.stderr or "").lower():
        proc = subprocess.run(base_cmd, text=True, capture_output=True)
        cmd = base_cmd
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    items = load_jsonl(items_path)
    filtered = load_jsonl(filtered_path)
    return {
        "template_id": template_id,
        "status": "pass" if proc.returncode == 0 and items else "fail",
        "returncode": proc.returncode,
        "num_items": len(items),
        "num_filtered": len(filtered),
        "items_path": str(items_path),
        "filtered_path": str(filtered_path),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "duration_sec": round(time.time() - started, 4),
        "command": " ".join(cmd),
    }


def run_all_templates(args: argparse.Namespace) -> None:
    bundle = Path(args.bundle).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    generator = Path(args.generator).expanduser().resolve() if args.generator else bundle / "scripts" / "generate_items.py"
    evidence_index = Path(args.evidence_index).expanduser().resolve() if args.evidence_index else default_evidence_index(bundle)
    if not generator.is_file():
        raise SystemExit(f"Missing generate_items.py: {generator}")
    if evidence_index is None or not evidence_index.is_file():
        raise SystemExit(f"Missing evidence index under bundle, or pass --evidence-index: {bundle}")

    templates = discover_templates(bundle, args.template_id)
    if not templates:
        raise SystemExit("No enabled templates discovered. Pass --template-id explicitly.")

    statuses: List[Dict[str, Any]] = []
    merged_items: List[Dict[str, Any]] = []
    merged_filtered: List[Dict[str, Any]] = []
    for idx, template_id in enumerate(templates):
        status = run_template(
            args.python,
            generator,
            bundle,
            evidence_index,
            out_dir,
            template_id,
            args.limit_per_template,
            args.seed + idx,
        )
        statuses.append(status)
        merged_items.extend(load_jsonl(Path(status["items_path"])))
        merged_filtered.extend(load_jsonl(Path(status["filtered_path"])))

    write_jsonl(out_dir / "generated_items.jsonl", merged_items)
    write_jsonl(out_dir / "filtered_items.jsonl", merged_filtered)
    write_csv(
        out_dir / "template_status.csv",
        statuses,
        ["template_id", "status", "returncode", "num_items", "num_filtered", "items_path", "filtered_path", "duration_sec", "command"],
    )
    write_json(
        out_dir / "synthesis_manifest.json",
        {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bundle": str(bundle),
            "generator": str(generator),
            "evidence_index": str(evidence_index),
            "templates": statuses,
            "outputs": {
                "generated_items": str(out_dir / "generated_items.jsonl"),
                "filtered_items": str(out_dir / "filtered_items.jsonl"),
                "template_status": str(out_dir / "template_status.csv"),
            },
        },
    )
    print(json.dumps({"templates": len(templates), "items": len(merged_items), "filtered": len(merged_filtered)}, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Synthesize grey-batch items per template.")
    p.add_argument("--bundle", required=True, help="data_20_template_metric_code_bundle directory.")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--generator", default="", help="Override generate_items.py path.")
    p.add_argument("--evidence-index", default="")
    p.add_argument("--template-id", action="append", default=[])
    p.add_argument("--limit-per-template", type=int, default=8)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


if __name__ == "__main__":
    run_all_templates(parse_args())
