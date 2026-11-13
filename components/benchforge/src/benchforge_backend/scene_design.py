"""Resolve model-declared simplifications from a saved scene production plan."""
import json
import math
from pathlib import Path
import re

DETAIL_FIELDS = ('purpose', 'reason', 'simplifications', 'retained_constraints', 'excluded_claims')


def path_is_excluded(path, policy):
    source = Path(path).resolve()
    return any(source.is_relative_to(Path(root).resolve()) for root in policy.get('excluded_paths', []))


def references_excluded_source(value, policy):
    if isinstance(value, dict):
        return any(references_excluded_source(child, policy) for child in value.values())
    if isinstance(value, list):
        return any(references_excluded_source(child, policy) for child in value)
    if not isinstance(value, str):
        return False
    return (
        any(value in policy.get(field, ()) for field in ('excluded_tasks', 'excluded_runs', 'excluded_scene_groups'))
        or Path(value).is_absolute() and path_is_excluded(value, policy)
    )


def canonical_schema(value):
    """Read a saved schema identifier under its current product name."""
    if isinstance(value, str) and value.startswith('spatialforge.'):
        return 'benchforge.' + value.removeprefix('spatialforge.')
    return value


def validate_geometry_declarations(scenes):
    declarations = scenes.get('geometry_exceptions', [])
    if not isinstance(declarations, list):
        raise ValueError('scenes.geometry_exceptions must be an optional array')
    designs = scenes.get('designs', [])
    if not isinstance(designs, list) or any(not isinstance(row, dict) for row in designs):
        raise ValueError('scenes.designs must contain scene designs')
    design_ids = {row.get('id') for row in designs}
    seen = set()
    for value in declarations:
        if not isinstance(value, dict):
            raise ValueError('Geometry declarations must be objects')
        design, scene = value.get('scene_design_id'), value.get('scene_id')
        if not isinstance(design, str) or design not in design_ids or not isinstance(scene, str) or not scene.strip():
            raise ValueError('Geometry declaration must identify a declared design and exact scene')
        if (design, scene) in seen:
            raise ValueError('Declare one geometry exception for this scene')
        seen.add((design, scene))
        for key in DETAIL_FIELDS:
            if (not isinstance(value.get(key), str) or not value[key].strip() or
                    value[key].strip().casefold() in {'无', 'none', 'todo', 'tbd', '待填写', 'n/a'}):
                raise ValueError('Geometry exception needs concrete ' + key + ' in the scene plan')
        ids = value.get('object_ids')
        if (not isinstance(ids, list) or not ids or
                not all(isinstance(item, str) and item.strip() for item in ids) or len(set(ids)) != len(ids)):
            raise ValueError('Geometry exception must name the exact simplified objects in this scene')
    return declarations


def saved_design(program, policy=None):
    references = [row for row in program.get('provenance', {}).get('sources', [])
                  if isinstance(row, dict) and row.get('kind') == 'scene_plan']
    if not references:
        return None
    if len(references) != 1:
        raise ValueError('Reference one saved scene production plan')
    reference = references[0]
    if not isinstance(reference.get('path'), str):
        raise ValueError('Scene plan needs its saved absolute path')
    path = Path(reference['path'])
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Scene plan must be an existing saved JSON document')
    if policy and path_is_excluded(path, policy):
        raise ValueError('Removed scene plans cannot declare a new geometry exception')
    plan = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(plan, dict):
        raise ValueError('Reference a saved assessment scene plan')
    assessment = plan.get('assessment', plan)
    if not isinstance(assessment, dict) or canonical_schema(assessment.get('schema')) != 'benchforge.assessment/v1':
        raise ValueError('Reference a saved assessment scene plan')
    scenes = assessment.get('scenes', {})
    if not isinstance(scenes, dict):
        raise ValueError('Saved scene plan needs scenes')
    validate_geometry_declarations(scenes)
    design = reference.get('scene_design_id')
    if not isinstance(design, str) or design not in {row.get('id') for row in scenes.get('designs', [])}:
        raise ValueError('Scene plan reference must identify its scene design')
    return scenes, next(row for row in scenes['designs'] if row['id'] == design), path


