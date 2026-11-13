"""Validate a workbench production submission before sending it to Isaac."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from benchforge_core.pipelines.scene_policy import check_submission

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--route', required=True)
    parser.add_argument('--execution-mode', choices=('production', 'exploration'), default='production')
    parser.add_argument('--policy', type=Path)
    args = parser.parse_args()
    try:
        os.environ['BENCHFORGE_EXECUTION_MODE'] = args.execution_mode
        if args.policy:
            os.environ['BENCHFORGE_SCENE_POLICY'] = str(args.policy.resolve())
        check_submission(args.workspace, args.route, json.load(sys.stdin))
        print(json.dumps({'allowed': True}))
    except (OSError, ValueError) as error:
        print(json.dumps({'allowed': False, 'error': str(error)}))

