"""Common DSH preset composition and model settings."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml

DSH_ROOT = Path(__file__).resolve().parents[1]
SOURCE = DSH_ROOT.parent
if (SOURCE / 'benchmark_workflows/__init__.py').is_file():
    sys.path.insert(0, str(SOURCE))
from service_access import configuration as provider_config


class JavaScript(str):
    pass


class Loader(yaml.SafeLoader):
    pass


class Dumper(yaml.SafeDumper):
    pass


Loader.add_constructor('tag:yaml.org,2002:js', lambda loader,node:JavaScript(loader.construct_scalar(node)))
Dumper.add_representer(JavaScript, lambda dumper,value:dumper.represent_scalar('tag:yaml.org,2002:js',str(value)))


BENCHFORGE_ID = 'benchforge'
PRESET_ALIASES = {'benchforge-ui': BENCHFORGE_ID}
SCENE_PLUGIN_ID = 'benchforge-scene-tools'
WORKBENCH_PLUGIN_ID = 'benchforge-workbench-ui'
CAPTURE_PLUGIN_ID = 'benchforge-capture'
SESSION_OPERATIONS_PLUGIN_ID = 'benchforge-session-operations'
PRESETS = {
    BENCHFORGE_ID: {
        'name': 'BenchForge', 'order': -2,
        'description': 'Scene and data production with an expandable workbench in the same conversation.',
    },
}
MODEL_TOOLS = ['model_infer']
DEFAULT_SERVICE_CONFIG = Path('config/generated/benchforge-client.local.json')
def set_identity(row, preset_id):
    """Keep preset metadata in one place, independent of tool composition."""
    row['id'] = 'preset-' + preset_id
    row['config'].update(id=preset_id, **PRESETS[preset_id])


def config_reference(path, package_imports=False):
    """Bundle defaults stay relative; deployment overlays use absolute paths."""
    path = Path(path)
    return path.as_posix() if package_imports else str(path.resolve())


def default_service_config(root=Path('.')):
    return root / DEFAULT_SERVICE_CONFIG


def load_sources(dsh_root=None, node=None, resolve_from=None):
    """Resolve official preset assets through the package's supported exports."""
    if resolve_from is None:
        if dsh_root is None:
            resolve_from=Path(__file__).resolve().parents[1]/'package.json'
        else:
            # Compatibility for source-based launchers: this is only a Node lookup
            # location, never the source path of an imported implementation/asset.
            root=Path(dsh_root).resolve()
            cli_manifest=root/'apps/cli/package.json'
            resolve_from=cli_manifest if cli_manifest.exists() else root/'package.json'
    script = """const {createRequire} = require('node:module');
const {readFileSync} = require('node:fs');
const from = createRequire(process.argv[1]);
const asset = from.resolve('@deepseek-ai/dsh-web-app/presets/standard.patch.yml');
process.stdout.write(readFileSync(asset, 'utf8'));"""
    command = [node or os.environ.get('BENCHFORGE_DSH_NODE', 'node'), '-e', script,
               str(Path(resolve_from).resolve())]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Cannot resolve the official DSH Standard preset. '
                           'Supply the DSH Node interpreter and package lookup directory.\n'
                           + result.stderr.strip())
    return yaml.load(result.stdout, Loader=Loader)


def add_source_arguments(parser):
    parser.add_argument('--dsh-root',type=Path,help='Compatibility lookup root for an existing DSH source installation')
    parser.add_argument('--dsh-resolve-from',type=Path,help='Package manifest used as the Node public-package lookup location')
    parser.add_argument('--node',help='DSH-compatible Node executable (or BENCHFORGE_DSH_NODE)')

def model_patches(config_path):
    """Project the DSH model role from the operator's shared registry."""
    path = Path(config_path)
    if not path.is_file():
        return []
    registry = json.loads(path.read_text(encoding='utf-8'))
    model = provider_config.selected_model(registry, 'dsh')
    if not model.get('model') or str(model['model']).startswith('YOUR_'):
        return []
    if not model.get('url'):
        raise ValueError('Configure the DSH model URL in config/benchforge.local.json')
    descriptor = {'id': model['model'], 'name': model.get('name', model['model'])}
    for source, target in (('context_window', 'contextWindow'), ('max_tokens', 'maxTokens'),
                           ('input', 'input'), ('reasoning_efforts', 'reasoningEfforts')):
        if source in model:
            descriptor[target] = model[source]
    provider = {'displayName': 'DSpark4A100' if 'providers' in registry else 'BenchForge models',
                'api': model.get('api', 'openai-completions'),
                'baseURL': provider_config.llm_base_url(model['url']), 'models': [descriptor]}
    if model.get('token_env'):
        provider['apiKeyEnv'] = model['token_env']
    if model.get('compat'):
        provider['compat'] = model['compat']
    if 'retries' in model:
        provider['retryPolicy'] = {'mode': 'normal', 'maxRetries': model['retries']}
    selection = {'provider': 'benchforge-models', 'model': model['model']}
    if model.get('reasoning_effort'):
        selection['reasoningEffort'] = model['reasoning_effort']
    return [{'id': 'llm-pi-ai', 'config': {'providers': {'benchforge-models': provider}}},
            {'id': 'agent-default-model', 'config': selection}]


