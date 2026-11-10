"""Resolve SpatialForge service and model configuration files."""
import json
import os
from pathlib import Path
import re


_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|%([A-Za-z_][A-Za-z0-9_]*)%")
_PATH_ENVIRONMENT = {
    'artifacts': 'SPATIALFORGE_ARTIFACTS',
    'harness': 'SPATIALFORGE_HARNESS',
    'models_config': 'SPATIALFORGE_MODELS_CONFIG',
    'task_root': 'SPATIALFORGE_TASK_ROOT',
    'scene_policy_path': 'SPATIALFORGE_SCENE_POLICY',
}


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path):
    """Read strict JSON and reject duplicate keys at every nesting level."""
    path = Path(path).expanduser().resolve()
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)


def expand_environment(value, environ=None):
    """Expand ${NAME}, $NAME and %NAME% references, failing on missing values."""
    if not isinstance(value, str):
        raise ValueError('configuration path/value must be a string')
    environ = os.environ if environ is None else environ

    def replace(match):
        name = next(part for part in match.groups() if part is not None)
        if name not in environ:
            raise ValueError(f'configuration references unset environment variable {name}')
        return environ[name]

    return _ENV_REFERENCE.sub(replace, value)


def resolve_path(value, config_path, environ=None):
    path = Path(expand_environment(os.fspath(value), environ)).expanduser()
    if not path.is_absolute():
        path = Path(config_path).parent / path
    return path.resolve()


def _resolve_environment_value(config, key, env_name, config_path):
    if env_name in os.environ:
        value = os.environ[env_name]
    else:
        value = config.get(key)
    if value is None:
        return None
    if key in _PATH_ENVIRONMENT:
        return str(resolve_path(value, config_path))
    return expand_environment(str(value)) if isinstance(value, str) else value


class RuntimeConfig:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.data = read_json(self.path)
        for model in self.data.get('models', {}).values():
            for key in ('python', 'path'):
                if key not in model:
                    continue
                model_path = resolve_path(model[key], self.path)
                # Keep venv interpreter symlinks; resolving them can change sys.prefix.
                model[key] = os.path.abspath(model_path) if key == 'python' else str(model_path)
        for name, value in self.data.get('sources', {}).items():
            self.data['sources'][name] = str(resolve_path(value, self.path))

    def model(self, name):
        if name not in self.data.get('models', {}):
            raise ValueError(f'Configure models.{name} in {self.path} before using that tool')
        return self.data['models'][name]


def _token(config, name, required):
    env_key = name + '_token_env'
    env_name = config.get(env_key)
    if env_name:
        env_name = expand_environment(str(env_name))
        value = os.environ.get(env_name)
        if not value and required:
            raise ValueError(f'{name}_token_env references unset environment variable {env_name}')
    else:
        value = config.get(name + '_token') or os.environ.get('SPATIALFORGE_' + name.upper() + '_TOKEN')
    if not value and required:
        raise ValueError(f'{name}_token must not be empty')
    config[name + '_token'] = value or ''


