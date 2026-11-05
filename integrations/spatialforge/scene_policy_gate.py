"""Validate a workbench production submission before sending it to Isaac."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from benchforge_core.pipelines.scene_policy import check_submission

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--route', required=True)
    args = parser.parse_args()
    try:
        check_submission(args.workspace, args.route, json.load(sys.stdin))
        print(json.dumps({'allowed': True}))
    except (OSError, ValueError) as error:
        print(json.dumps({'allowed': False, 'error': str(error)}))

