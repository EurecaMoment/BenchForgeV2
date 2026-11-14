"""Server-scoped direct plan editing; no inference or new capture submission."""
import argparse
import json
import sys


sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
from server.plan_edit import save_edit
parser=argparse.ArgumentParser()
parser.add_argument('--workspace',required=True)
parser.add_argument('--session',required=True)
parser.add_argument('--plan',required=True)
args=parser.parse_args()
try:
    body=json.load(sys.stdin)
    print(json.dumps(save_edit(args.workspace,args.session,args.plan,body.get('assessment'),body.get('split'),
                              markdown=body.get('markdown'),base_markdown=body.get('base_markdown')),ensure_ascii=False))
except (ValueError,KeyError,TypeError) as error:
    print(json.dumps({'error':str(error),'status_code':400},ensure_ascii=False))
