"""Persisted recipe execution; durable remote submissions and local artifacts resume."""
import json
import os
import urllib.request
from pathlib import Path
from ..runtime import read, write
from .artifact_graph import ArtifactGraph, binding_roots, make_record
from .repair import create_plan
from .production import produce, package
from ..stage_review import STAGES, gate, review
from .plan_versions import current as active_plan
from .scene_policy import check_submission, check_source, load_policy

SERVICE_ROUTES = {'spatialforge.start': '/start', 'spatialforge.capture': '/capture',
                  'spatialforge.asset': '/asset', 'spatialforge.refine': '/refine', 'spatialforge.extend': '/extend',
                  'spatialforge.observe': '/inspect', 'spatialforge.evidence': '/evidence',
                  'spatialforge.task_code': '/task-code'}


class MissingBinding(ValueError):
    pass


def bind(value, environment):
    if isinstance(value, str) and value.startswith('$'):
        current = environment
        for key in value[1:].split('.'):
            if isinstance(current, list):
                current = current[int(key)]
                continue
            if key not in current:
                raise MissingBinding(value)
            current = current[key]
        return current
    if isinstance(value, list):
        return [bind(v, environment) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            try:
                result[key] = bind(child, environment)
            except MissingBinding:
                if key not in ('evidence', 'capture_options'):
                    raise
        return result
    return value


def service_call(route, arguments, config_path):
    config = read(config_path)
    url = config.get('service_url') or f"http://127.0.0.1:{config.get('port', 3841)}"
    token = config.get('operator_token') or os.environ.get(config.get('operator_token_env', 'SPATIALFORGE_OPERATOR_TOKEN'))
    if not token:
        raise ValueError('Configure operator_token in the SpatialForge service configuration')
    request = urllib.request.Request(url.rstrip('/')+route, data=json.dumps(arguments).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+token})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=60) as response:
        return json.load(response)


def execute_step(step, arguments, directory, environment, client):
    operation = step['uses']
    if operation == 'pipeline':
        from .catalog import pipeline_files
        recipes = {p['id']: p for p in pipeline_files()}
        recipe = recipes[step['pipeline_id']]
        inputs = arguments
        steps = recipe['steps']
        nested = {'schema': 'spatialforge.pipeline/v1', 'version': 1, 'pipeline_id': recipe['id'], 'inputs': inputs, 'steps': steps}
        nested_path = Path(directory)/'nested-plan.json'
        write(nested_path, nested)
        nested_root = Path(directory)/'nested-run'
        saved = nested_root/'plan.json'
        if saved.exists():
            write(nested_path, read(saved))
        return run({'plan': str(nested_path), 'run': str(nested_root), '_workspace': environment['_workspace'], 'bindings': inputs,
                    '_dsh_context': environment.get('_dsh_context', {}), '_review_nested':True,
                    '_review_scope': environment.get('_review_scope')}, directory, client=client)
    if operation == 'templates.produce':
        return produce({**arguments, '_workspace': environment['_workspace']}, directory)
    if operation == 'data.package':
        return package(arguments, directory)
    if operation in SERVICE_ROUTES:
        check_submission(environment['_workspace'], SERVICE_ROUTES[operation], arguments)
        if operation in ('spatialforge.start', 'spatialforge.capture', 'spatialforge.asset', 'spatialforge.refine', 'spatialforge.extend'):
            arguments.setdefault('request_key', environment['_run_key']+'.'+step['id'])
        if not environment['inputs'].get('service_config'):
            raise MissingBinding('$inputs.service_config')
        result = client(SERVICE_ROUTES[operation], arguments, environment['inputs']['service_config'])
        if operation == 'spatialforge.task_code' and (result['returncode'] != 0 or result.get('timed_out')):
            raise RuntimeError('Task-code adapter failed: '+str(result))
        return result
    raise ValueError(f'Unknown pipeline operation: {operation}')


