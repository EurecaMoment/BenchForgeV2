"""Small BenchForge client-config resolver for BenchForge HTTP calls."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|%([A-Za-z_][A-Za-z0-9_]*)%")


def environment_value(name, default=None, *, environ=None):
    environ = os.environ if environ is None else environ
    if name in environ:
        return environ[name]
    if name.startswith('BENCHFORGE_'):
        return environ.get('SPATIALFORGE_' + name.removeprefix('BENCHFORGE_'), default)
    if name.startswith('SPATIALFORGE_'):
        return environ.get('BENCHFORGE_' + name.removeprefix('SPATIALFORGE_'), default)
    return default


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _expand_environment(value):
    def replace(match):
        name = next(part for part in match.groups() if part is not None)
        resolved = environment_value(name)
        if resolved is None:
            raise ValueError(f'configuration references unset environment variable {name}')
        return resolved

    return _ENV_REFERENCE.sub(replace, value)


def _service_url(config):
    value = environment_value('BENCHFORGE_SERVICE_URL') or config.get('service_url')
    if value:
        url = _expand_environment(str(value)).rstrip('/')
    else:
        try:
            port = int(config.get('port', 3841))
        except (TypeError, ValueError) as error:
            raise ValueError('port must be an integer') from error
        if not 1 <= port <= 65535:
            raise ValueError('port must be between 1 and 65535')
        host = _expand_environment(str(config.get('service_host', '127.0.0.1')))
        url = f'http://{host}:{port}'
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('service_url must be an absolute HTTP or HTTPS URL')
    return url


def _operator_token(config):
    env_name = config.get('operator_token_env')
    if env_name:
        env_name = _expand_environment(str(env_name))
        token = environment_value(env_name)
        if not token:
            raise ValueError(f'operator_token_env references unset environment variable {env_name}')
        return token
    token = config.get('operator_token') or environment_value('BENCHFORGE_OPERATOR_TOKEN')
    if not token:
        raise ValueError('Configure operator_token or set BENCHFORGE_OPERATOR_TOKEN')
    return token


def _config_path(value, config_path):
    expanded = _expand_environment(str(value))
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def resolve_service_config_file(path):
    """Select a local client projection, with a fallback for older DSH installs."""
    path = Path(_expand_environment(os.fspath(path))).expanduser().resolve()
    if path.is_file():
        return path
    for names in (
        ('benchforge-client.local.json', 'spatialforge.local.json'),
        ('benchforge-server.local.json', 'spatialforge-server.local.json'),
    ):
        if path.name in names:
            folders = [path.parent]
            if path.parent.name == 'generated' and path.parent.parent.name == 'config':
                folders.append(path.parent.parent)
            elif path.parent.name == 'config':
                folders.append(path.parent / 'generated')
            return next(
                (candidate for folder in folders for name in names
                 if (candidate := folder / name).is_file()),
                path,
            )
    return path


def _execution_policy(config, config_path):
    configured_mode = config.get('execution_mode')
    environment_mode = environment_value('BENCHFORGE_EXECUTION_MODE')
    if configured_mode is not None and environment_mode is not None and configured_mode != environment_mode:
        raise ValueError('BENCHFORGE_EXECUTION_MODE conflicts with configured execution_mode')
    mode = configured_mode if configured_mode is not None else environment_mode or 'production'
    if mode not in ('production', 'exploration'):
        raise ValueError('execution_mode must be production or exploration')
    policy = environment_value('BENCHFORGE_SCENE_POLICY') or config.get('scene_policy_path')
    if not policy:
        task_root = config.get('task_root')
        candidates = []
        if task_root:
            candidates.append(_config_path(task_root, config_path) / 'scene-library' / 'policy.json')
        candidates.extend((config_path.parent / 'scene-library' / 'policy.json',
                           config_path.parent.parent / 'scene-library' / 'policy.json'))
        policy = next((candidate for candidate in candidates if candidate.is_file()), None)
    elif isinstance(policy, str):
        policy = _config_path(policy, config_path)
    if policy is not None:
        policy = Path(policy).expanduser().resolve()
        if not policy.is_file():
            raise ValueError(f'scene policy file does not exist: {policy}')
        policy_value = json.loads(policy.read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(policy_value, dict):
            raise ValueError('scene policy must be a JSON object')
        if mode == 'production' and (policy_value.get('enabled') is not True or
                                     policy_value.get('enforce_realism') is not True):
            raise ValueError('production execution requires an enabled scene policy with enforce_realism=true')
    if mode == 'production' and policy is None:
        raise ValueError('execution_mode=production requires scene_policy_path pointing to an existing policy.json')
    return mode, str(policy) if policy is not None else None


def load_service_client_config(path):
    """Return the service URL and operator token from a local or legacy config."""
    config_path = resolve_service_config_file(path)
    config = json.loads(config_path.read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(config, dict):
        raise ValueError('BenchForge service configuration must be a JSON object')
    if config.get('service_config'):
        base_path = resolve_service_config_file(_config_path(config['service_config'], config_path))
        base = json.loads(base_path.read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(base, dict):
            raise ValueError('Referenced BenchForge service configuration must be a JSON object')
        overrides = {key: value for key, value in config.items() if key != 'service_config'}
        for field in ('port', 'service_url', 'execution_mode', 'scene_policy_path'):
            if field in overrides and field in base and overrides[field] != base[field]:
                raise ValueError(f'{field} in {config_path.name} conflicts with referenced service configuration')
        config = {**base, **overrides}
        config_path = base_path
    mode, policy_path = _execution_policy(config, config_path)
    return {'service_url': _service_url(config), 'operator_token': _operator_token(config),
            'execution_mode': mode, 'scene_policy_path': policy_path}
