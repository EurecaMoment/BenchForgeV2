"""Fail-closed operator admission for realistic, physically plausible scene production.

Native measurements and visual opinions remain separate. Conservative bound
overlaps are unresolved, not proof of penetration; unresolved scenes cannot ship.
"""
import json
import math
from pathlib import Path
import re

from capabilities.scene_authoring.catalog.native import ASSETS
from capabilities.scene_authoring.validation.program import validate_program
from capabilities.scene_authoring.catalog.native import normalize_native_asset_references
from capabilities.scene_authoring.geometry.preview import preview_scene_geometry
from capabilities.scene_authoring.validation.preflight import preflight_scene
from capabilities.scene_authoring.contracts.scene_design import geometry_exception
from capabilities.scene_authoring.contracts.scene_design import scene_brief
from capabilities.scene_authoring.geometry.relations import native_part_bounds
from capabilities.scene_authoring.geometry.relations import supported_by_parts
from capabilities.scene_authoring.geometry.relations import supported_by_native_parts
from capabilities.scene_authoring.geometry.relations import overlap_unresolved
from capabilities.scene_authoring.geometry.relations import transported_mesh_bounds
from capabilities.scene_authoring.validation.policy import check_references
from capabilities.scene_authoring.validation.policy import check_request
from capabilities.scene_authoring.validation.policy import policy_for

STRUCTURE = re.compile(r'^(?:floor|ceiling|wall(?:_|$)|ground|terrain|pavement|asphalt|roof|road(?:_|$)|bay_line|rug|carpet|window|door(?:_|$))', re.I)
VISUAL_CHECKS = {'object_identity', 'realistic_scale', 'support_and_attachment',
                 'functional_layout', 'access_and_clearance', 'materials_and_lighting'}


def _policy_for_mode(root, execution_mode):
    return policy_for(root) if execution_mode is None else policy_for(root, execution_mode)


def captured_observation(row, frames):
    """A real view and useful text are required; verbosity is not evidence."""
    return (isinstance(row,dict) and isinstance(row.get('view'),str) and row['view'] in frames and
            isinstance(row.get('observation'),str) and bool(row['observation'].strip()))


def detailed_construction(obj):
    """A modeled table/fixture is distinct from a single envelope placeholder.

    This admits geometry for capture, never certifies its visual identity.
    """
    parts = obj.get('parts', [])
    return (obj.get('kind') == 'composite' and len(parts) >= 3 and
            len({tuple(part.get('offset', [0, 0, 0])) for part in parts}) >= 3)


def attachment(obj, by_id):
    value = obj.get('metadata', {}).get('spatial_attachment')
    if value is None:return None
    if (not isinstance(value, dict) or obj.get('dynamic') is not False or
            value.get('target') not in by_id or value['target'] == obj['id'] or
            by_id[value['target']].get('dynamic') is not False or value.get('method') != 'static_mount' or
            type(value.get('axis')) is not int or value['axis'] not in (0, 1, 2) or
            value.get('object_face') not in ('min', 'max') or value.get('target_face') not in ('min', 'max') or
            value['object_face'] == value['target_face']):
        raise ValueError(obj['id'] + ': invalid explicit static mounting relation')
    return value


def structure(obj):
    # A name cannot turn a chair-sized cube into a floor or wall.
    size = obj.get('size', [])
    return (bool(STRUCTURE.search(str(obj.get('id', '')))) and len(size) == 3
            and obj.get('dynamic') is False and min(size) <= .4
            and max(size) >= 1)