def geometry_exception(program, policy=None):
    saved = saved_design(program, policy)
    if not saved:return None
    scenes, design, path = saved
    matched = [row for row in scenes.get('geometry_exceptions', []) if row['scene_design_id'] == design['id'] and row['scene_id'] == program.get('scene_id')]
    if not matched:
        return None
    value = matched[0]
    if not set(value['object_ids']) <= {obj['id'] for obj in program['objects']}:
        raise ValueError('Geometry exception must name the exact simplified objects in this scene')
    return {**value, 'plan_path': str(path.resolve()), 'plan_version': [path.stat().st_size, path.stat().st_mtime_ns],
            'scene_style': 'simplified_geometry', 'authority': 'model-declared experimental design, not physical evidence'}


_REVIEW_DIRECTIONS = {'left', 'right', 'front', 'back', 'above', 'below'}


def _review_reference_vector(value, name):
    if (not isinstance(value, (list, tuple)) or len(value) != 3 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)):
        raise ValueError(name + ' needs three finite coordinates')
    return tuple(float(v) for v in value)


def _review_reference_dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _review_reference_unit(a, name):
    length = math.sqrt(_review_reference_dot(a, a))
    if length <= 1e-8:
        raise ValueError(name + ' is degenerate')
    return tuple(v/length for v in a)


def validate_reference(design, object_ids=None):
    reference = design.get('spatial_reference')
    if reference is None:
        return None
    if isinstance(reference, str):
        if not reference.strip():
            raise ValueError('spatial_reference text must define a concrete reference')
        return reference
    if not isinstance(reference, dict) or canonical_schema(reference.get('schema')) != 'benchforge.review-reference/v1':
        raise ValueError('spatial_reference needs text or benchforge.review-reference/v1')
    up = _review_reference_unit(_review_reference_vector(reference.get('world_up'), 'world_up'), 'world_up')
    frames = reference.get('frames')
    if not isinstance(frames, list) or not frames:
        raise ValueError('spatial_reference needs explicitly named frames')
    by_id = {}
    for frame in frames:
        if (not isinstance(frame, dict) or not isinstance(frame.get('id'), str) or not frame['id'].strip() or
                frame['id'] in by_id or frame.get('kind') not in {'user', 'world'}):
            raise ValueError('spatial reference frames need distinct IDs and user/world kind')
        keys = ('origin_object_id', 'observer_object_id', 'facing_target_object_id') if frame['kind'] == 'user' else ('origin_object_id',)
        if any(not isinstance(frame.get(k), str) or not frame[k].strip() for k in keys):
            raise ValueError('spatial reference needs explicit source objects')
        if object_ids is not None and any(frame[k] not in object_ids for k in keys):
            raise ValueError('spatial reference names an unavailable object')
        if frame['kind'] == 'user':
            if frame.get('front') not in {'toward_observer', 'observer_forward'}:
                raise ValueError('user frame front must distinguish work-surface front from observer forward')
        else:
            front = _review_reference_unit(_review_reference_vector(frame.get('front_world'), 'front_world'), 'front_world')
            right = _review_reference_unit(_review_reference_vector(frame.get('right_world'), 'right_world'), 'right_world')
            if any(abs(value) > 1e-4 for value in (_review_reference_dot(front, right), _review_reference_dot(front, up), _review_reference_dot(right, up))):
                raise ValueError('world reference axes must be orthogonal')
        by_id[frame['id']] = frame
    for relation in design.get('relations', []):
        name, directions = relation.get('reference_frame'), relation.get('expected_direction')
        if name is not None and name not in by_id:
            raise ValueError('spatial relation names an unknown reference frame')
        if directions is not None:
            if (name is None or not isinstance(directions, list) or not directions or
                    any(not isinstance(direction, str) or direction not in _REVIEW_DIRECTIONS for direction in directions) or len(set(directions)) != len(directions) or
                    any(pair <= set(directions) for pair in ({'left','right'}, {'front','back'}, {'above','below'}))):
                raise ValueError('directional relation needs a frame and nonconflicting directions')
            if relation.get('target') != by_id[name]['origin_object_id']:
                raise ValueError('directional relation target must be its reference origin')
    return reference