def load_service_config(path, *, required_tokens=('operator', 'worker')):
    """Load server configuration, resolve paths, and set its runtime environment."""
    path = Path(path).expanduser().resolve()
    config = read_json(path)
    if not isinstance(config, dict):
        raise ValueError('SpatialForge service configuration must be a JSON object')
    if config.get('service_config'):
        base_path = resolve_path(config['service_config'], path)
        base = read_json(base_path)
        if not isinstance(base, dict):
            raise ValueError('referenced SpatialForge service configuration must be a JSON object')
        overrides = {key: value for key, value in config.items() if key != 'service_config'}
        for key, value in overrides.items():
            if key in base and base[key] != value and key in {'port', 'service_url', 'execution_mode', 'scene_policy_path'}:
                raise ValueError(f'{key} in {path.name} conflicts with referenced service configuration')
        config = {**base, **overrides}
        path = base_path

    configured_mode = config.get('execution_mode')
    environment_mode = os.environ.get('SPATIALFORGE_EXECUTION_MODE')
    if configured_mode is not None and environment_mode is not None and configured_mode != environment_mode:
        raise ValueError('SPATIALFORGE_EXECUTION_MODE conflicts with configured execution_mode')
    mode = configured_mode if configured_mode is not None else environment_mode or 'production'
    if mode not in ('production', 'exploration'):
        raise ValueError('execution_mode must be production or exploration')
    config['execution_mode'] = mode
    os.environ['SPATIALFORGE_EXECUTION_MODE'] = mode

    for key, env_name in _PATH_ENVIRONMENT.items():
        resolved = _resolve_environment_value(config, key, env_name, path)
        if resolved is not None:
            config[key] = resolved

    # Keep legacy local.json files usable while making the selected client route explicit.
    raw_url = os.environ.get('SPATIALFORGE_SERVICE_URL') or config.get('service_url')
    if raw_url:
        config['service_url'] = expand_environment(str(raw_url))
    else:
        port = int(config.get('port', 3841))
        if not 1 <= port <= 65535:
            raise ValueError('port must be between 1 and 65535')
        config['service_url'] = f"http://127.0.0.1:{port}"

    for name in ('operator', 'worker'):
        _token(config, name, name in required_tokens)
    if config.get('database_url_env'):
        env_name = expand_environment(str(config['database_url_env']))
        if env_name not in os.environ:
            raise ValueError(f'database_url_env references unset environment variable {env_name}')
        config['database_url'] = os.environ[env_name]
    elif 'database_url' in config and isinstance(config['database_url'], str):
        config['database_url'] = expand_environment(config['database_url'])

    policy_from_env = os.environ.get('SPATIALFORGE_SCENE_POLICY')
    if policy_from_env:
        policy_path = resolve_path(policy_from_env, path)
    elif config.get('scene_policy_path'):
        policy_path = resolve_path(config['scene_policy_path'], path)
    else:
        candidates = ((Path(config['task_root']) / 'scene-library/policy.json') if config.get('task_root') else None,
                      path.parent / 'scene-library/policy.json',
                      path.parent.parent / 'scene-library/policy.json')
        policy_path = next((candidate.resolve() for candidate in candidates if candidate and candidate.is_file()), None)
    if policy_path is not None:
        if not policy_path.is_file():
            raise ValueError(f'scene policy file does not exist: {policy_path}')
        policy = read_json(policy_path)
        if not isinstance(policy, dict):
            raise ValueError('scene policy must be a JSON object')
        if mode == 'production' and (policy.get('enabled') is not True or policy.get('enforce_realism') is not True):
            raise ValueError('production execution requires an enabled scene policy with enforce_realism=true')
        config['scene_policy_path'] = str(policy_path)
        os.environ['SPATIALFORGE_SCENE_POLICY'] = str(policy_path)
    else:
        config.pop('scene_policy_path', None)
        os.environ.pop('SPATIALFORGE_SCENE_POLICY', None)
    if mode == 'production' and policy_path is None:
        raise ValueError('execution_mode=production requires scene_policy_path pointing to an existing policy.json')

    environment_values = (
        ('gpu_candidates', 'SPATIALFORGE_GPU_CANDIDATES'),
        ('model_url', 'SPATIALFORGE_MODEL_URL'),
        ('model_id', 'SPATIALFORGE_MODEL_ID'),
        ('model_api_key_env', 'SPATIALFORGE_MODEL_API_KEY_ENV'),
    )
    for key, env_name in environment_values:
        value = os.environ.get(env_name, config.get(key))
        if value is not None:
            resolved = expand_environment(str(value))
            config[key] = resolved
            os.environ[env_name] = resolved
    for key in ('models_config', 'task_root'):
        env_name = _PATH_ENVIRONMENT[key]
        if key in config:
            os.environ[env_name] = config[key]
    return config


def load_worker_config(path):
    """Load a desktop worker view derived from the referenced service config."""
    path = Path(path).expanduser().resolve()
    config = read_json(path)
    if not isinstance(config, dict):
        raise ValueError('SpatialForge worker configuration must be a JSON object')
    service_path = config.get('service_config')
    service = read_json(resolve_path(service_path, path)) if service_path else {}
    if service and not isinstance(service, dict):
        raise ValueError('SpatialForge service configuration must be a JSON object')
    server_port = int(service.get('port', 3841))
    server_host = service.get('service_host', '127.0.0.1')
    canonical_url = service.get('service_url') or f'http://{server_host}:{server_port}'
    service_url = os.environ.get('SPATIALFORGE_SERVICE_URL')
    config['url'] = expand_environment(str(config.get('url') or service_url or canonical_url)).rstrip('/')
    if config.get('worker_token_env'):
        env_name = expand_environment(str(config['worker_token_env']))
        config['worker_token'] = os.environ.get(env_name)
        if not config['worker_token']:
            raise ValueError(f'worker_token_env references unset environment variable {env_name}')
    elif service.get('worker_token_env'):
        env_name = expand_environment(str(service['worker_token_env']))
        config['worker_token'] = os.environ.get(env_name)
        if not config['worker_token']:
            raise ValueError(f'worker_token_env references unset environment variable {env_name}')
    else:
        config['worker_token'] = (service.get('worker_token') or config.get('worker_token') or
                                  os.environ.get('SPATIALFORGE_WORKER_TOKEN'))
    if not config['worker_token']:
        raise ValueError('Configure worker_token in service_config or set SPATIALFORGE_WORKER_TOKEN')
    for key in ('isaac_root', 'isaac_asset_root', 'runs', 'ssh_config'):
        if config.get(key):
            config[key] = str(resolve_path(config[key], path))
    if not config.get('ssh_forward'):
        config['ssh_forward'] = f'{server_port}:127.0.0.1:{server_port}'
    return config
