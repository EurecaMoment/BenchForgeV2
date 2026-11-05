"""User-edited plans become the active production contract for one session."""
import json
import difflib
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from .assessment import validate_assessment


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


def _same(left,right):
    return json.dumps(left,ensure_ascii=False,sort_keys=True,separators=(',',':')) == json.dumps(
        right,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _leaf_changes(before,after,path=''):
    if isinstance(before,dict) and isinstance(after,dict):
        output=[]
        for key in before.keys() | after.keys():
            if '.' in str(key):
                raise ValueError('Assessment keys containing dots cannot be normalized from Markdown')
            child=f'{path}.{key}' if path else str(key)
            if key not in before or key not in after:
                output.append((child,before.get(key),after.get(key)))
            else:
                output.extend(_leaf_changes(before[key],after[key],child))
        return output
    if isinstance(before,list) and isinstance(after,list):
        output=[]
        for index in range(max(len(before),len(after))):
            child=f'{path}.{index}' if path else str(index)
            if index>=len(before) or index>=len(after):
                output.append((child,before[index] if index<len(before) else None,
                               after[index] if index<len(after) else None))
            else:
                output.extend(_leaf_changes(before[index],after[index],child))
        return output
    if not _same(before,after):
        if not path:
            raise ValueError('The complete assessment cannot be replaced as one normalized Markdown change')
        return [(path,before,after)]
    return []


def _private_projection(value,path=''):
    if isinstance(value,dict):
        output={}
        for key,child in value.items():
            child_path=f'{path}.{key}' if path else str(key)
            if key!='authority_source' and re.match(r'^(?:answers?|answer_?key|correct_?answer|reference_?answer|ground_?truth|gt|authority|gold|oracle|token|password|api_?key|solution)(?:_|$)',str(key),re.I):
                output[child_path]=child
            else:
                output.update(_private_projection(child,child_path))
        return output
    if isinstance(value,list):
        output={}
        for index,child in enumerate(value):
            output.update(_private_projection(child,f'{path}.{index}' if path else str(index)))
        return output
    return {}


def _narrative(markdown):
    return re.sub(r'^```assessment-yaml\s*\r?\n.*?^```\s*$', '', markdown or '', flags=re.M|re.S).strip()


def _plain_text(markdown):
    value=_narrative(markdown)
    value=re.sub(r'^\s*#{1,6}\s*', '', value, flags=re.M)
    value=re.sub(r'^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)', '', value, flags=re.M)
    value=re.sub(r'[`*_~]', '', value)
    return ' '.join(value.split())


def _narrative_unmapped(old,new,resolutions):
    if _plain_text(old)==_plain_text(new):
        return False
    old_lines=_narrative(old).splitlines()
    new_lines=_narrative(new).splitlines()
    instructions=[_plain_text(row['instruction']) for row in resolutions]
    unmatched=False
    matcher=difflib.SequenceMatcher(a=old_lines,b=new_lines,autojunk=False)
    for tag,_,_,new_start,new_end in matcher.get_opcodes():
        if tag=='equal':
            continue
        changed=[line.strip() for line in new_lines[new_start:new_end] if line.strip()]
        if not changed or any(not any(_plain_text(line) in instruction for instruction in instructions)
                              for line in changed if _plain_text(line)):
            unmatched=True
    return unmatched


def _check_normalization(saved,previous,args):
    assessment=args.get('assessment')
    if not isinstance(assessment,dict):
        raise ValueError('Markdown normalization requires a complete resolved assessment')
    changes=_leaf_changes(saved['assessment'],assessment)
    rows=args.get('markdown_resolution')
    if not isinstance(rows,list) or len(rows)!=len(changes):
        raise ValueError('markdown_resolution must cover every changed assessment field exactly once')
    by_path={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'path','before','after','instruction'}:
            raise ValueError('Each markdown_resolution item needs path, before, after and instruction')
        path,instruction=row['path'],row['instruction']
        if not isinstance(path,str) or not path or path in by_path:
            raise ValueError('markdown_resolution paths must be unique assessment field paths')
        if not isinstance(instruction,str) or not instruction.strip():
            raise ValueError('Each Markdown normalization needs a non-empty quoted instruction')
        by_path[path]=row
    expected={path:(before,after) for path,before,after in changes}
    if set(by_path)!=set(expected):
        raise ValueError('markdown_resolution paths must match all and only the changed assessment fields')
    narrative=_narrative(saved.get('user_markdown',''))
    previous_narrative=saved.get('edit_revision',{}).get('base_narrative',
        _narrative(previous.get('user_markdown','')))
    for path,(before,after) in expected.items():
        row=by_path[path]
        if not _same(row['before'],before) or not _same(row['after'],after) or _same(before,after):
            raise ValueError('markdown_resolution before/after values do not match '+path)
        if row['instruction'] not in narrative or row['instruction'] in previous_narrative:
            raise ValueError('Each normalization instruction must quote newly added or changed Markdown prose, outside the YAML block')
    if _private_projection(assessment)!=_private_projection(previous.get('assessment',{})):
        raise ValueError('Markdown normalization cannot change protected answer, authority or credential fields')
    inputs={**args.get('inputs',{}),**{key:args[key] for key in ('seed','split','evidence') if key in args}}
    saved_inputs=saved['inputs']
    for key in ('split','scene_selection'):
        if inputs.get(key)!=saved_inputs.get(key):
            raise ValueError('Markdown normalization must honor the saved '+key)
    for key in ('selected_scenes','selection_path','allow_new_scenes'):
        if assessment.get('scenes',{}).get(key)!=previous.get('assessment',{}).get('scenes',{}).get(key):
            raise ValueError('Markdown normalization must preserve assessment.scenes.'+key)
    for key in saved_inputs:
        if key not in ('seed','target_items','target_scene_count','selections','scene_selection','split','evidence') and inputs.get(key)!=saved_inputs.get(key):
            raise ValueError('Markdown normalization must preserve the saved '+key)
    mutable_inputs={'seed','target_items','target_scene_count','selections','scene_selection','split','evidence'}
    if set(inputs)-set(saved_inputs)-mutable_inputs:
        raise ValueError('Markdown normalization cannot introduce new production inputs')
    if inputs.get('selections')!=args.get('selections'):
        raise ValueError('Resolved pipeline inputs.selections must match the validated assessment allocation')
    validate_assessment(assessment,args.get('selections',[]),inputs)
    if args.get('objective')!=assessment.get('summary'):
        raise ValueError('The resolved plan objective must match assessment.summary')
    heading=re.search(r'^#\s+(.+?)\s*$',saved.get('user_markdown',''),re.M)
    if heading and heading.group(1).strip()!=assessment.get('title'):
        raise ValueError('The resolved assessment.title must match the Markdown title')
    if inputs.get('target_scene_count')!=assessment['scenes']['target_scene_count']:
        raise ValueError('Resolved scene count must match assessment.scenes.target_scene_count')
    numeric_prefixes=('coverage.',)
    numeric_paths={'dataset.target_items','dataset.seed','scenes.target_scene_count'}
    only_parameters=bool(expected) and all(path in numeric_paths or path.startswith(numeric_prefixes) and path.endswith('.count')
                        for path in expected)
    unmapped_narrative=_narrative_unmapped(previous_narrative,saved.get('user_markdown',''),rows)
    return rows,only_parameters,unmapped_narrative


def verify_application(active,args):
    if not active or not active['pending']:return
    if args.get('applies_edit')!=active['plan']:
        raise ValueError('Apply the active user-edited plan with applies_edit before saving execution changes.')
    saved=json.loads(Path(active['plan']).read_text(encoding='utf-8'))
    if 'user_markdown' in saved and args.get('user_markdown')!=saved['user_markdown']:
        raise ValueError('Execution changes must retain the complete saved user-edited Markdown document.')
    previous=json.loads(Path(saved['edit_revision']['base_plan']).read_text(encoding='utf-8'))
    normalization=bool(saved.get('edit_revision',{}).get('markdown_normalization'))
    inputs={**args.get('inputs',{}),**{key:args[key] for key in ('seed','split','evidence') if key in args}}
    rows=[];only_parameters=False;unmapped_narrative=False
    if normalization:
        rows,only_parameters,unmapped_narrative=_check_normalization(saved,previous,args)
    else:
        if args.get('assessment')!=saved['assessment'] or args.get('selections')!=saved['selections']:
            raise ValueError('Execution changes must retain the saved user-edited assessment and template allocation.')
        inputs={**args.get('inputs',{}),**{k:args[k] for k in ('seed','split') if k in args}}
        for key in ('seed','split','target_items','scene_selection','target_scene_count'):
            if key in saved['inputs'] and inputs.get(key)!=saved['inputs'][key]:
                raise ValueError('Execution changes must honor the edited '+key)
    semantic=('objectives','summary','annotations','questions','scoring','quality_gates','execution')
    effective_assessment=args.get('assessment',{}) if normalization else saved['assessment']
    changed=any(effective_assessment.get(key)!=previous.get('assessment',{}).get(key) for key in semantic)
    scenes=lambda document:{key:value for key,value in document.get('scenes',{}).items() if key!='target_scene_count'}
    changed=changed or scenes(effective_assessment)!=scenes(previous.get('assessment',{}))
    coverage=lambda document:[{key:value for key,value in row.items() if key not in ('count','selection_reason')} for row in document.get('coverage',[])]
    dataset=lambda document:{key:value for key,value in document.get('dataset',{}).items() if key not in ('target_items','seed')}
    changed=changed or coverage(effective_assessment)!=coverage(previous.get('assessment',{})) or dataset(effective_assessment)!=dataset(previous.get('assessment',{}))
    if changed and args.get('steps')==saved['steps'] and inputs.get('evidence')==saved['inputs'].get('evidence'):
        raise ValueError('Changed production rules require updated executable steps or evidence inputs; repeating the document does not apply them.')
    if normalization:
        steps_changed=args.get('steps')!=saved['steps']
        evidence_changed=inputs.get('evidence')!=saved['inputs'].get('evidence')
        if (unmapped_narrative or (rows and not only_parameters)) and not (steps_changed or evidence_changed):
            raise ValueError('Narrative rules outside resolved production parameters require updated executable steps or evidence inputs.')
        return rows
    if 'user_markdown' in saved:
        markdown_changed=_narrative(saved['user_markdown'])!=_narrative(previous.get('user_markdown',''))
        if markdown_changed and args.get('steps')==saved['steps'] and inputs.get('evidence')==saved['inputs'].get('evidence'):
            raise ValueError('Markdown instructions outside the assessment-yaml block require updated executable steps or evidence inputs.')
    return None
