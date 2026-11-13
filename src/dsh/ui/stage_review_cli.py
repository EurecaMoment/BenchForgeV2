"""Authenticated UI adapter; the server supplies workspace and session scope."""
import argparse
import json
from runtime_paths import use_checkout_core

use_checkout_core()
from benchforge_core.stage_review import review

parser=argparse.ArgumentParser()
parser.add_argument('--workspace',required=True)
parser.add_argument('--session',required=True)
parser.add_argument('--request',default='{}')
args=parser.parse_args()
body=json.loads(args.request)
if body.get('action','status') not in ('status','continue','pause','instruction'):
    raise ValueError('This action is not available from the workbench')
print(json.dumps(review(args.workspace,args.session,body.get('action','status'),
    review_id=body.get('review_id'),instruction=body.get('instruction','')),ensure_ascii=False))
