"""Authenticated HTTP client for BenchForge pipeline operations."""

from ..service_config import load_service_client_config
from ..service_http import post_service_json


MODE_ROUTES = {'/start', '/capture', '/refine', '/extend', '/retry', '/dataset'}


def _bind_execution_mode(route, arguments, configured_mode):
    """Make the server's configured execution mode explicit on each request."""
    if route not in MODE_ROUTES:
        return arguments

    def bind(value):
        supplied = value.get('execution_mode')
        if supplied is not None and supplied != configured_mode:
            raise ValueError(
                f'execution_mode {supplied} conflicts with configured {configured_mode} mode'
            )
        return {**value, 'execution_mode': configured_mode}

    if route == '/start':
        intents = arguments.get('intents')
        if not isinstance(intents, list):
            return bind(arguments)
        return {**arguments, 'intents': [bind(intent) for intent in intents]}

    request = bind(arguments)
    if isinstance(request.get('intent'), dict):
        request['intent'] = bind(request['intent'])
    return request


def service_call(route, arguments, config_path):
    config = load_service_client_config(config_path)
    arguments = _bind_execution_mode(route, arguments, config['execution_mode'])
    return post_service_json(
        config['service_url'], route, arguments, token=config['operator_token'], timeout=60,
    )
