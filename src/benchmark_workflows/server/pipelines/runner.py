"""Persisted recipe execution; durable remote submissions and local artifacts resume."""
from pathlib import Path
from benchmark_workflows.server.storage.artifacts import read
from benchmark_workflows.server.storage.artifacts import write
from benchmark_workflows.server.pipelines.artifact_graph import ArtifactGraph
from benchmark_workflows.server.pipelines.artifact_graph import binding_roots
from benchmark_workflows.server.pipelines.artifact_graph import make_record
from benchmark_workflows.server.pipelines.repair import create_plan
from benchmark_workflows.server.dataset_authoring.production import produce
from benchmark_workflows.server.dataset_authoring.production import package
from benchmark_workflows.server.pipelines.stage_review import STAGES
from benchmark_workflows.server.pipelines.stage_review import gate
from benchmark_workflows.server.pipelines.stage_review import review
from benchmark_workflows.server.assessment_planning.plan_versions import current as active_plan
from scene_production.api import check_source
from scene_production.api import load_policy
from benchmark_workflows.server.pipelines.execution_lock import exclusive_run
from benchmark_workflows.server.pipelines.bindings import MissingBinding
from benchmark_workflows.server.pipelines.bindings import bind
from benchmark_workflows.server.pipelines.review_steps import stage_of
from benchmark_workflows.server.pipelines.review_steps import review_scope
from benchmark_workflows.server.pipelines.review_steps import completed_stage
from service_access.scene_service import service_call

SERVICE_ROUTES = {'benchforge.start': '/start', 'benchforge.capture': '/capture',
                  'benchforge.asset': '/asset', 'benchforge.refine': '/refine', 'benchforge.extend': '/extend',
                  'benchforge.observe': '/inspect', 'benchforge.evidence': '/evidence',
                  'benchforge.task_code': '/task-code'}


def execute_step(step, arguments, directory, environment, client):
    operation = step['uses']
    if operation == 'pipeline':
        from benchmark_workflows.server.assessment_planning.catalog import pipeline_files
        recipes = {p['id']: p for p in pipeline_files()}
        recipe = recipes[step['pipeline_id']]
        inputs = arguments
        steps = recipe['steps']
        nested = {'schema': 'benchforge.pipeline/v1', 'version': 1, 'pipeline_id': recipe['id'], 'inputs': inputs, 'steps': steps}
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
        return produce({**arguments, '_workspace': environment['_workspace'],
                        '_service_config': environment['inputs'].get('service_config')}, directory)
    if operation == 'data.package':
        return package(arguments, directory)
    if operation in SERVICE_ROUTES:
        session_id = environment.get('_dsh_context', {}).get('session_id')
        if session_id:
            request_context = arguments.setdefault('context', {})
            if not isinstance(request_context, dict):
                raise ValueError('context must be an object')
            if request_context.get('session_id') not in (None, session_id):
                raise ValueError('context.session_id conflicts with the active DSH session')
            request_context['session_id'] = session_id
        if operation in ('benchforge.start', 'benchforge.capture', 'benchforge.asset', 'benchforge.refine', 'benchforge.extend'):
            arguments.setdefault('request_key', environment['_run_key']+'.'+step['id'])
        if not environment['inputs'].get('service_config'):
            raise MissingBinding('$inputs.service_config')
        result = client(SERVICE_ROUTES[operation], arguments, environment['inputs']['service_config'])
        if operation == 'benchforge.task_code' and (result['returncode'] != 0 or result.get('timed_out')):
            raise RuntimeError('Task-code adapter failed: '+str(result))
        return result
    raise ValueError(f'Unknown pipeline operation: {operation}')


def run(args, directory, config=None, client=service_call):
    """Advance one run under a lock; status readers need not acquire it."""
    run_root = Path(args['run']).resolve() if args.get('run') else Path(directory) / 'pipeline_run'
    with exclusive_run(run_root):
        return _run_locked(args, directory, config, client)


def _run_locked(args, directory, config, client):
    plan_path = Path(args['plan']).resolve()
    plan = read(plan_path)
    inputs = {**plan.get('inputs', {}), **args.get('bindings', {})}
    service_config = inputs.get('service_config')
    policy = load_policy(args['_workspace'], service_config)
    check_source(policy, source_path=plan_path)
    run_root = Path(args['run']).resolve() if args.get('run') else Path(directory)/'pipeline_run'
    run_root.mkdir(parents=True, exist_ok=True)
    frozen = run_root/'plan.json'
    if frozen.exists() and read(frozen) != plan:
        raise ValueError('Plan changed; create a new pipeline run to retain prior evidence')
    write(frozen, plan)
    state_path = run_root/'state.json'
    state = read(state_path) if state_path.exists() else {'schema': 'benchforge.pipeline-state/v1', 'steps': {}, 'state': 'running'}
    if 'schema' in state:
        state['schema'] = state['schema']
    state.setdefault('run_id', f'run-{run_root.name}')
    execution_mode = policy['execution_mode']
    prior_mode = state.get('execution_mode')
    if prior_mode and prior_mode != execution_mode:
        raise ValueError('Execution mode changed; create a new pipeline run to preserve its original policy')
    state['execution_mode'] = execution_mode
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
    environment = {'inputs': inputs, '_workspace': args['_workspace'], '_dsh_context': context,
                   '_run_key': 'pipeline:'+run_root.as_posix(), '_review_scope': scope}
    def plan_guard():
        owner_plan = scope['plan'] if scope else str(plan_path)
        active=active_plan(args['_workspace'],session) if session else None
        same_plan = bool(active) and Path(active['plan']).resolve() == Path(owner_plan).resolve()
        if active and (not same_plan or active['pending']):
            state.update(state='needs_plan_application' if same_plan else 'plan_superseded',
                active_plan=active['plan'],changed_sections=active['changes'],
                next='Read the saved edited assessment, update scene/task code and executable steps, and call pipeline_plan with applies_edit='+active['plan']+'. Retain its assessment, allocation and inputs. Use a new run; do not execute the old plan.')
            write(state_path,state)
            return {'run':str(run_root.resolve()),**state}
        if active and not args.get('_review_nested'):
            for key in ('seed','split','target_items','selections','scene_selection','target_scene_count','preserve_source_splits'):
                expected = plan['inputs'].get(key, False) if key == 'preserve_source_splits' else plan['inputs'].get(key)
                if key in args.get('bindings',{}) and args['bindings'][key]!=expected:
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
            initial = gate(args['_workspace'],session,'S1',plan.get('stage_review_key',str(plan_path)),str(plan_path))
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
            artifact = {'schema': 'benchforge.stage-review/v1', 'stage': stage,
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
