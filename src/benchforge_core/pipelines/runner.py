"""Persisted recipe execution; durable remote submissions and local artifacts resume."""
import json
import os
import urllib.request
from pathlib import Path
from ..runtime import read, write
from .artifact_graph import ArtifactGraph, binding_roots, make_record
from .repair import create_plan
from .production import produce, package
from ..stage_review import gate, review
from .plan_versions import current as active_plan

SERVICE_ROUTES = {'spatialforge.start': '/start', 'spatialforge.capture': '/capture',
                  'spatialforge.asset': '/asset', 'spatialforge.refine': '/refine',
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
                    '_dsh_context': environment.get('_dsh_context', {}), '_review_nested':True}, directory, client=client)
    if operation == 'templates.produce':
        return produce({**arguments, '_workspace': environment['_workspace']}, directory)
    if operation == 'data.package':
        return package(arguments, directory)
    if operation in SERVICE_ROUTES:
        if operation in ('spatialforge.start', 'spatialforge.capture', 'spatialforge.asset', 'spatialforge.refine'):
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
            'spatialforge.refine':'S2','spatialforge.asset':'S2','spatialforge.evidence':'S3',
            'templates.produce':'S4','data.package':'S5'}.get(step['uses'])


def run(args, directory, config=None, client=service_call):
    plan_path = Path(args['plan']).resolve()
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
                   '_run_key': 'pipeline:'+run_root.as_posix()}
    session = context.get('session_id')
    def plan_guard():
        active=active_plan(args['_workspace'],session) if session and not args.get('_review_nested') else None
        if active and (active['plan']!=str(plan_path) or active['pending']):
            state.update(state='needs_plan_application' if active['plan']==str(plan_path) else 'plan_superseded',
                active_plan=active['plan'],changed_sections=active['changes'],
                next='Read the saved edited assessment, update scene/task code and executable steps, and call pipeline_plan with applies_edit='+active['plan']+'. Retain its assessment, allocation and inputs. Use a new run; do not execute the old plan.')
            write(state_path,state)
            return {'run':str(run_root.resolve()),**state}
        if active:
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
    def checkpoint(index, step, result):
        stage = stage_of(step)
        next_stage = stage_of(plan['steps'][index+1]) if index+1 < len(plan['steps']) else None
        if not session or not stage or stage == next_stage or result.get('state') in ('RUNNING','READY'):
            return None
        value = gate(args['_workspace'],session,stage,str(run_root.resolve())+':'+step['id'],
                     str((run_root/'steps'/step['id']/'result.json').resolve()))
        return waiting(value) if not value['can_continue'] else None
    for index, step in enumerate(plan['steps']):
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
            pending = checkpoint(index,step,prior['result'])
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
            if result.get('state') in ('needs_evidence', 'needs_input', 'waiting','waiting_user','paused'):
                state['steps'][step['id']] = {'state': result['state'], 'result': result, 'artifact': artifact}
                state['state'] = result['state']
                state['next'] = 'Read exact template conditions, generate/source evidence and rerun with bindings.evidence. Completed upstream steps remain reusable.'
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
            pending = checkpoint(index,step,result)
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
