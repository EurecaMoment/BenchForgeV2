"""Persisted recipe execution; durable remote submissions and local artifacts resume."""
import json
import os
import urllib.request
from pathlib import Path
from ..runtime import read, write
from .production import produce, package

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
    token = config.get('operator_token') or os.environ[config.get('operator_token_env', 'SPATIALFORGE_OPERATOR_TOKEN')]
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
        if recipe['id'] == 'data.capability':
            steps = [dict(row) for row in steps]
            steps[0] = {**steps[0], 'arguments': {'selections': '$inputs.selections', 'evidence': '$inputs.evidence', 'seed': '$inputs.seed', 'split': '$inputs.split'}}
        nested = {'schema': 'spatialforge.pipeline/v1', 'version': 1, 'pipeline_id': recipe['id'], 'inputs': inputs, 'steps': steps}
        nested_path = Path(directory)/'nested-plan.json'
        write(nested_path, nested)
        nested_root = Path(directory)/'nested-run'
        saved = nested_root/'plan.json'
        if saved.exists():
            write(nested_path, read(saved))
        return run({'plan': str(nested_path), 'run': str(nested_root), '_workspace': environment['_workspace'], 'bindings': inputs}, directory, client=client)
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
    environment = {'inputs': {**plan['inputs'], **args.get('bindings', {})}, '_workspace': args['_workspace'], '_run_key': str(run_root)}
    environment['_run_key'] = 'pipeline.'+run_root.parent.name+'.'+run_root.name
    for step in plan['steps']:
        prior = state['steps'].get(step['id'])
        if prior and prior['state'] == 'completed':
            arguments = bind(step.get('arguments', {}), environment)
            if read(run_root/'steps'/step['id']/'request.json') != arguments:
                raise ValueError('Completed step inputs changed; create a new plan/run')
            environment[step['id']] = prior['result']
            continue
        step_root = run_root/'steps'/step['id']
        step_root.mkdir(parents=True, exist_ok=True)
        try:
            arguments = bind(step.get('arguments', {}), environment)
            write(step_root/'request.json', arguments)
            result = execute_step(step, arguments, step_root, environment, client)
            if result.get('state') in ('needs_evidence', 'needs_input', 'waiting'):
                state['steps'][step['id']] = {'state': result['state'], 'result': result}
                state['state'] = result['state']
                state['next'] = 'Read exact template conditions, generate/source evidence and rerun with bindings.evidence. Completed upstream steps remain reusable.'
                write(state_path, state)
                return {'run': str(run_root.resolve()), **state}
            if step.get('await_terminal'):
                lifecycle = result.get('state')
                if lifecycle in ('FAILED_FINAL', 'CANCELED'):
                    raise RuntimeError('Upstream scene lifecycle failed: '+str(result))
                if lifecycle != 'SUCCEEDED':
                    state['steps'][step['id']] = {'state': 'waiting', 'result': result}
                    state['state'] = 'waiting'
                    write(state_path, state)
                    return {'run': str(run_root.resolve()), **state}
            write(step_root/'result.json', result)
            state['steps'][step['id']] = {'state': 'completed', 'result': result}
            environment[step['id']] = result
            state['state'] = 'running'
            write(state_path, state)
        except MissingBinding as error:
            state.update(state='needs_input', missing_binding=str(error), step=step['id'])
            write(state_path, state)
            return {'run': str(run_root.resolve()), **state}
        except Exception as error:
            state['steps'][step['id']] = {'state': 'failed', 'error': str(error)}
            state['state'] = 'failed'
            write(state_path, state)
            raise
    state['state'] = 'completed'
    state.pop('next', None)
    state.pop('missing_binding', None)
    state.pop('step', None)
    write(state_path, state)
    return {'run': str(run_root.resolve()), 'outputs': {k: v['result'] for k, v in state['steps'].items()}, **state}


def pipeline_run(args, directory, config=None):
    # Core operations directory is workspace/operations/id.
    return run({**args, '_workspace': str(Path(directory).parents[1])}, directory, config)


def status(args, directory=None, config=None):
    return {'run': str(Path(args['run']).resolve()), **read(Path(args['run'])/'state.json')}
