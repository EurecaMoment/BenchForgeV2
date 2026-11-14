"""Common DSH preset composition and model settings."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from urllib.request import url2pathname
import yaml

DSH_ROOT = Path(__file__).resolve().parents[1]
SOURCE = DSH_ROOT.parent
if (SOURCE / 'benchforge_core/__init__.py').is_file():
    sys.path.insert(0, str(SOURCE))
from benchforge_core.provider_config import provider_config


class JavaScript(str):
    pass


class Loader(yaml.SafeLoader):
    pass


class Dumper(yaml.SafeDumper):
    pass


Loader.add_constructor('tag:yaml.org,2002:js', lambda loader,node:JavaScript(loader.construct_scalar(node)))
Dumper.add_representer(JavaScript, lambda dumper,value:dumper.represent_scalar('tag:yaml.org,2002:js',str(value)))


RETIRED_SCENE_TOOL = 'benchforge_dataset'
BENCHFORGE_ID = 'benchforge'
WORKBENCH_PRESET_ID = 'benchforge-ui'
PRESET_ALIASES = {'benchforgev2': BENCHFORGE_ID, 'spatialforge-standard-ptc': WORKBENCH_PRESET_ID}
PRESET_ALIASES_PLUGIN_ID = 'benchforge-preset-aliases'
SCENE_PLUGIN_ID = 'benchforge-scene-tools'
LEGACY_SCENE_PLUGIN_ID = 'spatialforge-tools'
LEGACY_WORKBENCH_PLUGIN_ID = 'spatialforge-evaluation-ui'
WORKBENCH_PLUGIN_ID = 'benchforge-workbench-ui'
CAPTURE_PLUGIN_ID = 'benchforge-capture'
SESSION_OPERATIONS_PLUGIN_ID = 'benchforge-session-operations'
SCENE_TOOL_NAMES = {'catalog', 'status', 'sam3', 'sam3d', 'evidence', 'collaboration'}
PRESETS = {
    BENCHFORGE_ID: {
        'name': 'BenchForge', 'order': -2,
        'description': 'Scene and data production in the standard conversation interface.',
    },
    WORKBENCH_PRESET_ID: {
        'name': 'BenchForge_UI', 'order': -1,
        'description': 'Scene and data production with the visual workbench.',
    },
}
MODEL_TOOLS = ['llm_local']
DEFAULT_SERVICE_CONFIG = Path('config/generated/benchforge-client.local.json')
LEGACY_SERVICE_CONFIG = Path('config/benchforge-client.local.json')
LEGACY_SERVICE_CONFIGS = (
    LEGACY_SERVICE_CONFIG, Path('config/generated/spatialforge.local.json'), Path('config/spatialforge.local.json'),
)
SERVER_SERVICE_CONFIGS = (
    Path('config/generated/benchforge-server.local.json'),
    Path('config/generated/spatialforge-server.local.json'), Path('config/spatialforge-server.local.json'),
)
PLUGIN_MOVES = {
    Path('presets/tools.mjs'): 'tools/core.mjs',
    Path('presets/persistent-shell.mjs'): 'tools/persistent-shell.mjs',
    Path('presets/tool_executor.mjs'): 'tools/tool_executor.mjs',
    Path('presets/subagent_policy.mjs'): 'tools/subagent_policy.mjs',
    Path('presets/preset_aliases.mjs'): 'host/preset_aliases.mjs',
    Path('plugin/tools.mjs'): 'tools/scene/tools.mjs',
    Path('ui/stage_products.js'): 'ui/index.js',
    Path('ui/production.js'): 'ui/index.js',
}
SOURCE_RELOCATIONS = {
    **{Path('src/dsh') / old: new for old, new in PLUGIN_MOVES.items()},
    **{Path('integrations/dsh') / old.name: new for old, new in PLUGIN_MOVES.items()
       if old.parent.name == 'presets'},
    **{Path('integrations') / package / old: new for package in ('benchforge', 'spatialforge')
       for old, new in {**PLUGIN_MOVES, Path('ui/index.js'): 'ui/index.js'}.items()
       if old.parent.name in ('plugin', 'ui')},
}


def set_identity(row, preset_id):
    """Keep preset metadata in one place, independent of tool composition."""
    row['id'] = 'preset-' + preset_id
    row['config'].update(id=preset_id, **PRESETS[preset_id])


def preset_alias_entry(*, package_imports=False):
    name = '@eurecamoment/benchforge-dsh/preset-aliases' if package_imports else (
        DSH_ROOT / 'host/preset_aliases.mjs').as_uri()
    return {'id': PRESET_ALIASES_PLUGIN_ID, 'name': name, 'config': {'aliases': PRESET_ALIASES.copy()}}


def config_reference(path, package_imports=False):
    """Bundle defaults stay relative; deployment overlays use absolute paths."""
    path = Path(path)
    return path.as_posix() if package_imports else str(path.resolve())


def default_service_config(root=Path('.')):
    current = root / DEFAULT_SERVICE_CONFIG
    return next((path for path in (current, *(root / path for path in LEGACY_SERVICE_CONFIGS))
                 if path.is_file()), current)


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
    names=['standard','ptc','minimal','cordis']
    script="""const {createRequire}=require('node:module');