def stage_of(step):
    if step.get('review_stage') in ('S1','S2','S3','S4','S5'):
        return step['review_stage']
    return {'spatialforge.start':'S2','spatialforge.capture':'S2','spatialforge.observe':'S2',
            'spatialforge.refine':'S2','spatialforge.extend':'S2','spatialforge.asset':'S2','spatialforge.evidence':'S3',
            'templates.produce':'S4','data.package':'S5'}.get(step['uses'])


def review_scope(plan, run_root, plan_path):
    """One review owner for the leaf artifacts of a composed production run."""
    members = {stage: [] for stage in STAGES[1:]}
    recipes = None

    def expand(steps, root, prefix=''):
        nonlocal recipes
        consumed = set()
        for step in steps:
            for source in binding_roots(step.get('arguments', {})):
                consumed.add(source)
        for step in steps:
            step_root = root/'steps'/step['id']
            label = prefix+step['id']
            if step['uses'] == 'pipeline':
                nested_root = step_root/'nested-run'
                saved = nested_root/'plan.json'
                if saved.exists():
                    nested_steps = read(saved)['steps']
                else:
                    if recipes is None:
                        from .catalog import pipeline_files
                        recipes = {recipe['id']: recipe for recipe in pipeline_files()}
                    nested_steps = recipes[step['pipeline_id']]['steps']
                expand(nested_steps, nested_root, label+'/')
            else:
                stage = stage_of(step)
                if stage in members:
                    members[stage].append({'step': step['id'], 'label': label, 'uses': step['uses'],
                        'run': str(root.resolve()), 'result_path': str((step_root/'result.json').resolve()),
                        'terminal': step['id'] not in consumed})

    expand(plan['steps'], run_root)
    return {'run': str(run_root.resolve()), 'plan': str(plan_path), 'members': members, 'continued_stages': []}


def completed_stage(scope, stage):
    """Receipts are retained, but a review needs every planned stage artifact."""
    members = scope['members'][stage]
    if not members:
        return None
    states = {}
    # The last planned artifact is usually unfinished; check it first so large
    # scene batches do not reread every completed scene on each submission.
    for member in reversed(members):
        root = member['run']
        if root not in states:
            path = Path(root)/'state.json'
            states[root] = read(path).get('steps', {}) if path.exists() else {}
        prior = states[root].get(member['step'])
        if not prior or prior['state'] != 'completed':
            return None
    outputs = []
    for member in members:
        result_path = Path(member['result_path'])
        if not result_path.is_file():
            return None
        result = read(result_path)
        if member['terminal'] and result.get('state') in ('RUNNING', 'READY'):
            return None
        outputs.append({'step': member['label'], 'uses': member['uses'],
                        'result_path': member['result_path'], 'result': result})
    return outputs


