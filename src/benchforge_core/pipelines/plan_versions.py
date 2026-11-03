"""User-edited plans become the active production contract for one session."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def connection(workspace):
    db=sqlite3.connect(Path(workspace)/'plan-revisions.sqlite',timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS active_plans (session TEXT PRIMARY KEY, plan TEXT, previous TEXT, version INTEGER, pending INTEGER, changes TEXT)')
    return db


def current(workspace,session):
    if not (Path(workspace)/'plan-revisions.sqlite').exists():return None
    with closing(connection(workspace)) as db:
        row=db.execute('SELECT * FROM active_plans WHERE session=?',(session,)).fetchone()
    if not row:return None
    value=dict(row);value['changes']=json.loads(value['changes']);value['pending']=bool(value['pending'])
    return value


def activate(workspace,session,plan,*,expected=None,pending=False,changes=()):
    with closing(connection(workspace)) as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM active_plans WHERE session=?',(session,)).fetchone()
        if expected and old and old['plan']!=expected:
            raise ValueError('The plan changed in another operation. Refresh before saving.')
        if old and old['pending'] and expected!=old['plan']:
            raise ValueError('Read and apply the user-edited plan before replacing it.')
        version=old['version']+1 if old else 1
        db.execute('INSERT OR REPLACE INTO active_plans VALUES(?,?,?,?,?,?)',
                   (session,str(plan),old['plan'] if old else expected,version,int(pending),json.dumps(list(changes))))
        db.commit()
    return current(workspace,session)


def verify_application(active,args):
    if not active or not active['pending']:return
    if args.get('applies_edit')!=active['plan']:
        raise ValueError('Apply the active user-edited plan with applies_edit before saving execution changes.')
    saved=json.loads(Path(active['plan']).read_text(encoding='utf-8'))
    if args.get('assessment')!=saved['assessment'] or args.get('selections')!=saved['selections']:
        raise ValueError('Execution changes must retain the saved user-edited assessment and template allocation.')
    inputs={**args.get('inputs',{}),**{k:args[k] for k in ('seed','split') if k in args}}
    for key in ('seed','split','target_items','scene_selection','target_scene_count'):
        if key in saved['inputs'] and inputs.get(key)!=saved['inputs'][key]:
            raise ValueError('Execution changes must honor the edited '+key)
    previous=json.loads(Path(saved['edit_revision']['base_plan']).read_text(encoding='utf-8'))
    semantic=('objectives','summary','annotations','questions','scoring','quality_gates','execution')
    changed=any(saved['assessment'].get(key)!=previous.get('assessment',{}).get(key) for key in semantic)
    scenes=lambda document:{key:value for key,value in document.get('scenes',{}).items() if key!='target_scene_count'}
    changed=changed or scenes(saved['assessment'])!=scenes(previous.get('assessment',{}))
    coverage=lambda document:[{key:value for key,value in row.items() if key not in ('count','selection_reason')} for row in document.get('coverage',[])]
    dataset=lambda document:{key:value for key,value in document.get('dataset',{}).items() if key not in ('target_items','seed')}
    changed=changed or coverage(saved['assessment'])!=coverage(previous.get('assessment',{})) or dataset(saved['assessment'])!=dataset(previous.get('assessment',{}))
    if changed and args.get('steps')==saved['steps'] and inputs.get('evidence')==saved['inputs'].get('evidence'):
        raise ValueError('Changed production rules require updated executable steps or evidence inputs; repeating the document does not apply them.')
