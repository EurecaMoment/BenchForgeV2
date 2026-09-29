"""Freeze validated task-authored scene data before queueing; never import code or GT."""
import json
import os
from pathlib import Path
from .contracts import validate_program,ASSETS

MAX_PROGRAM_BYTES=1024*1024


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate SceneProgram JSON key: '+key)
        result[key]=value
    return result


def read_program_submission(artifact_root,source_path):
    roots=[(Path(artifact_root)/'operator_workspaces').resolve(),
           Path(os.environ.get('SPATIALFORGE_TASK_ROOT','/home/maqiang/SpatialForge-tasks')).resolve()]
    if not isinstance(source_path,str) or not source_path:raise ValueError('scene_program_path must be a task workspace JSON source_path')
    path=Path(source_path).resolve()
    if not any(path.is_relative_to(root) for root in roots) or path.suffix.lower()!='.json':
        raise ValueError('scene_program_path must be a .json file inside an operator task workspace. '
                         f'Accepted roots: {", ".join(str(root) for root in roots)}. '
                         f'Use standard file tools to write or copy the task JSON under {roots[1]}, '
                         'or use spatialforge_task_code and its returned source_path.')
    try:
        with path.open('rb') as stream:raw=stream.read(MAX_PROGRAM_BYTES+1)
    except OSError as exc:raise ValueError('SceneProgram task file unavailable') from exc
    if len(raw)>MAX_PROGRAM_BYTES:raise ValueError('SceneProgram exceeds 1 MiB input limit')
    def invalid_constant(value):raise ValueError('non-finite JSON constant: '+value)
    try:
        program=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_pairs,parse_constant=invalid_constant)
        json.dumps(program,allow_nan=False)  # Also rejects exponent overflow such as 1e999.
    except (UnicodeError,ValueError,RecursionError) as exc:raise ValueError('invalid SceneProgram JSON: '+str(exc)[:300]) from exc
    validate_program(program)
    from .contracts import normalize_native_asset_references
    validate_program(normalize_native_asset_references(program))
    # Validate mesh references without reading large meshes. Native aliases are
    # normalized by the same established executor path after acceptance.
    from .contracts import ident
    for obj in program['objects']:
        if obj['kind']!='mesh' or obj.get('asset_id') in ASSETS:continue
        asset_id=ident(obj.get('asset_id'))
        assets=(Path(artifact_root)/'generated_assets').resolve()
        mesh=(assets/asset_id/'mesh.json').resolve()
        if not mesh.is_relative_to(assets) or not mesh.is_file():raise ValueError(f'object {obj["id"]}: registered mesh unavailable: {asset_id}')
    return {'schema':'spatialforge.program-submission/v1','source_path':str(path),
        'source_bytes':len(raw),'authority':'task-authored scene data; not GT',
        'program':program}


def handoff_receipt(submission,program,revision):
    original=submission['program']
    old={o['id']:o for o in original['objects']};new={o['id']:o for o in program['objects']}
    changed=[{'id':key,'fields':sorted(k for k in set(old[key])|set(new[key]) if old[key].get(k)!=new[key].get(k))}
        for key in old.keys()&new.keys() if old[key]!=new[key]]
    return {'schema':'spatialforge.program-handoff/v1','source_path':submission['source_path'],
        'authority':submission['authority'],'revision':revision,
        'program_stage':'prepared_for_capture; execution requires capture evidence',
        'first_pass_mode':'validated file snapshot without planner rewrite',
        'submitted_object_count':len(old),'prepared_object_count':len(new),
        'submitted_camera_count':len(original['cameras']),'prepared_camera_count':len(program['cameras']),
        'exact_program_match':original==program,'added_objects':sorted(new.keys()-old.keys()),
        'removed_objects':sorted(old.keys()-new.keys()),'changed_objects':sorted(changed,key=lambda row:row['id']),
        'changed_sections':sorted(k for k in set(original)|set(program) if k!='objects' and original.get(k)!=program.get(k)),
        'notes':['generated assets and native aliases retain existing realization/normalization rules',
                 'submitted scene data stays operator-controlled; inspect captures and submit your own revision',
                 'handoff equality is not simulation, contact, photorealism or benchmark acceptance']}