def admit_program(root, program, *, allow_generated=False, execution_mode=None):
    policy = _policy_for_mode(root, execution_mode)
    if not policy:return {'enforced': False, 'passed': None, 'evaluation_status': 'not_evaluated'}
    check_references(program, policy)
    validate_program(program)
    program = normalize_native_asset_references(program)
    props = [obj for obj in program['objects'] if not structure(obj)]
    if not props:raise ValueError('Realistic scenes need recognizable foreground assets')
    declaration = geometry_exception(program, policy)
    brief = scene_brief(program, policy, root)
    simplified=set(declaration['object_ids']) if declaration else set()
    by_id = {obj['id']: obj for obj in program['objects']}
    problems = []
    if brief:
        for relation in brief['relations']:
            obj = by_id[relation['source']]
            if relation['type'] == 'supported_by' and obj['support'] != relation['target']:
                problems.append(obj['id'] + ': support contradicts saved scene brief')
            if relation['type'] == 'mounted_to' and (attachment(obj, by_id) or {}).get('target') != relation['target']:
                problems.append(obj['id'] + ': mounting contradicts saved scene brief')
    for obj in props:
        kind = obj['kind']
        mount = attachment(obj, by_id)
        if obj['id'] not in simplified and kind not in ASSETS and kind not in {'mesh', 'bin', 'container'} and not detailed_construction(obj) and not (kind == 'generated' and allow_generated):
            problems.append(obj['id'] + ': default scene design uses recognizable assets; simplified geometry needs an explicit scoped declaration in the saved scene plan')
        if obj['id'] not in simplified and re.search(r'cube|立方体', obj['id'] + ' ' + obj['label'], re.I):
            problems.append(obj['id'] + ': default scene design needs an explicit planned geometry exception for cube objects')
        if kind in ASSETS:
            ratios = [obj['size'][i] / ASSETS[kind]['size'][i] for i in range(3)]
            if min(ratios) < .5 or max(ratios) > 2 or max(ratios)/min(ratios) > 1.5:
                problems.append(obj['id'] + ': scale or proportions depart from the registered real asset')
        if not mount and obj['support'] == 'ground' and abs(obj['base_z']) > .03:
            problems.append(obj['id'] + ': ground object floats or penetrates ground; model actual support/attachment')
        if obj['dynamic'] and not obj.get('physics'):
            problems.append(obj['id'] + ': dynamic object needs explicit friction, restitution and mass provenance')
        if obj['dynamic'] and not {'static_friction','dynamic_friction','restitution','mass_source'} <= set(obj.get('physics', {})):
            problems.append(obj['id'] + ': incomplete physical material/inertia declaration')
    if any(obj['kind']=='generated' for obj in props):
        if not allow_generated:problems.append('Generated assets must be realized before capture admission')
    camera = preflight_scene(program)
    problems += [row['code'] for row in camera['errors']]
    def mesh(asset_id):
        path = Path(root)/'generated_assets'/asset_id/'mesh.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        declared_assets = {obj.get('asset_id') for obj in props if obj['id'] in simplified}
        if len(value.get('vertices', [])) <= 8 and asset_id not in declared_assets:
            raise ValueError('Mesh is a primitive proxy, not a recognizable scene asset: ' + asset_id)
        return value
    if not allow_generated or not any(obj['kind'] == 'generated' for obj in props):
        geometry = preview_scene_geometry(program, mesh_loader=mesh)
        for row in geometry['objects']:
            if row.get('unavailable'):problems.append(row['object_id'] + ': source geometry is unavailable')
            obj=by_id[row['object_id']]
            if not structure(obj) and not attachment(obj, by_id) and row.get('support_face_options') and not any(face['footprint_within_face'] and abs(face['geometry_bottom_gap_m']) <= .03 for face in row['support_face_options']):
                problems.append(row['object_id'] + ': unsupported initial placement')
    if problems:raise ValueError('Realistic scene admission failed: ' + '; '.join(problems)[:1800])
    return {'enforced': True, 'passed': True, 'stage': 'before_capture',
            'scene_style':'simplified_geometry' if declaration else 'realistic_assets','geometry_exception':declaration,'scene_brief':brief,
            'scope': 'assets or declared simplification, scale, support and camera sanity; capture validation still required'}


