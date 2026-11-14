"""Project the selected OpenAI scene model into the production runtime."""

import os

from .provider_config import selected_model
from .runtime_config import read_json


def apply_model_environment(config):
    reference = config.get('models_config')
    if not reference:
        return
    spec = selected_model(read_json(reference), 'scene')
    for source, target, variable in (
        ('url', 'model_url', 'BENCHFORGE_MODEL_URL'),
        ('model', 'model_id', 'BENCHFORGE_MODEL_ID'),
        ('token_env', 'model_api_key_env', 'BENCHFORGE_MODEL_API_KEY_ENV'),
    ):
        if spec.get(source):
            config[target] = spec[source]
            os.environ[variable] = spec[source]
        else:
            config.pop(target, None)
            os.environ.pop(variable, None)
