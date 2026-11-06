"""Operator scene exclusions and a lightweight box-proxy admission rule."""
import json
from pathlib import Path
import re

STRUCTURE = re.compile(r'^(?:floor|ceiling|wall(?:_|$)|ground|terrain|pavement|asphalt|roof|road(?:_|$)|bay_line|rug|carpet|window|door(?:_|$))', re.I)
CLASSIFIER_VERSION = 4


def scene_design_parser():
    # The monorepo tool runner and separately deployed service share this parser.
    try:
        from spatialforge import scene_design as module
    except ImportError:
        # Normal installs use the validator bundled from the same source at
        # wheel build time. SpatialForge itself requires Python >=3.11 and is
        # intentionally optional for the core's Python 3.10 support.
        try:
            from . import _scene_design as module
            return module
        except ImportError:
            pass
        import importlib.util
        file=Path(__file__).resolve().parents[3]/'components/spatialforge/src/spatialforge/scene_design.py'
        spec=importlib.util.spec_from_file_location('scene_design_policy',file)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
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


def load_policy(workspace):
    file = Path(workspace) / 'scene-library' / 'policy.json'
    policy=json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}
    if policy.get('enabled') and policy.get('enforce_realism'):
        policy['require_scene_brief']=True
    return policy


def excluded_path(policy, value):
    path = Path(value).resolve()
    return any(path == Path(root).resolve() or path.is_relative_to(Path(root).resolve()) for root in policy.get('excluded_paths', []))


def check_source(policy, *, task_id=None, run_id=None, scene_group=None, source_path=None):
    if not policy.get('enabled'):
        return
    if (task_id in policy.get('excluded_tasks', []) or run_id in policy.get('excluded_runs', []) or
            scene_group in policy.get('excluded_scene_groups', []) or source_path and excluded_path(policy, source_path)):
        raise ValueError('This cube/proxy scene was removed by the user and cannot be reused')


def check_program(policy, program):
    if policy.get('enabled'):
        def inspect(value):
            if isinstance(value, dict):
                for child in value.values():inspect(child)
            elif isinstance(value, list):
                for child in value:inspect(child)
            elif isinstance(value, str):
                check_source(policy, task_id=value, run_id=value, scene_group=value,
                             source_path=value if Path(value).is_absolute() else None)
        inspect(program)
        scene_design_parser().scene_brief(program, policy)
        verdict = classify_planned(program, policy)
        if not verdict['allowed']:
            raise ValueError('Scene rejected: ' + verdict['reason'] + '. Default to recognizable assets; declare any intentional simplified geometry and its exact scope in the saved scene production plan.')


def check_submission(workspace, route, arguments):
    policy = load_policy(workspace)
    if not policy.get('enabled'):
        return
    if route not in ('/start', '/capture', '/refine', '/extend', '/retry', '/dataset'):
        return
    check_source(policy, task_id=arguments.get('parent_task_id') or arguments.get('task_id'), run_id=arguments.get('run_id'))
    def inspect(value):
        if isinstance(value, dict):
            for child in value.values():inspect(child)
        elif isinstance(value, list):
            for child in value:inspect(child)
        elif isinstance(value, str):
            check_source(policy, task_id=value, run_id=value, scene_group=value,
                         source_path=value if Path(value).is_absolute() else None)
    inspect(arguments)
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


def check_evidence(workspace, record, evidence_path):
    policy=load_policy(workspace)
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