def validate_scene_brief(design, object_ids=None):
    if not isinstance(design.get('name'), str) or not design['name'].strip():
        raise ValueError('Scene brief needs a human-readable title')
    if not isinstance(design.get('summary'), str) or not design['summary'].strip():
        raise ValueError('Scene brief needs a non-empty description of its intended layout and use')
    for key in ('hard_requirements', 'physical_assumptions'):
        rows = design.get(key)
        if not isinstance(rows, list) or not rows or any(not isinstance(row, str) or not row.strip() for row in rows):
            raise ValueError('Scene brief needs concrete ' + key)
    roles = design.get('object_roles')
    if not isinstance(roles, list) or not roles:
        raise ValueError('Scene brief needs object roles')
    for row in roles:
        if not isinstance(row, dict) or not isinstance(row.get('object_id'), str) or not row['object_id'].strip() or not isinstance(row.get('role'), str) or not row['role'].strip():
            raise ValueError('Scene brief object role needs an exact object and useful explanation')
        if object_ids is not None and row['object_id'] not in object_ids:
            raise ValueError('Scene brief references a missing object: ' + row['object_id'])
    relations = design.get('relations')
    if not isinstance(relations, list) or not relations:
        raise ValueError('Scene brief needs explicit spatial relations')
    for row in relations:
        if (not isinstance(row, dict) or row.get('type') not in {'supported_by', 'mounted_to', 'clearance', 'near', 'facing', 'inside'} or
                not isinstance(row.get('description'), str) or not row['description'].strip() or
                any(not isinstance(row.get(key), str) or not row[key].strip() for key in ('source', 'target'))):
            raise ValueError('Scene brief needs concrete typed spatial relations')
        if object_ids is not None and (row.get('source') not in object_ids or row.get('target') not in object_ids | {'ground'}):
            raise ValueError('Scene brief relation references an unavailable object')
    validate_reference(design, object_ids)
    return design


def validate_brief_revision(design, path):
    """A declared revision inherits hard requirements from frozen production.

    Soft design can change in both directions; original production evidence is
    the authority for the inherited requirement list, not the author's new text.
    """
    history=design.get('revision_history', [])
    if not isinstance(history,list) or any(not isinstance(row,dict) for row in history):
        raise ValueError('Scene brief revision_history must be an array of revision records')
    previous=design.get('previous_capture_directory')
    if not previous and not history:
        return
    if not previous:
        if len(history)>1 or any(isinstance(row,dict) and (row.get('previous_attempt') or
                isinstance(row.get('revision'),int) and row['revision']>1) for row in history):
            raise ValueError('A revised scene brief must reference its previous captured evidence')
        directory=Path(history[-1].get('evidence_directory',''))
    else:
        directory=Path(previous)
    if not directory.is_absolute() or not directory.is_dir():raise ValueError('Brief revision needs its prior captured evidence directory')
    file=directory/'scene_brief.json'
    previous_history=[]
    if file.is_file():
        frozen=json.loads(file.read_text(encoding='utf-8'))
        if not set(frozen.get('hard_requirements',[])) <= set(design['hard_requirements']):
            raise ValueError('Scene brief revision must preserve every original hard requirement')
        previous_history=frozen.get('revision_history',[])
        if not isinstance(previous_history,list) or history[:-1]!=previous_history:
            raise ValueError('Scene brief revision must preserve earlier revision records')
    if not history or (previous and history[-1].get('evidence_directory')!=str(directory)):
        raise ValueError('Scene brief revision needs actual prior evidence and explicit changes')
    latest=history[-1]
    changes=latest.get('changes')
    if (type(latest.get('revision')) is not int or latest['revision'] < 1 or
            not isinstance(changes,list) or not changes or
            any(not isinstance(change,str) or not change.strip() for change in changes)):
        raise ValueError('Scene brief revision needs a numbered revision and concrete changes')
    if previous_history and (not isinstance(previous_history[-1],dict) or
            type(previous_history[-1].get('revision')) is not int or
            latest['revision'] <= previous_history[-1]['revision']):
        raise ValueError('Scene brief revision number must advance beyond its previous revision')
    unresolved=latest.get('unresolved')
    if (not isinstance(unresolved,list) or
            any(not isinstance(item,str) or not item.strip() for item in unresolved)):
        raise ValueError('Scene brief revision must record unresolved issues, or an empty array')
    refs=latest.get('evidence_refs')
    if not isinstance(refs,list) or not refs:
        raise ValueError('Scene brief revision needs image and physical evidence references')
    resolved=[]
    for ref in refs:
        if (not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or
                not isinstance(ref.get('observation'),str) or not ref['observation'].strip()):
            raise ValueError('Scene brief evidence references need a relative path and concrete observation')
        evidence_path=Path(ref['path'])
        if evidence_path.is_absolute() or '..' in evidence_path.parts:
            raise ValueError('Scene brief evidence references must stay inside the prior capture')
        source=directory/evidence_path
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Scene brief evidence reference does not point to a saved prior artifact')
        resolved.append(evidence_path.as_posix())
    if not any(re.fullmatch(r'capture/view_\d+\.png',name) for name in resolved):
        raise ValueError('Scene brief revision must cite an actual captured view')
    if not any(name in {'capture/evidence.json','scene_acceptance.json'} for name in resolved):
        raise ValueError('Scene brief revision must cite a native physical or acceptance receipt')
    if directory.resolve()==path.parent.resolve():raise ValueError('Preserve prior capture evidence in a separate revision')


