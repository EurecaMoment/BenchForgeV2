"""Resolve the provider settings used by DSH and the production service."""

import re
from ipaddress import IPv6Address
from urllib.parse import urlsplit


MODEL_PROVIDERS = {
    'diffusion': 'FastFLUX2Klein',
    'sam3': 'FastSAM3',
    'depth': 'FastDA3',
    'trellis': 'FastTrellis2',
}
LLM_PROVIDER = 'DSpark4A100'
ISAAC_PROVIDER = 'IssacSim4A100'
MODEL_FIELDS = {
    'url', 'model', 'token_env', 'name', 'api', 'context_window', 'max_tokens',
    'input', 'reasoning_efforts', 'reasoning_effort', 'compat', 'retries',
}
HTTP_FIELDS = {'url', 'model', 'token_env', 'timeout_seconds', 'request_defaults'}


def selected_model(config, role):
    spec = dict(config.get('providers', {}).get(LLM_PROVIDER, {}))
    roles = spec.pop('roles', {})
    return {**spec, **roles.get(role, {})}


def llm_base_url(url):
    return url.rstrip('/').removesuffix('/chat/completions')


def model_settings(config, tool):
    return config.get('providers', {}).get(MODEL_PROVIDERS[tool], {})


def isaac_config(config):
    return config.get('providers', {}).get(ISAAC_PROVIDER, {})


def isaac_endpoint(grpc):
    host = grpc.get('host')
    if (not isinstance(host, str) or not host or host.upper().startswith('YOUR_')
            or any(char.isspace() for char in host) or '/' in host):
        raise ValueError(f'Configure providers.{ISAAC_PROVIDER}.grpc.host in config/benchforge.local.json')
    port = grpc.get('port', 50051)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('The Isaac gRPC port must be an integer between 1 and 65535')
    if ':' in host:
        host = host.strip('[]')
        try:
            IPv6Address(host)
        except ValueError:
            raise ValueError('The Isaac gRPC host must not include the port') from None
        return f'[{host}]:{port}'
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', host):
        raise ValueError('The Isaac gRPC host must be a host name or IP address')
    return f'{host}:{port}'


def capture_timeout(isaac):
    return isaac.get('capture_timeout_seconds', 1800)


def _configured_url(value, field):
    try:
        parts = urlsplit(value) if isinstance(value, str) else None
        if (parts and parts.scheme in ('http', 'https') and parts.hostname
                and not parts.query and not parts.fragment and parts.username is None
                and not any(char.isspace() for char in value) and parts.port != 0):
            return
    except ValueError:
        pass
    raise ValueError(f'{field} must be an absolute HTTP or HTTPS base URL without credentials')


def validate_providers(config):
    providers = config['providers']
    if not isinstance(providers, dict):
        raise ValueError('providers must be a JSON object')
    known = {LLM_PROVIDER, ISAAC_PROVIDER, *MODEL_PROVIDERS.values()}
    if unknown := providers.keys() - known:
        raise ValueError(f'Unknown providers: {", ".join(sorted(unknown))}')
    for name, spec in providers.items():
        if not isinstance(spec, dict):
            raise ValueError(f'providers.{name} must be a JSON object')
        if name in MODEL_PROVIDERS.values():
            field = f'providers.{name}'
            _validate_fields(spec, field, HTTP_FIELDS)
            _validate_token(spec, field)
            if spec.get('url') is not None:
                _configured_url(spec['url'], field + '.url')
                if not isinstance(spec.get('model'), str) or not spec['model'].strip():
                    raise ValueError(f'{field}.model must be the deployed model ID')
            if not isinstance(spec.get('request_defaults', {}), dict):
                raise ValueError(f'{field}.request_defaults must be a JSON object')
            timeout = spec.get('timeout_seconds', 180)
            if (type(timeout) not in (int, float) or not 0 < timeout < float('inf')
                    or (name == 'FastTrellis2' and not .01 <= timeout <= 3600)):
                raise ValueError(f'{field}.timeout_seconds is outside the supported range')
    llm = providers.get(LLM_PROVIDER, {})
    roles = llm.get('roles', {})
    if not isinstance(roles, dict) or roles.keys() - {'dsh', 'scene', 'annotation'}:
        raise ValueError(f'providers.{LLM_PROVIDER}.roles must contain DSH, scene or annotation settings')
    for role, spec in (('', llm), *roles.items()):
        field = f'providers.{LLM_PROVIDER}' + (f'.roles.{role}' if role else '')
        if not isinstance(spec, dict):
            raise ValueError(f'{field} must be a JSON object')
        _validate_token(spec, field)
        _validate_fields(spec, field, MODEL_FIELDS if role else MODEL_FIELDS | {'roles'})
        spec = selected_model(config, role) if role else spec
        model = spec.get('model')
        if spec.get('url') is not None or model is not None:
            _configured_url(spec.get('url'), field + '.url')
            if not isinstance(model, str) or not model.strip() or model.upper().startswith('YOUR_'):
                raise ValueError(f'{field}.model must be the deployed model ID')
            if 'input' in spec and (not isinstance(spec['input'], list)
                    or any(item not in ('text', 'image') for item in spec['input'])):
                raise ValueError(f'{field}.input must be a list of text or image modalities')
    isaac = isaac_config(config)
    field = f'providers.{ISAAC_PROVIDER}'
    _validate_fields(isaac, field, {'mode', 'grpc', 'local', 'capture_timeout_seconds'})
    mode = isaac.get('mode', 'grpc')
    if mode not in ('grpc', 'local'):
        raise ValueError(f'{field}.mode must be grpc or local')
    local = isaac.get('local', {})
    if not isinstance(local, dict):
        raise ValueError(f'{field}.local must be a JSON object')
    _validate_fields(local, field + '.local', {'python', 'asset_root', 'idle_seconds'})
    if mode == 'local':
        for key in ('python', 'asset_root'):
            if not isinstance(local.get(key), str) or not local[key].strip():
                raise ValueError(f'{field}.local.{key} is required for local mode')
    if type(local.get('idle_seconds', 300)) is not int or local.get('idle_seconds', 300) <= 0:
        raise ValueError(f'{field}.local.idle_seconds must be a positive integer')
    grpc = isaac.get('grpc', {})
    if not isinstance(grpc, dict):
        raise ValueError(f'providers.{ISAAC_PROVIDER}.grpc must be a JSON object')
    _validate_fields(grpc, f'providers.{ISAAC_PROVIDER}.grpc', {'host', 'port', 'timeout_seconds'})
    if grpc.get('host') is not None:
        isaac_endpoint(grpc)
    if 'timeout_seconds' in grpc and (type(grpc['timeout_seconds']) is not int or grpc['timeout_seconds'] <= 0):
        raise ValueError(f'providers.{ISAAC_PROVIDER}.grpc.timeout_seconds must be a positive integer')
    timeout = capture_timeout(isaac)
    if type(timeout) not in (int, float) or not 0 < timeout < float('inf'):
        raise ValueError(f'providers.{ISAAC_PROVIDER}.capture_timeout_seconds must be a positive number')


def _validate_fields(config, name, fields):
    if unknown := config.keys() - fields:
        raise ValueError(f'{name} has unknown settings: {", ".join(sorted(unknown))}')


def _validate_token(config, name):
    token = config.get('token_env')
    if token is not None and (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', token)):
        raise ValueError(f'{name}.token_env must name an environment variable')
    if 'token' in config or 'api_key' in config:
        raise ValueError(f'Configure {name}.token_env for credentials')
