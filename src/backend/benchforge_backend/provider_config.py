"""Resolve the provider settings used by the DSH, inference and capture clients."""

import re
from ipaddress import IPv6Address
from urllib.parse import urlsplit


GATEWAY_PROVIDERS = {
    'diffusion': 'FastFLUX2Klein',
    'sam3': 'FastSAM3',
    'depth_anything': 'FastDA3',
    'sam3d': 'FastTrellis2',
}
PROVIDER_TOOLS = {
    'diffusion': 'model_diffusion', 'sam3': 'model_sam3',
    'depth_anything': 'model_depth_anything', 'sam3d': 'model_trellis',
}
LLM_PROVIDER = 'DSpark4A100'
ISAAC_PROVIDER = 'IssacSim4A100'
INFERENCE_TOKEN_ENV = 'BENCHFORGE_INFERENCE_API_KEY'
MODEL_FIELDS = {
    'url', 'model', 'token_env', 'name', 'api', 'context_window', 'max_tokens',
    'input', 'reasoning_efforts', 'reasoning_effort', 'compat', 'retries',
}
INFERENCE_FIELDS = {
    'url', 'availability_url', 'token_env', 'health_timeout_seconds', 'http_timeout_seconds',
}
PROVIDER_CONTROL_FIELDS = {'provider', 'model_path', 'source_root', 'config_path', 'checkpoint'}


def selected_model(config, role):
    if 'providers' in config:
        spec = config['providers'].get(LLM_PROVIDER, {})
        return spec.get('roles', {}).get(role, spec)
    name = config.get('model_roles', {}).get(role)
    if not name:
        return {}
    spec = config.get('models', {}).get(name)
    if not isinstance(spec, dict):
        raise ValueError(f'model_roles.{role} references an unknown model: {name}')
    return spec


def llm_base_url(url):
    return url.rstrip('/').removesuffix('/chat/completions')


def inference_config(config):
    if 'providers' not in config:
        return config.get('model_services', {})
    providers = config['providers']
    tools = {
        tool: {**providers[provider], 'provider': provider}
        for tool, provider in GATEWAY_PROVIDERS.items() if provider in providers
    }
    return {**config.get('inference', {}), 'tools': tools, 'provider_registry': True}


def request_defaults(config, tool):
    return config.get('tools', {}).get(tool, {}).get('request_defaults', {})


def gateway_request(config, tool, request, *, production=False):
    if config.get('provider_registry') and tool == 'trellis':
        tool = 'sam3d'
    spec = config.get('tools', {}).get(tool)
    if config.get('provider_registry') and spec is None:
        raise ValueError(f'Inference tool {tool} has no provider in config/benchforge.local.json')
    spec = spec or {}
    value = {**request_defaults(config, tool), **(request or {})}
    if config.get('provider_registry'):
        if production and tool == 'sam3d':
            value.pop('provider', None)
        if PROVIDER_CONTROL_FIELDS.intersection(value):
            raise ValueError(f'Provider and model paths for {tool} are selected by the inference gateway')
    if spec.get('provider') == 'FastTrellis2':
        value['provider'] = 'trellis2'
    return spec.get('gateway_tool', tool), value


def isaac_config(config):
    if 'providers' in config:
        return config['providers'].get(ISAAC_PROVIDER, {})
    return config.get('isaac', {})


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
    inference = config.get('inference', {})
    if not isinstance(providers, dict) or not isinstance(inference, dict):
        raise ValueError('providers and inference must be JSON objects')
    known = {LLM_PROVIDER, ISAAC_PROVIDER, *GATEWAY_PROVIDERS.values()}
    if unknown := providers.keys() - known:
        raise ValueError(f'Unknown providers: {", ".join(sorted(unknown))}')
    for name, spec in providers.items():
        if not isinstance(spec, dict):
            raise ValueError(f'providers.{name} must be a JSON object')
        if name in GATEWAY_PROVIDERS.values():
            if 'gateway_tool' in spec and (not isinstance(spec['gateway_tool'], str)
                    or not re.fullmatch(r'[a-zA-Z0-9_-]+', spec['gateway_tool'])):
                raise ValueError(f'providers.{name}.gateway_tool must be a tool ID')
            if not isinstance(spec.get('request_defaults', {}), dict):
                raise ValueError(f'providers.{name}.request_defaults must be a JSON object')
            _validate_fields(spec, f'providers.{name}', {'gateway_tool', 'request_defaults'})
            if PROVIDER_CONTROL_FIELDS.intersection(spec.get('request_defaults', {})):
                raise ValueError(f'providers.{name}.request_defaults cannot select another model or model path')
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
        model = spec.get('model')
        if spec.get('url') is not None or model is not None:
            _configured_url(spec.get('url'), field + '.url')
            if not isinstance(model, str) or not model.strip() or model.upper().startswith('YOUR_'):
                raise ValueError(f'{field}.model must be the deployed model ID')
            if 'input' in spec and (not isinstance(spec['input'], list)
                    or any(item not in ('text', 'image') for item in spec['input'])):
                raise ValueError(f'{field}.input must be a list of text or image modalities')
    _validate_token(inference, 'inference')
    _validate_fields(inference, 'inference', INFERENCE_FIELDS)
    for key in ('url', 'availability_url'):
        if inference.get(key) is not None:
            _configured_url(inference[key], 'inference.' + key)
    for key in ('health_timeout_seconds', 'http_timeout_seconds'):
        if key in inference and (type(inference[key]) not in (int, float) or not 0 < inference[key] < float('inf')):
            raise ValueError(f'inference.{key} must be a positive number')
    isaac = isaac_config(config)
    _validate_fields(isaac, f'providers.{ISAAC_PROVIDER}', {'grpc', 'capture_timeout_seconds'})
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