const {readFileSync}=require('node:fs');
const requireFrom=createRequire(process.argv[1]);
const names=JSON.parse(process.argv[2]);
console.log(JSON.stringify(Object.fromEntries(names.map(name=>
  [name,readFileSync(requireFrom.resolve('@deepseek-ai/dsh-web-app/presets/'+name+'.patch.yml'),'utf8')]))));"""
    command=[node or os.environ.get('BENCHFORGE_DSH_NODE','node'),'-e',script,
             str(Path(resolve_from).resolve()),json.dumps(names)]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Cannot resolve official @deepseek-ai/dsh-web-app preset exports. '
                           'Use a current DSH Node interpreter (--node) and installed package '
                           'lookup location (--dsh-resolve-from).\n'+result.stderr.strip())
    assets=json.loads(result.stdout)
    # Node also handles Windows long package-manager paths that pathlib cannot open.
    return {name:yaml.load(assets[name],Loader=Loader)
            for name in names}


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


def is_retired_preset(row):
    # The first-generation preset shared the new public id but only loaded the Python tools.
    return preset_id(row) == BENCHFORGE_ID and not any(
        plugin.get('id') in {SCENE_PLUGIN_ID, LEGACY_SCENE_PLUGIN_ID}
        for plugin in row['config']['plugins'])


def remove_retired_preset(profile):
    """Drop the old preset declaration from the config without touching sessions."""
    changed = False
    for patch in profile:
        if 'insert' not in patch:
            continue
        prior = patch['insert']
        current = [row for row in prior if not is_retired_preset(row)]
        if len(current) != len(prior):
            patch['insert'] = current
            changed = True
    return changed


def _rename_scene_tokens(value):
    def rename(match):
        suffix = match.group(1)
        return ('benchforge_scene_' if suffix in SCENE_TOOL_NAMES else 'benchforge_') + suffix

    return re.sub(r'\bspatialforge_([a-z0-9_]+)\b', rename, value)


def _refresh_preset_plugins(plugins):
    for row in plugins:
        config = row.get('config')
        name = row.get('name')
        if row.get('id') == LEGACY_SCENE_PLUGIN_ID:
            row['id'] = SCENE_PLUGIN_ID
        if isinstance(name, str):
            for old, new in (
                ('@eurecamoment/benchforge-dsh/spatialforge-tools', '@eurecamoment/benchforge-dsh/benchforge-scene-tools'),
                ('@eurecamoment/benchforge-dsh/spatialforge-ui', '@eurecamoment/benchforge-dsh/benchforge-ui'),
            ):
                if name == old:
                    row['name'] = new
        if isinstance(config, list):
            _refresh_preset_plugins(config)
        elif isinstance(config, dict):
            for key in (('prefix', 'suffix') if row.get('id') == 'persona' else ('persona',)
                        if name == '@deepseek-ai/dsh-tool-subagent' else ()):
                if isinstance(config.get(key), str):
                    prompt = _rename_scene_tokens(config[key])
                    prompt = re.sub(r'(?<!/)\bBenchForgeV2\b|\bSpatialForge\b', 'BenchForge', prompt)
                    prompt = prompt.replace('BenchForgeV2_UI', 'BenchForge_UI')
                    for package in ('benchforge', 'spatialforge'):
                        for section in ('ui/DESIGN.md', 'ui/plan_request_cli.py', 'task_support'):
                            old = f'integrations/{package}/{section}'
                            prompt = re.sub(r'(?<![\w/\\])' + re.escape(old), 'src/dsh/' + section, prompt)
                    prompt = prompt.replace('src/dsh/ui/plan_request_cli.py',
                                            'src/dsh/host/workbench/plan_request_cli.py')
                    config[key] = re.sub(r'(?<![\w/\\])benchforge/task_support/README\.md',
                                         'task_support/README.md', prompt)
            tool_filter = config.get('toolFilter')
            if isinstance(tool_filter, dict):
                for key in ('allow', 'deny'):
                    if isinstance(tool_filter.get(key), list):
                        tool_filter[key] = [_rename_scene_tokens(value) if isinstance(value, str) else value
                                            for value in tool_filter[key]]


def refresh_source_plugins(profile, root, profile_dir=None):
    """Move local BenchForge plugin references to this checkout's source layout."""
    root = Path(root).resolve()

    def relocated(name):
        if not isinstance(name, str):
            return None
        url = urlsplit(name) if name.startswith('file:') else None
        if (url and url.netloc not in ('', 'localhost')) or (not url and '://' in name):
            return None
        local = Path(url2pathname(url.path) if url else name.replace('\\', '/')).expanduser()
        for directory in (root, profile_dir):
            if directory is None:
                continue
            path = (directory / local).resolve()
            if path.is_relative_to(root):
                destination = SOURCE_RELOCATIONS.get(path.relative_to(root))
                if destination:
                    target = root / 'src/dsh' / destination
                    if url:
                        parts = urlsplit(target.as_uri())
                        return urlunsplit(parts._replace(query=url.query, fragment=url.fragment))
                    return str(target)
        return None

    def refresh(row):
        if not isinstance(row, dict):
            return False
        changed = False
        replacement = relocated(row.get('name'))
        if replacement:
            row['name'] = replacement
            changed = True
        config = row.get('config')
        children = config.get('plugins') if isinstance(config, dict) else config
        for child in row.get('insert', []):
            changed = refresh(child) or changed
        if isinstance(children, list):
            for child in children:
                changed = refresh(child) or changed
        return changed

    changed = False
    for row in profile:
        changed = refresh(row) or changed
    return changed


