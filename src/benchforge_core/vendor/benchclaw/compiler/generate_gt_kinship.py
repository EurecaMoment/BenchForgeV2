#!/usr/bin/env python3
"""Default runner for GT kinship analysis.

For project-specific raw collection schemas, generate a new runtime script that
imports `GTKinshipAnalyzerBase` and overrides extraction hooks. Keep this file
as the generic fallback runner.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from gt_kinship_base import GTKinshipAnalyzerBase


class DefaultRawCollectionKinshipAnalyzer(GTKinshipAnalyzerBase):
    """Generic fallback analyzer for JSON/JSONL/YAML/CSV BenchClaw artifacts."""


def infer_workspace_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env_root = os.environ.get("WORKSPACE_ROOT")
    if env_root:
        return Path(env_root).resolve()
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "path_resolution.json").exists() or (candidate / "stage3").exists():
            return candidate
    return cur


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the generic BenchClaw GT kinship analyzer. Generate a subclass for project-specific schemas."
    )
    parser.add_argument("--workspace-root", help="BenchClaw workspace root. Defaults to WORKSPACE_ROOT or cwd ancestry.")
    parser.add_argument("--bundle-dir", help="data_20_template_metric_code_bundle directory. Defaults under WORKSPACE_ROOT/stage4/artifacts.")
    parser.add_argument("--output-dir", help="Output gt_kinship directory. Defaults to BUNDLE_DIR/gt_kinship.")
    parser.add_argument("--input-root", action="append", default=[], help="Additional raw/evidence root to scan. May be repeated.")
    parser.add_argument("--max-records-per-file", type=int, default=5000)
    parser.add_argument("--max-fields-per-record", type=int, default=80)
    parser.add_argument("--max-group-pairs", type=int, default=120)
    parser.add_argument("--max-kinship-pairs", type=int, default=20000)
    parser.add_argument("--max-chains", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_root = infer_workspace_root(args.workspace_root)
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else None
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    input_roots = [Path(p).resolve() for p in args.input_root] if args.input_root else None
    analyzer = DefaultRawCollectionKinshipAnalyzer(
        workspace_root=workspace_root,
        bundle_dir=bundle_dir,
        output_dir=output_dir,
        input_roots=input_roots,
        max_records_per_file=args.max_records_per_file,
        max_fields_per_record=args.max_fields_per_record,
        max_group_pairs=args.max_group_pairs,
        max_kinship_pairs=args.max_kinship_pairs,
        max_chains=args.max_chains,
    )
    summary = analyzer.run()
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
