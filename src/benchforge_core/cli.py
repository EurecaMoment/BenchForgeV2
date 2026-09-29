import argparse
import json
import sys
import subprocess
from .runtime import Runtime, read
from .workbench import OPERATIONS


def main():
    parser = argparse.ArgumentParser(description="Composable BenchClaw capabilities")
    parser.add_argument("tool", choices=["catalog", "status", "plan", "sam3", "yoloe", "depthanything3", "llm_local", "habitat", "libero", "carla", "isaac", "evidence", "build", "evaluate", "method", *OPERATIONS])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--config")
    parser.add_argument("--input", help="JSON request file; '-' reads stdin")
    args = parser.parse_args()
    request = json.load(sys.stdin) if args.input == "-" else read(args.input) if args.input else {}
    runtime = Runtime(args.workspace, read(args.config) if args.config else None)
    try:
        print(json.dumps(runtime.call(args.tool, request), ensure_ascii=False))
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'error':str(error),'workspace':str(runtime.root)},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
