"""Expose the benchmark stages and review tool arguments."""
import time
from pathlib import Path

from storage.stage_reviews import review

STAGES = ('S1', 'S2', 'S3', 'S4', 'S5')


def call(args, directory, config=None):
    workspace = str(Path(directory).parents[1])
    session = args.get('_dsh_context',{}).get('session_id')
    action = args.get('action','status')
    options = {k:args[k] for k in ('stage','key','artifact','review_id','instruction') if k in args}
    if action == 'open' and options.get('stage') not in STAGES:
        raise ValueError('A completed stage, stable key and viewable artifact are required')
    if action != 'wait':
        return review(workspace,session,action,**options)
    timeout = args.get('timeout_seconds',60)
    if type(timeout) not in (int,float) or not 0 <= timeout <= 300:
        raise ValueError('Wait timeout must be between 0 and 300 seconds')
    end = time.monotonic()+timeout
    while True:
        result = review(workspace,session,'status',review_id=args.get('review_id'))
        if result['state'] != 'waiting_user' or time.monotonic() >= end:
            return result
        time.sleep(min(1,max(0,end-time.monotonic())))
