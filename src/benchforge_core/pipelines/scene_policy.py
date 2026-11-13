"""Operator scene exclusions and a lightweight box-proxy admission rule."""
from functools import cache
import importlib.util
import json
from pathlib import Path
import re
from ..service_config import environment_value

STRUCTURE = re.compile(r'^(?:floor|ceiling|wall(?:_|$)|ground|terrain|pavement|asphalt|roof|road(?:_|$)|bay_line|rug|carpet|window|door(?:_|$))', re.I)
CLASSIFIER_VERSION = 4
EXCLUDED_SCENE = 'This cube/proxy scene was removed by the user and cannot be reused'


@cache
def scene_design_parser():
    # A core wheel ships the contract from its own revision.
    try:
        from . import _scene_design as module
    except ImportError:
        # Editable installs use the same source directly from the checkout.
        file = Path(__file__).resolve().parents[2] / 'backend/benchforge_backend/scene_design.py'
        spec = importlib.util.spec_from_file_location('scene_design_policy', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def planned_geometry(program, policy=None):
    return scene_design_parser().geometry_exception(program, policy)


def classify(program):
    props = [obj for obj in program.get('objects', []) if isinstance(obj, dict) and not STRUCTURE.search(str(obj.get('id', '')))]
    detailed = [obj for obj in props if obj.get('kind') == 'mesh' or str(obj.get('kind', '')).startswith('office_') or obj.get('kind') == 'mug']
    boxes = [obj for obj in props if obj.get('kind', 'box') in ('box', 'composite', 'bin', 'container')]
    simple = [obj for obj in props if obj.get('kind', 'box') == 'box']
    explicit = [obj for obj in props if re.search(r'cube|立方体', str(obj.get('id', '')) + ' ' + str(obj.get('label', '')), re.I)]
    reason = ('explicit_cube_objects' if explicit else 'foreground_box_proxy' if simple else
              'primitive_box_proxy_scene' if boxes and not detailed else None)
    return {'allowed': reason is None, 'reason': reason, 'classifier_version': CLASSIFIER_VERSION, 'foreground_objects': len(props),
            'simple_boxes': len(simple), 'detailed_objects': len(detailed),
            'cube_objects': [obj.get('id') for obj in explicit],
            'scope': 'program representation check; captured appearance still requires visual acceptance'}


def classify_planned(program, policy=None):
    # Detailed multi-part furniture and real open containers remain subject to
    # captured identity/support checks; the old removal classifier is stricter.
    candidate = {**program, 'objects': [obj for obj in program.get('objects', []) if not (
        obj.get('kind') in {'bin', 'container'} or obj.get('kind') == 'composite' and len(obj.get('parts', [])) >= 3 and
        len({tuple(part.get('offset', [0,0,0])) for part in obj.get('parts', [])}) >= 3)]}
    verdict = classify(candidate)
    declaration = planned_geometry(program, policy)
    if declaration:
        remaining = {**candidate, 'objects': [obj for obj in candidate.get('objects', [])
                                            if obj['id'] not in declaration['object_ids']]}
        allowed = classify(remaining)['allowed']
        verdict = {**verdict, 'allowed': allowed, 'geometry_exception': declaration,
                   'scene_style': 'simplified_geometry'}
    else:
        verdict['scene_style'] = 'realistic_assets'
    return verdict


def _read_policy(file):
    path = Path(file) if file else None
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def load_policy(workspace, service_config=None):
    """Load the same policy selected by the BenchForge service config."""
    if service_config:
        from ..service_config import load_service_client_config

        config = load_service_client_config(service_config)
        mode = config['execution_mode']
        file = config.get('scene_policy_path')
    else:
        mode = environment_value('BENCHFORGE_EXECUTION_MODE')
        file = environment_value('BENCHFORGE_SCENE_POLICY')
        if not file:
            legacy = Path(workspace) / 'scene-library' / 'policy.json'
            file = legacy if legacy.is_file() else None
        if not mode:
            mode = 'production' if file else 'exploration'

    if mode not in {'production', 'exploration'}:
        raise ValueError('execution_mode must be production or exploration')
    policy = _read_policy(file)
    if mode == 'production' and (not file or not policy.get('enabled') or not policy.get('enforce_realism')):
        raise ValueError('Production execution requires an enabled, realism-enforcing scene policy')
    if mode == 'exploration':
        return {'execution_mode': mode}
    policy['execution_mode'] = mode
    if policy.get('enabled') and policy.get('enforce_realism'):
        policy['require_scene_brief']=True
    return policy


def excluded_path(policy, value):
    return scene_design_parser().path_is_excluded(value, policy)


def check_source(policy, *, task_id=None, run_id=None, scene_group=None, source_path=None):
    if not policy.get('enabled'):
        return
    if (task_id in policy.get('excluded_tasks', []) or run_id in policy.get('excluded_runs', []) or
            scene_group in policy.get('excluded_scene_groups', []) or source_path and excluded_path(policy, source_path)):
        raise ValueError(EXCLUDED_SCENE)


def check_program(policy, program):
    if policy.get('enabled'):
        scene_design = scene_design_parser()
        if scene_design.references_excluded_source(program, policy):
            raise ValueError(EXCLUDED_SCENE)
        scene_design.scene_brief(program, policy)
        verdict = classify_planned(program, policy)
        if not verdict['allowed']:
            raise ValueError('Scene rejected: ' + verdict['reason'] + '. Default to recognizable assets; declare any intentional simplified geometry and its exact scope in the saved scene production plan.')


def check_submission(workspace, route, arguments, service_config=None):
    policy = load_policy(workspace, service_config)
    if not policy.get('enabled'):
        return
    if route not in ('/start', '/capture', '/refine', '/extend', '/retry', '/dataset'):
        return
    check_source(policy, task_id=arguments.get('parent_task_id') or arguments.get('task_id'), run_id=arguments.get('run_id'))
    if scene_design_parser().references_excluded_source(arguments, policy):
        raise ValueError(EXCLUDED_SCENE)
    if route == '/retry' and re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.scene\d+',str(arguments.get('task_id',''))):
        catalog=Path(workspace)/'scene-library/catalog.json'
        accepted=json.loads(catalog.read_text(encoding='utf-8')) if catalog.is_file() else {'items':[]}
        if arguments['task_id'] not in {row['id'] for row in accepted['items']}:
            config=Path(workspace)/'service.local.json'
            if not config.is_file():raise ValueError('Unreviewed scene retries are disabled; provide a compliant SceneProgram through capture/refine')
            root=json.loads(config.read_text())['artifacts']
            directory=scene_design_parser().capture_retry_directory(root,arguments['task_id'])
            if arguments.get('feedback') is not None:raise ValueError('Scene changes require capture/refine')
            check_program(policy,json.loads((directory/'program.json').read_text()))
    intents = arguments.get('intents', []) if route == '/start' else [arguments]
    if route in ('/start', '/capture', '/refine', '/extend'):
        if not intents:
            raise ValueError('Provide a complete SceneProgram for scene admission')
        for intent in intents:
            source = intent.get('scene_program_path')
            if not source:
                raise ValueError('Scene policy requires scene_program_path before queue submission; the unchecked default planner is disabled')
            check_source(policy, source_path=source)
            check_program(policy, json.loads(Path(source).read_text(encoding='utf-8-sig')))


def check_evidence(workspace, record, evidence_path, service_config=None):
    policy=load_policy(workspace, service_config)
    if not policy.get('enabled') or not policy.get('enforce_realism'):return
    references=[str(record.get('scene_group_id','')),*[str(v) for v in record.get('media',[])],
                str(record.get('provenance',{}).get('path',''))]
    catalog=Path(workspace)/'scene-library/catalog.json'
    items=json.loads(catalog.read_text(encoding='utf-8'))['items'] if catalog.is_file() else []
    task_id=record.get('provenance',{}).get('task_id')
    matches=[row for row in items if row['task_id']==task_id or any(row['task_id'] in value for value in references)
             or record.get('scene_group_id') in {'scene-v1:'+row.get('name',''),'scene-v1:'+row['task_id']}]
    if not matches:raise ValueError('Scene evidence must bind an accepted source scene; copied media and scene labels alone are insufficient')
    for row in matches:
        directory=Path(row['source_directory'])
        file=directory/'scene_acceptance.json'
        receipt=json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}
        if receipt.get('passed') is not True:raise ValueError('Scene lacks physical and life acceptance; recapture and review before question production')
        if policy.get('require_scene_brief') and not receipt.get('scene_brief'):
            raise ValueError('Scene needs a saved brief and capture alignment before question production')
        for declaration in (receipt.get('geometry_exception'), receipt.get('scene_brief')):
            if not declaration:continue
            if not scene_design_parser().plan_declaration_current(declaration):
                raise ValueError('Scene design changed since acceptance; recapture and review the changed scene')
        for relative in ('program.json','capture/report.json','capture/evidence.json'):
            path=directory/relative
            if not path.is_file() or receipt.get('evidence_versions',{}).get(relative) != [path.stat().st_size,path.stat().st_mtime_ns]:
                raise ValueError('Scene evidence changed after acceptance')
        for name,version in receipt.get('mesh_versions',{}).items():
            path=Path(name)
            if not path.is_file() or [path.stat().st_size,path.stat().st_mtime_ns]!=version:
                raise ValueError('Transported scene mesh changed after acceptance')

