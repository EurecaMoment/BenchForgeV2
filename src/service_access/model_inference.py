"""Send annotation requests to the configured OpenAI endpoint."""
import json
import os
from urllib.parse import urlsplit
import urllib.request

from service_access import configuration as provider_config


def annotation(args, config):
    config = provider_config.selected_model(config, 'annotation')
    if not config.get('url'):
        raise ValueError('Configure the annotation model under providers.DSpark4A100')
    base_url = provider_config.llm_base_url(config['url'])
    headers = {'Content-Type': 'application/json'}
    if token_env := config.get('token_env'):
        token = os.environ.get(token_env)
        if not token:
            raise ValueError(f'Annotation model token_env references unset {token_env}')
        headers['Authorization'] = f'Bearer {token}'
    if args.get('action') == 'models':
        request = urllib.request.Request(base_url + '/models', headers=headers)
    else:
        data = json.dumps({**args.get('payload', {}), 'model': config['model']}).encode('utf8')
        request = urllib.request.Request(base_url + '/chat/completions', data=data, headers=headers)
    local = urlsplit(base_url).hostname in ('localhost', '127.0.0.1', '::1')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
    with opener.open(request, timeout=args.get('timeout_seconds', 300)) as response:
        return {'service_result': json.load(response), 'evidence_kind': 'model_prediction', 'gt_written': False}