def capture_acceptance(root, program, report, evidence, review, capture, execution_mode=None):
    """Require actual native capture, physics, geometry and per-view life review."""
    policy = _policy_for_mode(root, execution_mode)
    if execution_mode == 'exploration' or not policy:
        return {
            'enforced': False,
            'passed': None,
            'evaluation_status': 'not_evaluated',
            'execution_mode': execution_mode or 'exploration',
        }
    issues = []
    admission={}
    try:admission=admit_program(root, program, execution_mode=execution_mode)
    except (ValueError, OSError, KeyError, TypeError) as error:issues.append(str(error))
    physics = evidence.get('physics', {})
    if report.get('status') != 'captured' or report.get('renderable') is not True or evidence.get('origin') != 'isaac_native':
        issues.append('Actual native rendered capture is required')
    if not report.get('token') or evidence.get('token') != report.get('token'):
        issues.append('Native capture evidence must bind this exact capture token')
    if (physics.get('stable') is not True or not isinstance(physics.get('steps'), int) or physics['steps'] < 60
            or not isinstance(physics.get('dt'), (int,float)) or not math.isfinite(physics['dt']) or physics['dt'] <= 0):
        issues.append('A stable native physics rollout of at least 60 steps is required')
    actions=[row for row in program.get('interactions',program.get('affordances',[])) if row.get('action')=='apply_force']
    if actions:
        interaction=evidence.get('interaction',{})
        results={row.get('id'):row for row in interaction.get('action_results',[]) if isinstance(row,dict)}
        for action in actions:
            result=results.get(action['id'],{})
            if (interaction.get('validated') is not True or result.get('success') is not True or
                    result.get('action')!='apply_force' or result.get('object_id')!=action['object_id'] or
                    any(not isinstance(result.get(key),str) or not (Path(capture)/result[key]).is_file()
                        for key in ('trajectory_file','before_image','after_image'))):
                issues.append(action['id']+': native interaction needs a passing trajectory and before/after evidence')
    entities = evidence.get('entities', {})
    boxes = {}
    executed_parts = {}
    mesh_bound_checks=[];mesh_versions={}
    dependencies={row.get('entity_id'):row for row in evidence.get('asset_dependencies',[]) if isinstance(row,dict)}
    for obj in program['objects']:
        row = entities.get(obj['id'], {})
        box = row.get('world_aabb', {})
        lo, hi = box.get('min', []), box.get('max', [])
        if (len(lo) != 3 or len(hi) != 3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in [*lo,*hi])
                or any(hi[i] <= lo[i] for i in range(3)) or not isinstance(row.get('collision'),dict) or not row['collision'].get('paths')):
            issues.append(obj['id'] + ': native bounds/collider receipt missing');continue
        boxes[obj['id']] = (lo,hi)
        executed_parts[obj['id']] = native_part_bounds(row)
        if obj.get('kind')=='mesh' and obj.get('asset_id'):
            file=Path(root)/'generated_assets'/obj['asset_id']/'mesh.json'
            try:
                tight=transported_mesh_bounds(row,dependencies.get(obj['id'],{}),json.loads(file.read_text()))
                if tight and all(tight[0][i]>=lo[i]-.002 and tight[1][i]<=hi[i]+.002 for i in range(3)):
                    boxes[obj['id']]=tight
                    mesh_versions[str(file)]=[file.stat().st_size,file.stat().st_mtime_ns]
                    mesh_bound_checks.append({'object_id':obj['id'],'min':tight[0],'max':tight[1],
                        'basis':'all transported source vertices under final native world transform; overlap exclusion only'})
            except (OSError,ValueError,TypeError,KeyError):pass
    props = [obj for obj in program['objects'] if not structure(obj)]
    by_id = {obj['id']: obj for obj in program['objects']}
    verified_mounts = set()
    for obj in props:
        if obj['id'] not in boxes:continue
        lo,hi = boxes[obj['id']]
        try:mount = attachment(obj, by_id)
        except ValueError as error:issues.append(str(error));mount = None
        if mount:
            target = boxes.get(mount['target'])
            axis = mount['axis']
            if target:
                face = lo if mount['object_face'] == 'min' else hi
                target_face = target[0] if mount['target_face'] == 'min' else target[1]
                touching = abs(face[axis] - target_face[axis]) <= .04
                inside = all(min(hi[i], target[1][i]) - max(lo[i], target[0][i]) > .005 for i in range(3) if i != axis)
                if touching and inside:
                    verified_mounts.add(frozenset((obj['id'], mount['target'])));continue
            issues.append(obj['id'] + ': static mount has no native connection to its declared target');continue
        support = obj['support']
        if support == 'ground':
            if abs(lo[2]) > .04:issues.append(obj['id'] + ': native geometry floats above or penetrates ground')
        elif support in boxes:
            a,b = boxes[support]
            supported = supported_by_native_parts((lo,hi),entities[support]) if executed_parts.get(support) else supported_by_parts((lo,hi),[(a,b)])
            if not supported:
                issues.append(obj['id'] + ': native support gap or overhang is unresolved')
        else:issues.append(obj['id'] + ': native support evidence missing')
    for i, left in enumerate(program['objects']):
        for right in program['objects'][i+1:]:
            if left['id'] not in boxes or right['id'] not in boxes:continue
            if structure(left) and structure(right):continue
            if frozenset((left['id'], right['id'])) in verified_mounts:continue
            left_parts = executed_parts.get(left['id']) or [boxes[left['id']]]
            right_parts = executed_parts.get(right['id']) or [boxes[right['id']]]
            if overlap_unresolved(left_parts, right_parts):
                issues.append(left['id'] + '/' + right['id'] + ': overlapping native bounds require layout repair; mesh intersection is unresolved')
    physical_issues=list(issues)
    frames = {row.get('frame_id') + '.png' for row in evidence.get('frames', []) if isinstance(row.get('frame_id'), str)}
    frames = {name for name in frames if (Path(capture)/name).is_file()}
    for result in evidence.get('interaction',{}).get('action_results',[]):
        if not isinstance(result,dict):continue
        for key in ('before_image','after_image'):
            name=result.get(key)
            if isinstance(name,str) and Path(name).name==name and (Path(capture)/name).is_file():frames.add(name)
    expected = {'view_' + str(i) + '.png' for i in range(len(program.get('cameras', [])))}
    if not expected or not expected <= frames:
        issues.append('Every planned camera must have an actual captured view for production acceptance')
    checks = review.get('life_review', {}).get('checks', [])
    for name in sorted(VISUAL_CHECKS):
        rows = [row for row in checks if isinstance(row,dict) and row.get('check') == name]
        if len(rows) != 1 or rows[0].get('passed') is not True:
            issues.append('Visual/life check failed or missing: ' + name);continue
        observations = rows[0].get('evidence', [])
        if not observations or any(not captured_observation(item,frames) for item in observations):
            issues.append('Life check lacks a concrete captured-view observation: ' + name)
    style=admission.get('scene_style','realistic_assets')
    brief = admission.get('scene_brief')
    native_relation_checks=[]
    if brief:
        def relation_passed(relation):
            """Evaluate only the native evidence for this relation.

            A separate physical defect must not make unrelated relations look
            failed in the report. The overall receipt still fails when any
            physical issue remains; this only keeps the per-relation evidence
            honest and actionable.
            """
            source, target = relation['source'], relation['target']
            if source not in boxes:
                return False
            obj = by_id.get(source)
            if not obj:
                return False
            if relation['type'] == 'mounted_to':
                mount = obj.get('metadata', {}).get('spatial_attachment')
                return (isinstance(mount, dict) and mount.get('target') == target and
                        frozenset((source, target)) in verified_mounts)
            if relation['type'] != 'supported_by' or obj.get('support') != target:
                return False
            lo, hi = boxes[source]
            if target == 'ground':
                return abs(lo[2]) <= .04
            if target not in boxes:
                return False
            support_entity = entities.get(target, {})
            if executed_parts.get(target):
                return supported_by_native_parts((lo, hi), support_entity)
            return supported_by_parts((lo, hi), [(boxes[target][0], boxes[target][1])])

        for index,relation in enumerate(brief['relations']):
            if relation['type'] not in {'supported_by','mounted_to'}:continue
            source,target=relation['source'],relation['target']
            passed=relation_passed(relation)
            native_relation_checks.append({'index':index,'type':relation['type'],'source':source,'target':target,
                'passed':passed,'evidence':'capture/evidence.json',
                'basis':'native world bounds, executed support parts or verified static mount; not visual opinion'})
    frozen_file = Path(capture).parent / 'scene_admission.json'
    if brief and frozen_file.is_file():
        frozen = json.loads(frozen_file.read_text(encoding='utf-8')).get('scene_brief')
        if not frozen or frozen.get('plan_version') != brief.get('plan_version'):
            issues.append('Scene brief changed during production; start a new capture for the revised brief')
    if brief:
        alignment = review.get('brief_alignment', {})
        if alignment.get('passed') is not True or alignment.get('hard_requirements_preserved') is not True:
            issues.append('Captured scene does not satisfy the saved scene brief and protected requirements')
        observed = alignment.get('observations', [])
        if not observed or any(not captured_observation(row,frames) for row in observed):
            issues.append('Scene brief alignment needs actual per-view observations')
        if not expected <= {row['view'] for row in observed if captured_observation(row,frames)}:
            issues.append('Scene brief alignment must account for every captured camera view')
        if alignment.get('unresolved') != []:
            issues.append('Scene brief has unresolved spatial or functional contradictions')
        for key, expected_indices in (('requirement_checks', set(range(len(brief['hard_requirements'])))),
                                     ('relation_checks', {i for i,r in enumerate(brief['relations']) if r['type'] not in {'supported_by','mounted_to'}})):
            checks = alignment.get(key, [])
            # Physical relations are already measured above. Visual opinions
            # about hidden shelf bottoms must not replace those native checks.
            relevant=[row for row in checks if isinstance(row,dict) and type(row.get('index')) is int and
                      row['index'] in expected_indices] if isinstance(checks,list) else []
            if (not isinstance(checks, list) or len(relevant) != len(expected_indices) or
                    {row.get('index') for row in relevant} != expected_indices or
                    any(row.get('passed') is not True or not captured_observation(row,frames) for row in relevant)):
                issues.append('Scene brief needs complete captured evidence for ' + key)
    expected_status='matches_declared_geometry' if style=='simplified_geometry' else 'visually_plausible'
    if review.get('acceptable') is not True or review.get('visual_realism', {}).get('status') != expected_status:
        issues.append('Captured views failed appearance/semantic acceptance')
    files = [Path(capture).parent/'program.json',Path(capture)/'report.json',Path(capture)/'evidence.json']
    versions = {file.relative_to(Path(capture).parent).as_posix():[file.stat().st_size,file.stat().st_mtime_ns] for file in files if file.is_file()}
    return {'schema':'benchforge.scene-acceptance/v1','enforced':True,'passed':not issues,'issues':issues,
            'physical_issues':physical_issues,
            'native_relation_checks':native_relation_checks,
            'mesh_bound_checks':mesh_bound_checks,'mesh_versions':mesh_versions,
            'scene_id':program.get('scene_id'),'capture_token':report.get('token'),'evidence_versions':versions,
            'scene_style':style,'geometry_exception':admission.get('geometry_exception'),'scene_brief':brief,
            'physical_scope':'native settling, conservative world bounds, support gap and collider receipts; uncalibrated material parameters',
            'life_scope':'per-view model visual judgment, not measured truth or human certification',
            'on_failure':'retain failed evidence; repair within budget; never export or mark complete'}


