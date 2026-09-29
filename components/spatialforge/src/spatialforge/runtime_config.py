"""Deployment paths, independent of the old Pic2Sim pipeline configuration."""
import json
import os
from pathlib import Path


class RuntimeConfig:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.data = json.loads(self.path.read_text(encoding='utf8'))
        for model in self.data.get('models', {}).values():
            for key in ('python', 'path'):
                value = Path(os.path.expandvars(model[key])).expanduser()
                # Keep venv interpreter symlinks: resolve() changes sys.prefix.
                model[key] = os.path.abspath(self.path.parent / value)
        self.data['sources'] = {
            name: str((self.path.parent / Path(os.path.expandvars(value)).expanduser()).resolve())
            for name, value in self.data.get('sources', {}).items()
        }

    def model(self, name):
        if name not in self.data.get('models', {}):
            raise ValueError(f'Configure models.{name} in {self.path} before using that tool')
        return self.data['models'][name]


def load_service_config(path):
    path = Path(path).expanduser().resolve()
    config = json.loads(path.read_text(encoding='utf8'))
    for key in ('artifacts', 'harness', 'models_config', 'task_root'):
        if key in config:
            config[key] = str((path.parent / Path(config[key]).expanduser()).resolve())
    for name in ('operator', 'worker'):
        if name + '_token_env' in config:
            config[name + '_token'] = os.environ[config[name + '_token_env']]
        if not config[name + '_token']:
            raise ValueError(f'{name}_token must not be empty')
    if 'database_url_env' in config:
        config['database_url'] = os.environ[config['database_url_env']]
    for key, env in [('models_config', 'SPATIALFORGE_MODELS_CONFIG'),
                     ('task_root', 'SPATIALFORGE_TASK_ROOT'),
                     ('gpu_candidates', 'SPATIALFORGE_GPU_CANDIDATES'),
                     ('model_url', 'SPATIALFORGE_MODEL_URL'),
                     ('model_id', 'SPATIALFORGE_MODEL_ID'),
                     ('model_api_key_env', 'SPATIALFORGE_MODEL_API_KEY_ENV')]:
        if key in config:
            os.environ[env] = str(config[key])
    return config
