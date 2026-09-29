#!/usr/bin/env python3
"""Deprecated compatibility shim.

Stage4 no longer runs this legacy enhancer because it used hardcoded workspace
paths and synthetic/random quality scores. Use:

  skills/template-metric-code-generation/scripts/build_parent_runtime_bundle.py

to generate the unified data_20 bundle, then run contract-checking and grey
validation. This shim deliberately exits non-zero so it cannot silently mutate
artifacts.
"""
from __future__ import annotations
import sys

if __name__ == "__main__":
    print("run_enhancement.py is deprecated; use build_parent_runtime_bundle.py", file=sys.stderr)
    raise SystemExit(2)
