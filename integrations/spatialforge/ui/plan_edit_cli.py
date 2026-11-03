"""Server-scoped direct plan editing; no inference or new capture submission."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src'))
from benchforge_core.pipelines.plan_edit import save_edit
parser=argparse.ArgumentParser()
parser.add_argument('--workspace',required=True)
parser.add_argument('--session',required=True)
parser.add_argument('--plan',required=True)
args=parser.parse_args()
try:
    body=json.load(sys.stdin)
    print(json.dumps(save_edit(args.workspace,args.session,args.plan,body['assessment'],body.get('split')),ensure_ascii=False))
except (ValueError,KeyError,TypeError) as error:
    print(json.dumps({'error':str(error),'status_code':400},ensure_ascii=False))
