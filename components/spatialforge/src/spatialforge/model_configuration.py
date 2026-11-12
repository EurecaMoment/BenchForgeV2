"""One operator-owned model registry, shared by the service and agent clients."""
from copy import deepcopy
import os
from pathlib import Path

from .runtime_config import read_json


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


def initialize_model_config(path, template, server_path, server, write):
    """Import old declarations once; existing canonical fields always win.

    The old files remain on disk, but new server configuration references only
    this registry. Credentials are environment-variable names, never copied from
    the process environment.
    """
    path, template, server_path = Path(path), Path(template), Path(server_path)
    value = read_json(path) if path.is_file() else {}
    original = deepcopy(value)
    old_reference = server.get('models_config')
    if old_reference:
        old_path = Path(old_reference).expanduser()
        if not old_path.is_absolute():
            old_path = server_path.parent / old_path
        if old_path.resolve() != path.resolve() and old_path.is_file():
            legacy = read_json(old_path)
            endpoint = os.environ.get('SPATIALFORGE_INFERENCE_URL')
            if endpoint and 'generation' not in value:
                value['generation'] = {'mode': 'remote', 'service': 'model_services'}
                value.setdefault('model_services', {}).setdefault('url', endpoint)
                value['model_services'].setdefault('token_env', os.environ.get(
                    'SPATIALFORGE_INFERENCE_TOKEN_ENV', 'SPATIALFORGE_INFERENCE_TOKEN'))
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
    _defaults(value, read_json(template))
    if not path.exists() or value != original:
        write(path, value)
    return value


def selected_model(registry, role):
    """Resolve role references without duplicating URLs or model IDs."""
    name = registry.get('model_roles', {}).get(role)
    if name is None:
        return {}
    spec = registry.get('models', {}).get(name)
    if not isinstance(spec, dict):
        raise ValueError(f'model_roles.{role} references an unknown model: {name}')
    return spec


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
        for source, target, variable in (('url', 'model_url', 'SPATIALFORGE_MODEL_URL'),
                                         ('model', 'model_id', 'SPATIALFORGE_MODEL_ID'),
                                         ('token_env', 'model_api_key_env', 'SPATIALFORGE_MODEL_API_KEY_ENV')):
            if source in model:
                config[target] = model[source]
                os.environ[variable] = str(model[source])
    generation = registry.get('generation', {})
    if generation.get('mode') == 'remote':
        service = registry.get(generation.get('service', 'model_services'), {})
        if not service.get('url'):
            raise ValueError('Remote generation requires model_services.url in the unified model config')
        os.environ['SPATIALFORGE_INFERENCE_URL'] = service['url']
        if service.get('token_env'):
            os.environ['SPATIALFORGE_INFERENCE_TOKEN_ENV'] = service['token_env']
    elif generation.get('mode') == 'local':
        os.environ.pop('SPATIALFORGE_INFERENCE_URL', None)
    elif generation.get('mode') is not None:
        raise ValueError('generation.mode must be remote or local')
