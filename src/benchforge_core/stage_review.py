"""Durable five-minute user review windows, scoped to a DSH conversation."""
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

SECONDS = 300
STAGES = ('S1', 'S2', 'S3', 'S4', 'S5')


def review(workspace, session, action='status', *, stage=None, key=None, artifact=None,
           review_id=None, instruction='', now=None):
    if not session or not re.fullmatch(r'[\w-]{1,160}', session):
        raise ValueError('A valid DSH session is required')
    if action not in ('status', 'open', 'continue', 'pause', 'instruction', 'acknowledge'):
        raise ValueError('Unknown stage review action')
    if action == 'open' and (stage not in STAGES or not key or not artifact):
        raise ValueError('A completed stage, stable key and viewable artifact are required')
    clock = time.time() if now is None else now
    database = Path(workspace) / 'stage-reviews.sqlite'
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, session TEXT, key TEXT, stage TEXT, artifact TEXT, started REAL, deadline REAL, state TEXT, instruction TEXT, UNIQUE(session,key,stage))')
        db.execute('BEGIN IMMEDIATE')
        if action == 'open':
            db.execute('INSERT OR IGNORE INTO reviews(session,key,stage,artifact,started,deadline,state,instruction) VALUES(?,?,?,?,?,?,?,?)',
                       (session,key,stage,str(artifact),clock,clock+SECONDS,'waiting_user',''))
            row = db.execute('SELECT * FROM reviews WHERE session=? AND key=? AND stage=?', (session,key,stage)).fetchone()
        elif review_id is not None:
            row = db.execute('SELECT * FROM reviews WHERE session=? AND id=?', (session,review_id)).fetchone()
            if row is None:
                raise ValueError('Review does not belong to this conversation')
        else:
            row = db.execute('SELECT * FROM reviews WHERE session=? ORDER BY id DESC LIMIT 1', (session,)).fetchone()
        if row is None:
            db.commit()
            return {'state':'none', 'wait_seconds':SECONDS}
        if row['state'] == 'waiting_user' and clock >= row['deadline']:
            db.execute("UPDATE reviews SET state='elapsed' WHERE id=?", (row['id'],))
            row = db.execute('SELECT * FROM reviews WHERE id=?', (row['id'],)).fetchone()
        if action in ('continue', 'pause', 'instruction', 'acknowledge'):
            if action == 'instruction' and not instruction.strip():
                raise ValueError('User instruction must not be empty')
            if action in ('pause','instruction') and row['state'] not in ('waiting_user','paused','needs_input'):
                raise ValueError('This stage review has already ended')
            if action == 'acknowledge' and row['state'] != 'needs_input':
                raise ValueError('No pending instruction to acknowledge')
            state = {'continue':'continued', 'pause':'paused', 'instruction':'needs_input', 'acknowledge':'continued'}[action]
            db.execute('UPDATE reviews SET state=?,instruction=? WHERE id=?',
                       (state,instruction.strip() if action == 'instruction' else row['instruction'],row['id']))
        db.commit()
        result = dict(db.execute('SELECT * FROM reviews WHERE id=?', (row['id'],)).fetchone())
    result.update(review_id=result.pop('id'), remaining_seconds=max(0,round(result['deadline']-clock)),
                  server_time=clock, wait_seconds=SECONDS,
                  can_continue=result['state'] in ('elapsed','continued'))
    result['next'] = ('Apply the saved user instruction before acknowledging or revising the plan.' if result['state']=='needs_input'
                      else 'Use stage_review(action=wait), then resume the existing production when can_continue is true.')
    return result


def gate(workspace, session, stage, key, artifact):
    return review(workspace,session,'open',stage=stage,key=key,artifact=artifact)


def call(args, directory, config=None):
    workspace = str(Path(directory).parents[1])
    session = args.get('_dsh_context',{}).get('session_id')
    action = args.get('action','status')
    options = {k:args[k] for k in ('stage','key','artifact','review_id','instruction') if k in args}
    if action != 'wait':
        return review(workspace,session,action,**options)
    timeout = args.get('timeout_seconds',300)
    if type(timeout) not in (int,float) or not 0 <= timeout <= 300:
        raise ValueError('Wait timeout must be between 0 and 300 seconds')
    end = time.monotonic()+timeout
    while True:
        result = review(workspace,session,'status',review_id=args.get('review_id'))
        if result['state'] != 'waiting_user' or time.monotonic() >= end:
            return result
        time.sleep(min(1,max(0,end-time.monotonic())))