def run(args, directory, config=None, client=service_call):
    plan_path = Path(args['plan']).resolve()
    check_source(load_policy(args['_workspace']), source_path=plan_path)
    plan = read(plan_path)
    run_root = Path(args['run']).resolve() if args.get('run') else Path(directory)/'pipeline_run'
    run_root.mkdir(parents=True, exist_ok=True)
    frozen = run_root/'plan.json'
    if frozen.exists() and read(frozen) != plan:
        raise ValueError('Plan changed; create a new pipeline run to retain prior evidence')
    write(frozen, plan)
    state_path = run_root/'state.json'
    state = read(state_path) if state_path.exists() else {'schema': 'spatialforge.pipeline-state/v1', 'steps': {}, 'state': 'running'}
    state.setdefault('run_id', f'run-{run_root.name}')
    context = args.get('_dsh_context', {})
    session = context.get('session_id')
    scope = args.get('_review_scope') or (review_scope(plan, run_root, plan_path) if session else None)
    if context.get('session_id'):
        sessions = state.setdefault('context', {}).setdefault('session_ids', [])
        if context['session_id'] not in sessions:
            sessions.append(context['session_id'])
        write(state_path, state)
    graph = ArtifactGraph(run_root)
    artifact_ids = {}
    # The full persisted run path distinguishes nested recipes in separate plans
    # and stays the same when an interrupted submission is resumed.
    environment = {'inputs': {**plan['inputs'], **args.get('bindings', {})}, '_workspace': args['_workspace'], '_dsh_context': context,
                   '_run_key': 'pipeline:'+run_root.as_posix(), '_review_scope': scope}
    def plan_guard():
        owner_plan = scope['plan'] if scope else str(plan_path)
        active=active_plan(args['_workspace'],session) if session else None
        if active and (active['plan']!=owner_plan or active['pending']):
            state.update(state='needs_plan_application' if active['plan']==owner_plan else 'plan_superseded',
                active_plan=active['plan'],changed_sections=active['changes'],
                next='Read the saved edited assessment, update scene/task code and executable steps, and call pipeline_plan with applies_edit='+active['plan']+'. Retain its assessment, allocation and inputs. Use a new run; do not execute the old plan.')
            write(state_path,state)
            return {'run':str(run_root.resolve()),**state}
        if active and not args.get('_review_nested'):
            for key in ('seed','split','target_items','selections','scene_selection','target_scene_count'):
                if key in args.get('bindings',{}) and args['bindings'][key]!=plan['inputs'].get(key):
                    raise ValueError('Run bindings must honor the active edited '+key)
    blocked=plan_guard()
    if blocked:return blocked
    def waiting(value):
        state.update(state=value['state'], stage_review=value,
                     next='Wait for the user review window with stage_review(action=wait), then resume this same run. Apply pending user instructions first.')
        write(state_path,state)
        return {'run':str(run_root.resolve()), **state}
    if session:
        current = review(args['_workspace'],session)
        if current['state'] in ('waiting_user','paused','needs_input'):
            return waiting(current)
        if not args.get('_review_nested'):
            initial = gate(args['_workspace'],session,'S1',str(plan_path),str(plan_path))
            if not initial['can_continue']:
                return waiting(initial)
    def checkpoint():
        if not session:
            return None
        for stage in STAGES[1:]:
            if not scope['members'][stage] or stage in scope['continued_stages']:
                continue
            outputs = completed_stage(scope, stage)
            if outputs is None:
                return None
            artifact_path = Path(scope['run'])/'reviews'/(stage+'.json')
            artifact = {'schema': 'spatialforge.stage-review/v1', 'stage': stage,
                        'plan': scope['plan'], 'outputs': outputs}
            if not artifact_path.exists() or read(artifact_path) != artifact:
                write(artifact_path, artifact)
            value = gate(args['_workspace'],session,stage,scope['run']+':stage:'+stage,str(artifact_path))
            if not value['can_continue']:
                return waiting(value)
            scope['continued_stages'].append(stage)
        return None
    for step in plan['steps']:
        blocked=plan_guard()
        if blocked:return blocked
        prior = state['steps'].get(step['id'])
        if prior and prior['state'] == 'completed':
            arguments = bind(step.get('arguments', {}), environment)
            if read(run_root/'steps'/step['id']/'request.json') != arguments:
                raise ValueError('Completed step inputs changed; create a new plan/run')
            environment[step['id']] = prior['result']
            prior_artifact = prior.get('artifact')
            if prior_artifact:
                artifact_ids[step['id']] = prior_artifact.get('artifact_id')
            pending = checkpoint()
            if pending:
                return pending
            continue
        step_root = run_root/'steps'/step['id']
        step_root.mkdir(parents=True, exist_ok=True)
        try:
            arguments = bind(step.get('arguments', {}), environment)
            write(step_root/'request.json', arguments)
            parent_ids = [artifact_ids[root] for root in binding_roots(step.get('arguments', {})) if root in artifact_ids]
            result = execute_step(step, arguments, step_root, environment, client)
            result_path = step_root/'result.json'
            operation = step.get('uses', 'pipeline')
            # Persist non-terminal receipts too; artifact manifests must point
            # to a readable result when a run pauses for evidence or input.
            write(result_path, result)
            artifact = make_record(graph=graph, run_id=state['run_id'], step_id=step['id'],
                                  operation=operation, arguments=arguments, result=result,
                                  parent_ids=parent_ids, declared_type=step.get('artifact_type'),
                                  result_path=str(result_path.resolve()))
            if result.get('state') in ('needs_evidence', 'needs_input', 'waiting','waiting_user','paused',
                                       'needs_plan_application', 'plan_superseded'):
                state['steps'][step['id']] = {'state': result['state'], 'result': result, 'artifact': artifact}
                state['state'] = result['state']
                state['next'] = result.get('next') or 'Read exact template conditions, generate/source evidence and rerun with bindings.evidence. Completed upstream steps remain reusable.'
                if result.get('stage_review'):
                    state['stage_review'] = result['stage_review']
                write(state_path, state)
                return {'run': str(run_root.resolve()), **state}
            if step.get('await_terminal'):
                lifecycle = result.get('state')
                if lifecycle in ('FAILED_FINAL', 'CANCELED'):
                    raise RuntimeError('Upstream scene lifecycle failed: '+str(result))
                if lifecycle != 'SUCCEEDED':
                    state['steps'][step['id']] = {'state': 'waiting', 'result': result, 'artifact': artifact}
                    state['state'] = 'waiting'
                    write(state_path, state)
                    return {'run': str(run_root.resolve()), **state}
            state['steps'][step['id']] = {'state': 'completed', 'result': result, 'artifact': artifact}
            environment[step['id']] = result
            artifact_ids[step['id']] = artifact['artifact_id']
            state['state'] = 'running'
            write(state_path, state)
            pending = checkpoint()
            if pending:
                return pending
        except MissingBinding as error:
            artifact = make_record(graph=graph, run_id=state['run_id'], step_id=step['id'],
                                  operation=step.get('uses', 'pipeline'), arguments=step.get('arguments', {}),
                                  result={}, parent_ids=[], declared_type=step.get('artifact_type'),
                                  result_path=None, error=str(error))
            repair = create_plan(run=run_root, artifact=artifact, failure_code='missing_binding', reason=str(error))
            graph.append_repair(repair)
            state.update(state='needs_input', missing_binding=str(error), step=step['id'], artifact=artifact, repair=repair)
            write(state_path, state)
            return {'run': str(run_root.resolve()), **state}
        except Exception as error:
            artifact = make_record(graph=graph, run_id=state['run_id'], step_id=step['id'],
                                  operation=step.get('uses', 'pipeline'), arguments=step.get('arguments', {}),
                                  result={}, parent_ids=[], declared_type=step.get('artifact_type'),
                                  result_path=None, error=str(error))
            repair = create_plan(run=run_root, artifact=artifact, failure_code='execution_error', reason=str(error))
            graph.append_repair(repair)
            state['steps'][step['id']] = {'state': 'failed', 'error': str(error), 'artifact': artifact, 'repair': repair}
            state['state'] = 'failed'
            write(state_path, state)
            raise
    state['state'] = 'completed'
    state.pop('next', None)
    state.pop('missing_binding', None)
    state.pop('step', None)
    state.pop('stage_review', None)
    write(state_path, state)
    return {'run': str(run_root.resolve()), 'outputs': {k: v['result'] for k, v in state['steps'].items()}, **state}


def pipeline_run(args, directory, config=None):
    # Core operations directory is workspace/operations/id.
    return run({**args, '_workspace': str(Path(directory).parents[1])}, directory, config)


def status(args, directory=None, config=None):
    return {'run': str(Path(args['run']).resolve()), **read(Path(args['run'])/'state.json')}