def refresh_preset_identity(profile, *, root=None, profile_dir=None):
    """Promote earlier profile declarations to their canonical preset and plugin ids."""
    changed = remove_retired_preset(profile)
    declared = set()
    for patch in profile:
        if patch.get('id') == 'agent-preset-registry':
            changed = _refresh_registry_defaults(patch) or changed
        if 'insert' not in patch:
            continue
        rows = []
        for row in patch.get('insert', []):
            previous_id = preset_id(row)
            canonical_id = PRESET_ALIASES.get(previous_id, previous_id)
            if canonical_id in PRESETS:
                if canonical_id in declared:
                    changed = True
                    continue
                declared.add(canonical_id)
                previous = deepcopy(row)
                if canonical_id != previous_id:
                    if row.get('id') == 'preset-' + previous_id:
                        row['id'] = 'preset-' + canonical_id
                    row['config'].update(id=canonical_id, name=PRESETS[canonical_id]['name'])
                _refresh_preset_plugins(row['config']['plugins'])
                changed = row != previous or changed
            elif row.get('id') == WORKBENCH_PLUGIN_ID:
                previous = row.get('name')
                _refresh_preset_plugins([row])
                changed = row.get('name') != previous or changed
            elif row.get('id') == 'agent-preset-registry':
                changed = _refresh_registry_defaults(row) or changed
            rows.append(row)
        patch['insert'] = rows
    root = Path(__file__).resolve().parents[3] if root is None else root
    return refresh_source_plugins(profile, root, profile_dir) or changed


def _refresh_registry_defaults(row):
    changed = False
    options = row.get('config') or {}
    for key in ('default', 'selectedDefault'):
        if isinstance(options.get(key), str) and options[key] in PRESET_ALIASES:
            options[key] = PRESET_ALIASES[options[key]]
            changed = True
    return changed


def remove_retired_tool_filter(plugins):
    changed = False
    for plugin in plugins:
        config = plugin.get('config')
        if isinstance(config, list):
            changed = remove_retired_tool_filter(config) or changed
        elif plugin.get('name') == '@deepseek-ai/dsh-tool-subagent' and isinstance(config, dict):
            tool_filter = config.get('toolFilter') or {}
            deny = tool_filter.get('deny', [])
            retired = {RETIRED_SCENE_TOOL, 'spatialforge_dataset'}
            if retired.intersection(deny):
                remaining = [name for name in deny if name not in retired]
                tool_filter.pop('deny')
                if remaining:
                    tool_filter['deny'] = remaining
                if not tool_filter:
                    config.pop('toolFilter')
                changed = True
    return changed


