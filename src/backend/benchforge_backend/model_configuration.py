"""One operator-owned model registry, shared by the service and agent clients."""
from copy import deepcopy
import os
from pathlib import Path

from .provider_config import (
    GATEWAY_PROVIDERS, INFERENCE_FIELDS, INFERENCE_TOKEN_ENV, ISAAC_PROVIDER, LLM_PROVIDER, MODEL_FIELDS,
    inference_config, llm_base_url, selected_model,
)
from .runtime_config import environment_value, read_json


def _defaults(value, defaults):
    for key, item in defaults.items():
        if key not in value:
            value[key] = deepcopy(item)
        elif isinstance(value[key], dict) and isinstance(item, dict):
            _defaults(value[key], item)


def _anchored(value, directory):
    if not isinstance(value, str) or not value or '$' in value or '%' in value:
        return value
    path = Path(value).expanduser()
    # Do not resolve the interpreter symlink out of its virtual environment.
    return os.path.abspath(path if path.is_absolute() else directory / path)


def initialize_model_config(path, server_path, server, environment):
    """Read model declarations saved before the unified configuration."""
    path, server_path = Path(path), Path(server_path)
    value = read_json(path) if path.is_file() else {}
    old_reference = server.get('models_config')
    if old_reference:
        old_path = Path(old_reference).expanduser()
        if not old_path.is_absolute():
            old_path = server_path.parent / old_path
        if old_path.resolve() != path.resolve() and old_path.is_file():
            legacy = read_json(old_path)
            endpoint = environment_value('BENCHFORGE_INFERENCE_URL', environ=environment)
            if endpoint and 'generation' not in value:
                value['generation'] = {'mode': 'remote', 'service': 'model_services'}
                value.setdefault('model_services', {}).setdefault('url', endpoint)
                value['model_services'].setdefault('token_env', environment_value(
                    'BENCHFORGE_INFERENCE_TOKEN_ENV', 'BENCHFORGE_INFERENCE_TOKEN', environ=environment))
            elif legacy.get('models'):
                value.setdefault('generation', {'mode': 'local'})
            for name, spec in legacy.get('models', {}).items():
                migrated = dict(spec)
                for field in ('python', 'path'):
                    if field in migrated:
                        migrated[field] = _anchored(migrated[field], old_path.parent)
                _defaults(value.setdefault('models', {}).setdefault(name, {}), migrated)
            for name, source in legacy.get('sources', {}).items():
                value.setdefault('sources', {}).setdefault(name, _anchored(source, old_path.parent))
    old_model = {target: server[source] for source, target in (
        ('model_url', 'url'), ('model_id', 'model'), ('model_api_key_env', 'token_env')
    ) if server.get(source)}
    if old_model and 'scene' not in value.get('model_roles', {}):
        registered = value.setdefault('models', {})
        same = next((name for name, spec in registered.items()
                     if all(spec.get(key) == item for key, item in old_model.items())), None)
        name = same or 'scene'
        _defaults(registered.setdefault(name, {}), old_model)
        value.setdefault('model_roles', {})['scene'] = name
    return value