def model_tools(config_path, *, portable=False):
    if portable:
        return MODEL_TOOLS
    path = Path(config_path) if config_path else None
    if not path or not path.is_file():
        return []
    settings = json.loads(path.read_text(encoding='utf-8'))
    annotation = provider_config.selected_model(settings, 'annotation')
    return MODEL_TOOLS if annotation.get('url') and annotation.get('model') else []


def preset_id(row):
    config = row.get('config')
    return config.get('id') if isinstance(config, dict) and isinstance(config.get('plugins'), list) else None


def refresh_preset_identity(profile):
    """Update saved profile declarations before DSH loads their plugins."""
    previous_addons = {'benchforge-tool-executor', 'persistent-shell', 'tool-presentation'}
    for patch in profile:
        if patch.get('id') == 'agent-preset-registry':
            config = patch.get('config', {})
            for key in ('default', 'selectedDefault'):
                if config.get(key) in PRESET_ALIASES:
                    config[key] = PRESET_ALIASES[config[key]]
        if 'insert' not in patch:
            continue
        patch['insert'] = [row for row in patch['insert'] if row.get('id') != 'benchforge-preset-aliases']
        for row in patch['insert']:
            identity = preset_id(row)
            if identity in PRESET_ALIASES:
                set_identity(row, PRESET_ALIASES[identity])
            if preset_id(row) not in PRESETS:
                continue
            plugins = row['config']['plugins']
            plugins[:] = [plugin for plugin in plugins if plugin.get('id') not in previous_addons]


def refresh_model_patches(preset_path, config_path, *, refresh_host=None):
    """Refresh model selection and generated BenchForge plugin options."""
    preset_path = Path(preset_path)
    if not preset_path.is_file():
        return
    profile = yaml.load(preset_path.read_text(encoding='utf-8'), Loader=Loader) or []
    previous = deepcopy(profile)
    refresh_preset_identity(profile)
    if refresh_host is not None:
        refresh_host(profile)
    refresh_host_models(profile, model_patches(config_path))
    enabled = model_tools(config_path)
    for patch in profile:
        for row in patch.get('insert', []):
            if preset_id(row) not in PRESETS:
                continue
            for plugin in row['config']['plugins']:
                if plugin.get('id') != 'benchforge-tools':
                    continue
                options = plugin.setdefault('config', {})
                if isinstance(included := options.get('includeTools'), list):
                    options['includeTools'] = [
                        tool for tool in included if not tool.startswith('model_') and tool not in MODEL_TOOLS
                    ] + enabled
                options.setdefault('configPath', str(Path(config_path).resolve()))
    if profile != previous:
        temporary = preset_path.with_suffix(preset_path.suffix + '.tmp')
        temporary.write_text(yaml.dump(profile, Dumper=Dumper, sort_keys=False, allow_unicode=True),
                             encoding='utf-8', newline='\n')
        temporary.replace(preset_path)


def refresh_host_models(profile, patches):
    """Refresh the BenchForge model provider in the host's profile."""
    changed = False
    if not patches:
        for row in profile[:]:
            if (row.get('id') == 'agent-default-model'
                    and row.get('config', {}).get('provider') == 'benchforge-models'):
                profile.remove(row)
                changed = True
                continue
            if row.get('id') == 'llm-pi-ai':
                providers = row.get('config', {}).get('providers', {})
                if 'benchforge-models' in providers:
                    providers.pop('benchforge-models')
                    changed = True
    for patch in patches:
        existing = next((row for row in profile if row.get('id') == patch['id']), None)
        if existing is None:
            profile.append(patch)
            changed = True
        else:
            prior = deepcopy(existing)
            if patch['id'] == 'llm-pi-ai':
                existing.setdefault('config', {}).setdefault('providers', {}).update(
                    patch['config']['providers'])
            else:
                existing['config'] = patch['config']
            changed = changed or prior != existing
    return changed


def compose_standard(standard):
    return deepcopy(next(row for patch in standard for row in patch.get('insert', [])
                         if row['id'] == 'preset-standard'))