def refresh_service_paths(profile, config_path):
    root = Path(config_path).resolve().parent.parent
    current = root / DEFAULT_SERVICE_CONFIG
    if not current.is_file():
        return False
    legacy = {(root / path).resolve() for path in LEGACY_SERVICE_CONFIGS}
    servers = {(root / path).resolve() for path in SERVER_SERVICE_CONFIGS}
    current = current.resolve()

    def refresh(row, key, old_paths):
        options = row.get('config')
        value = options.get(key) if isinstance(options, dict) else None
        if isinstance(value, str) and value and (root / Path(value).expanduser()).resolve() in old_paths:
            options[key] = str(current)
            return True
        return False

    changed = False
    for patch in profile:
        for row in patch.get('insert', []):
            if row.get('id') in {WORKBENCH_PLUGIN_ID, LEGACY_WORKBENCH_PLUGIN_ID, CAPTURE_PLUGIN_ID}:
                changed = refresh(row, 'productionConfig', legacy | servers) or changed
            if preset_id(row) not in PRESETS:
                continue
            for plugin in row['config']['plugins']:
                if plugin.get('id') == SCENE_PLUGIN_ID:
                    changed = refresh(plugin, 'serviceConfig', legacy | servers) or changed
                if plugin.get('id') == LEGACY_WORKBENCH_PLUGIN_ID:
                    changed = refresh(plugin, 'productionConfig', legacy | servers) or changed
    return changed


def refresh_model_patches(preset_path, config_path, *, refresh_host=None):
    """Refresh generated deployment settings and retire old preset entries."""
    preset_path = Path(preset_path)
    if not preset_path.is_file():
        return
    patches = model_patches(config_path)
    profile = yaml.load(preset_path.read_text(encoding='utf-8'), Loader=Loader) or []
    changed = refresh_preset_identity(profile, profile_dir=preset_path.resolve().parent)
    if refresh_host is not None:
        changed = refresh_host(profile) or changed
    changed = refresh_service_paths(profile, config_path) or changed
    changed = refresh_host_models(profile, patches) or changed
    enabled = model_tools(config_path)
    inserts = [row for patch in profile for row in patch.get('insert', [])]
    if any(preset_id(row) in PRESETS for row in inserts) and not any(
            row.get('id') == PRESET_ALIASES_PLUGIN_ID for row in inserts):
        profile.append({'insert': [preset_alias_entry()]})
        changed = True
    for patch in profile:
        for row in patch.get('insert', []):
            if preset_id(row) in PRESETS:
                changed = remove_retired_tool_filter(row['config']['plugins']) or changed
                for plugin in row['config']['plugins']:
                    if plugin.get('id') not in {'spatial-learning-tools', 'benchforge-tools'}:
                        continue
                    options = plugin.setdefault('config', {})
                    before = deepcopy(options)
                    included = options.get('includeTools')
                    if isinstance(included, list):
                        options['includeTools'] = [tool for tool in included if not tool.startswith('model_') and tool not in MODEL_TOOLS]
                        options['includeTools'].extend(enabled)
                    options.setdefault('configPath', str(Path(config_path).resolve()))
                    changed = before != options or changed
    if changed:
        temporary = preset_path.with_suffix(preset_path.suffix + '.tmp')
        temporary.write_text('# Generated settings read config/benchforge.local.json.\n'
                             + yaml.dump(profile, Dumper=Dumper, sort_keys=False, allow_unicode=True),
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


def compose_standard(sources, *, package_imports=False):
    def preset(name):
        return next(row for patch in sources[name] for row in patch.get('insert',[]) if row['id']=='preset-'+name)
    result=deepcopy(preset('standard'))
    plugins=result['config']['plugins']
    executor = '@eurecamoment/benchforge-dsh/tool-executor' if package_imports else (
        DSH_ROOT / 'tools/tool_executor.mjs').as_uri()
    plugins.append({'id': 'benchforge-tool-executor', 'name': executor})
    persistent=deepcopy(next(p for p in preset('minimal')['config']['plugins'] if p['id']=='persistent-shell'))
    for row in persistent['config']:
        if row['id'] in ('persistent-bash','persistent-pwsh'):
            shell='bash' if row['id']=='persistent-bash' else 'pwsh'
            row['name'] = '@eurecamoment/benchforge-dsh/persistent-shell' if package_imports else (
                DSH_ROOT / 'tools/persistent-shell.mjs').as_uri()
            row['config']={**row.get('config',{}),'shell':shell}
    plugins.append(persistent)
    plugins.append(deepcopy(next(p for p in preset('cordis')['config']['plugins'] if p['id']=='tool-cordis')))
    return result
