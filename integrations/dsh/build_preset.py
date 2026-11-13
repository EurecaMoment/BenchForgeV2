"""Common DSH preset composition and model settings."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import yaml


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
MODEL_TOOLS = [
    'model_yoloe', 'model_sam3', 'model_moge', 'model_lama', 'model_flux_fill',
    'model_osor_flux_fill', 'model_objectclear_fill', 'model_qwen_image_edit',
    'model_diffusion', 'model_depth_anything', 'model_sam3d', 'model_blender',
]
DEFAULT_SERVICE_CONFIG = Path('config/generated/benchforge-client.local.json')
LEGACY_SERVICE_CONFIG = Path('config/benchforge-client.local.json')
LEGACY_SERVICE_CONFIGS = (
    LEGACY_SERVICE_CONFIG, Path('config/generated/spatialforge.local.json'), Path('config/spatialforge.local.json'),
)
SERVER_SERVICE_CONFIGS = (
    Path('config/generated/benchforge-server.local.json'),
    Path('config/generated/spatialforge-server.local.json'), Path('config/spatialforge-server.local.json'),
)


def set_identity(row, preset_id):
    """Keep preset metadata in one place, independent of tool composition."""
    row['id'] = 'preset-' + preset_id
    row['config'].update(id=preset_id, **PRESETS[preset_id])


def preset_alias_entry(*, package_imports=False):
    name = '@eurecamoment/benchforge-dsh/preset-aliases' if package_imports else str(
        Path(__file__).with_name('preset_aliases.mjs').resolve())
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
    name = registry.get('model_roles', {}).get('dsh')
    if not name:
        return []
    model = registry.get('models', {}).get(name)
    if not isinstance(model, dict):
        raise ValueError(f'model_roles.dsh references an unknown model: {name}')
    if not model.get('model') or str(model['model']).startswith('YOUR_'):
        return []
    if not model.get('url'):
        raise ValueError(f'Configure models.{name}.url for the DSH model')
    descriptor = {'id': model['model'], 'name': model.get('name', model['model'])}
    for source, target in (('context_window', 'contextWindow'), ('max_tokens', 'maxTokens'),
                           ('input', 'input'), ('reasoning_efforts', 'reasoningEfforts')):
        if source in model:
            descriptor[target] = model[source]
    provider = {'displayName': 'BenchForge models', 'api': model.get('api', 'openai-completions'),
                'baseURL': model['url'], 'models': [descriptor]}
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
            row['name'] = row['name'].replace('integrations/spatialforge/', 'integrations/benchforge/').replace(
                'integrations\\spatialforge\\', 'integrations\\benchforge\\')
        if isinstance(config, list):
            _refresh_preset_plugins(config)
        elif isinstance(config, dict):
            for key in (('prefix', 'suffix') if row.get('id') == 'persona' else ('persona',)
                        if name == '@deepseek-ai/dsh-tool-subagent' else ()):
                if isinstance(config.get(key), str):
                    prompt = _rename_scene_tokens(config[key])
                    prompt = re.sub(r'(?<!/)\bBenchForgeV2\b|\bSpatialForge\b', 'BenchForge', prompt)
                    config[key] = prompt.replace('BenchForgeV2_UI', 'BenchForge_UI').replace(
                        'integrations/spatialforge/', 'integrations/benchforge/')
            tool_filter = config.get('toolFilter')
            if isinstance(tool_filter, dict):
                for key in ('allow', 'deny'):
                    if isinstance(tool_filter.get(key), list):
                        tool_filter[key] = [_rename_scene_tokens(value) if isinstance(value, str) else value
                                            for value in tool_filter[key]]


def refresh_preset_identity(profile):
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
    return changed


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
            if row.get('id') in {WORKBENCH_PLUGIN_ID, LEGACY_WORKBENCH_PLUGIN_ID}:
                changed = refresh(row, 'productionConfig', legacy | servers) or changed
            if preset_id(row) not in PRESETS:
                continue
            for plugin in row['config']['plugins']:
                if plugin.get('id') == SCENE_PLUGIN_ID:
                    changed = refresh(plugin, 'serviceConfig', legacy | servers) or changed
                if plugin.get('id') == LEGACY_WORKBENCH_PLUGIN_ID:
                    changed = refresh(plugin, 'productionConfig', legacy | servers) or changed
    return changed


def refresh_model_patches(preset_path, config_path):
    """Refresh generated deployment settings and retire old preset entries."""
    preset_path = Path(preset_path)
    if not preset_path.is_file():
        return
    patches = model_patches(config_path)
    profile = yaml.load(preset_path.read_text(encoding='utf-8'), Loader=Loader) or []
    changed = refresh_preset_identity(profile)
    changed = refresh_service_paths(profile, config_path) or changed
    inserts = [row for patch in profile for row in patch.get('insert', [])]
    if any(preset_id(row) in PRESETS for row in inserts) and not any(
            row.get('id') == PRESET_ALIASES_PLUGIN_ID for row in inserts):
        profile.append({'insert': [preset_alias_entry()]})
        changed = True
    for patch in profile:
        for row in patch.get('insert', []):
            if preset_id(row) in PRESETS:
                changed = remove_retired_tool_filter(row['config']['plugins']) or changed
    if not patches:
        retained = []
        for row in profile:
            if (row.get('id') == 'agent-default-model'
                    and row.get('config', {}).get('provider') == 'benchforge-models'):
                changed = True
                continue
            if row.get('id') == 'llm-pi-ai':
                providers = row.get('config', {}).get('providers', {})
                if 'benchforge-models' in providers:
                    providers.pop('benchforge-models')
                    changed = True
            retained.append(row)
        profile = retained
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
    if changed:
        temporary = preset_path.with_suffix(preset_path.suffix + '.tmp')
        temporary.write_text('# Generated settings read config/benchforge.local.json.\n'
                             + yaml.dump(profile, Dumper=Dumper, sort_keys=False, allow_unicode=True),
                             encoding='utf-8', newline='\n')
        temporary.replace(preset_path)


def compose_standard(sources, *, package_imports=False):
    def preset(name):
        return next(row for patch in sources[name] for row in patch.get('insert',[]) if row['id']=='preset-'+name)
    result=deepcopy(preset('standard'))
    plugins=result['config']['plugins']
    presentation=deepcopy(next(p for p in preset('ptc')['config']['plugins'] if p['id']=='tool-presentation'))
    presentation['config']['mode']='both'
    plugins.append(presentation)
    persistent=deepcopy(next(p for p in preset('minimal')['config']['plugins'] if p['id']=='persistent-shell'))
    for row in persistent['config']:
        if row['id'] in ('persistent-bash','persistent-pwsh'):
            shell='bash' if row['id']=='persistent-bash' else 'pwsh'
            row['name']='@eurecamoment/benchforge-dsh/persistent-shell' if package_imports else str(Path(__file__).with_name('persistent-shell.mjs').resolve())
            row['config']={**row.get('config',{}),'shell':shell}
    plugins.append(persistent)
    plugins.append(deepcopy(next(p for p in preset('cordis')['config']['plugins'] if p['id']=='tool-cordis')))
    return result