def require_accepted(root, directory, execution_mode=None):
    policy = _policy_for_mode(root, execution_mode)
    if not policy:return
    directory=Path(directory)
    file=directory/'scene_acceptance.json'
    receipt=json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}
    if receipt.get('passed') is not True or receipt.get('enforced') is not True:
        raise ValueError('Scene has no passing physical and life acceptance; do not export, select or mark complete')
    if policy.get('require_scene_brief') and not receipt.get('scene_brief'):
        raise ValueError('Scene has no saved brief and capture alignment acceptance')
    for relative in ('program.json','capture/report.json','capture/evidence.json'):
        path=directory/relative
        if not path.is_file() or receipt.get('evidence_versions',{}).get(relative) != [path.stat().st_size,path.stat().st_mtime_ns]:
            raise ValueError('Scene changed since acceptance; recapture and review before production')
    for declaration in (receipt.get('geometry_exception'), receipt.get('scene_brief')):
        if not declaration:continue
        plan=Path(declaration['plan_path'])
        if not plan.is_file() or declaration.get('plan_version')!=[plan.stat().st_size,plan.stat().st_mtime_ns]:
            raise ValueError('Declared scene simplification changed; review the new plan and capture again')
    for name,version in receipt.get('mesh_versions',{}).items():
        path=Path(name)
        if not path.is_file() or [path.stat().st_size,path.stat().st_mtime_ns]!=version:
            raise ValueError('Transported mesh changed since acceptance; recapture before production')