def require_prior_brief(brief, directory):
    """A known captured parent cannot be detached by omitting revision metadata."""
    directory=Path(directory)
    if not (directory/'scene_brief.json').is_file():return
    previous=brief.get('previous_capture_directory')
    if not previous or Path(previous).resolve()!=directory.resolve():
        raise ValueError('Scene revision must reference the frozen brief of its captured parent')


def capture_retry_directory(root, task_id, revision=None):
    """Admitted frozen input can be recovered before any capture exists."""
    if not re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.scene\d+',str(task_id)):
        raise ValueError('Unreviewed scene retries require a valid scene task')
    folders=[p for p in (Path(root)/task_id).glob('revision_*') if p.is_dir() and p.name[9:].isdigit()]
    if revision is not None:
        folders=[p for p in folders if p.name=='revision_'+str(revision)]
    if not folders:raise ValueError('Unreviewed scene retries have no frozen admitted program')
    directory=max(folders,key=lambda p:int(p.name[9:]))
    admission=directory/'scene_admission.json'
    if (not (directory/'program.json').is_file() or not admission.is_file() or
            json.loads(admission.read_text()).get('passed') is not True):
        raise ValueError('Unreviewed scene retries require an admitted frozen program')
    return directory


def review_retry_directory(root, task_id):
    directory=capture_retry_directory(root,task_id)
    report=directory/'capture/report.json'
    if not report.is_file() or json.loads(report.read_text()).get('status')!='captured':
        raise ValueError('Unreviewed scene retries require an admitted native capture')
    return directory


def plan_declaration_current(declaration):
    """Reuse acceptance after edits that do not change this scene's design.

    File versions remain the cheap fast path. A changed plan is compared with
    the saved scene snapshot directly; formatting, scoring and other scenes
    must not invalidate unchanged native capture evidence.
    """
    try:
        path = Path(declaration['plan_path'])
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            return False
        if declaration.get('plan_version') == [path.stat().st_size, path.stat().st_mtime_ns]:
            return True
        plan = json.loads(path.read_text(encoding='utf-8-sig'))
        scenes = plan.get('assessment', plan).get('scenes', {})
        if 'scene_design_id' in declaration:
            values = scenes.get('geometry_exceptions', [])
            saved = next((row for row in values if row.get('scene_design_id') == declaration['scene_design_id']
                          and row.get('scene_id') == declaration.get('scene_id')), None)
        else:
            saved = next((row for row in scenes.get('designs', []) if row.get('id') == declaration.get('id')), None)
        metadata = {'plan_path', 'plan_version', 'authority', 'iteration_rule', 'scene_style'}
        expected = {key: value for key, value in declaration.items() if key not in metadata}
        return saved is not None and saved == expected
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def scene_brief(program, policy=None, root=None):
    saved = saved_design(program, policy)
    if not saved:
        if policy and (policy.get('require_scene_brief') or policy.get('enforce_realism')):
            raise ValueError('Save a titled, detailed scene brief in the production plan before scene submission')
        return None
    _, design, path = saved
    if not ((policy or {}).get('require_scene_brief') or (policy or {}).get('enforce_realism')) and 'summary' not in design:return None
    validate_scene_brief(design, {obj['id'] for obj in program['objects']})
    if root:
        for source in program.get('provenance',{}).get('sources',[]):
            if not isinstance(source,dict) or source.get('kind')!='original_scene':continue
            task=source.get('task_id','');revision=source.get('revision',0)
            if re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.scene\d+',str(task)) and type(revision) is int and revision>=0:
                require_prior_brief(design,Path(root)/task/('revision_'+str(revision)))
    validate_brief_revision(design,path)
    return {**design, 'plan_path': str(path.resolve()), 'plan_version': [path.stat().st_size, path.stat().st_mtime_ns],
            'authority': 'versioned scene design, not captured physical truth',
            'iteration_rule': 'repair scene to brief; revise omissions from actual evidence; preserve user hard requirements and failed evidence'}