def upgrade_model_config(value, template, environment, *, previous_server=None):
    """Move v1/v2 model settings to the provider registry."""
    providers = deepcopy(template['providers'])
    inference = deepcopy(template['inference'])
    roles = {}
    for role in ('dsh', 'scene', 'annotation'):
        model = selected_model(value, role)
        if not model and role == 'annotation':
            model = value.get('models', {}).get('qwen', {})
        if model.get('url') and model.get('model') and not str(model['model']).startswith('YOUR_'):
            roles[role] = {key: item for key, item in model.items() if key in MODEL_FIELDS}
            roles[role]['url'] = llm_base_url(model['url'])
    previous_server = previous_server or {}
    if 'scene' not in roles:
        url = environment_value('BENCHFORGE_MODEL_URL', previous_server.get('model_url'), environ=environment)
        model = environment_value('BENCHFORGE_MODEL_ID', previous_server.get('model_id'), environ=environment)
        if url and model and not str(model).startswith('YOUR_'):
            roles['scene'] = {'url': llm_base_url(url), 'model': model}
            token_env = environment_value(
                'BENCHFORGE_MODEL_API_KEY_ENV', previous_server.get('model_api_key_env'), environ=environment
            )
            if token_env:
                roles['scene']['token_env'] = token_env
    if roles:
        lead = next(iter(roles.values()))
        variants = {role: roles.get(role, {}) for role in ('dsh', 'scene', 'annotation')
                    if roles.get(role, {}) != lead}
        providers[LLM_PROVIDER] = {**lead, **({'roles': variants} if variants else {})}

    generation = value.get('generation', {})
    legacy_service = generation.get('service', 'model_services')
    legacy_gateway = value.get(legacy_service, {})
    ambient_url = environment_value('BENCHFORGE_INFERENCE_URL', environ=environment)
    inference.update((key, item) for key, item in legacy_gateway.items() if key in INFERENCE_FIELDS)
    imported_token = None
    if legacy_gateway.get('url') or ambient_url:
        token_env = environment_value(
            'BENCHFORGE_INFERENCE_TOKEN_ENV', 'BENCHFORGE_INFERENCE_TOKEN', environ=environment
        )
        inference['token_env'] = legacy_gateway.get('token_env') or (
            token_env if environment_value(token_env, environ=environment) else None)
        configured = inference['token_env']
        if legacy_gateway.get('token') and (
            not configured or environment_value(configured, environ=environment) != legacy_gateway['token']
        ):
            inference['token_env'] = INFERENCE_TOKEN_ENV
            imported_token = legacy_gateway['token']
    if not inference.get('url') and generation.get('mode') != 'local':
        inference['url'] = ambient_url
    if inference.get('availability_url') == inference.get('url'):
        inference.pop('availability_url', None)
    for key, default in (('health_timeout_seconds', 10), ('http_timeout_seconds', 30)):
        if inference.get(key) == default:
            inference.pop(key, None)
    legacy_tools = legacy_gateway.get('tools', {})
    for tool, provider in GATEWAY_PROVIDERS.items():
        defaults = legacy_tools.get(tool, {}).get('request_defaults', {})
        if defaults:
            providers[provider].setdefault('request_defaults', {}).update(defaults)

    old_isaac = value.get('isaac', {})
    worker = value['worker']
    grpc = worker.pop('isaac_grpc', None) or old_isaac.get('grpc', {})
    if grpc:
        fields = ('host', 'port', 'timeout_seconds')
        providers[ISAAC_PROVIDER]['grpc'].update({key: grpc[key] for key in fields if key in grpc})
        grpc_settings = providers[ISAAC_PROVIDER]['grpc']
        for key in ('port', 'timeout_seconds'):
            item = grpc_settings.get(key)
            if isinstance(item, str) and item.isascii() and item.isdecimal():
                grpc_settings[key] = int(item)
        if grpc_settings.get('timeout_seconds') == 60:
            grpc_settings.pop('timeout_seconds')
        host = grpc_settings.get('host')
        if isinstance(host, str) and host.upper().startswith('YOUR_'):
            grpc_settings['host'] = None
    timeout = worker.pop('capture_timeout_seconds', old_isaac.get('capture_timeout_seconds'))
    if timeout is not None:
        providers[ISAAC_PROVIDER]['capture_timeout_seconds'] = float(timeout) if isinstance(timeout, str) else timeout
    for field in ('isaac_asset_root', 'runs'):
        if old_isaac.get(field):
            worker.setdefault(field, old_isaac[field])

    for key in ('isaac', 'model_roles', 'services', 'model_services'):
        value.pop(key, None)
    if legacy_service != 'model_services' and legacy_service not in ('web', 'server', 'client', 'worker', 'database', 'isaac'):
        value.pop(legacy_service, None)
    if generation.get('mode') == 'local':
        value['generation'] = {'mode': 'local'}
        local_models = {'flux', 'sam3', 'sam3d', 'depth_anything'}
        value['models'] = {name: spec for name, spec in value.get('models', {}).items()
                           if name in local_models and 'python' in spec}
        if 'sources' in value:
            value['sources'] = {name: source for name, source in value['sources'].items()
                                if name in local_models}
    else:
        for key in ('generation', 'models', 'sources'):
            value.pop(key, None)
    value.update(providers=providers, inference=inference)
    return imported_token


def apply_model_environment(config):
    """Adapt the single registry to existing model executors' environment API."""
    reference = config.get('models_config')
    if not reference or not Path(reference).is_file():
        return
    registry = read_json(reference)
    model = selected_model(registry, 'scene')
    if model.get('model') and not str(model['model']).startswith('YOUR_'):
        if not model.get('url'):
            raise ValueError('The scene model requires a URL in the unified model config')
        for source, target, variable in (('url', 'model_url', 'BENCHFORGE_MODEL_URL'),
                                         ('model', 'model_id', 'BENCHFORGE_MODEL_ID'),
                                         ('token_env', 'model_api_key_env', 'BENCHFORGE_MODEL_API_KEY_ENV')):
            if source in model:
                if model[source]:
                    config[target] = model[source]
                    os.environ[variable] = str(model[source])
                    continue
            if source == 'token_env':
                config.pop(target, None)
                os.environ.pop(variable, None)
                os.environ.pop('SPATIALFORGE_MODEL_API_KEY_ENV', None)
    elif 'providers' in registry:
        for field, variable in (('model_url', 'MODEL_URL'), ('model_id', 'MODEL_ID'),
                                ('model_api_key_env', 'MODEL_API_KEY_ENV')):
            config.pop(field, None)
            os.environ.pop('BENCHFORGE_' + variable, None)
            os.environ.pop('SPATIALFORGE_' + variable, None)
    generation = registry.get('generation', {})
    mode = generation.get('mode')
    if 'providers' in registry and mode != 'local':
        service = inference_config(registry)
        os.environ['BENCHFORGE_INFERENCE_URL'] = service.get('url') or ''
        if service.get('token_env'):
            os.environ['BENCHFORGE_INFERENCE_TOKEN_ENV'] = service['token_env']
        os.environ['BENCHFORGE_RECONSTRUCTION_PROVIDER'] = 'trellis2' if 'sam3d' in service['tools'] else ''
    elif mode == 'local':
        os.environ['BENCHFORGE_INFERENCE_URL'] = ''
    elif mode == 'remote':
        service = registry.get(generation.get('service', 'model_services'), {})
        if not service.get('url'):
            raise ValueError('Remote generation requires model_services.url in the unified model config')
        os.environ['BENCHFORGE_INFERENCE_URL'] = service['url']
        if service.get('token_env'):
            os.environ['BENCHFORGE_INFERENCE_TOKEN_ENV'] = service['token_env']
    elif mode is not None:
        raise ValueError('generation.mode must be remote or local')
