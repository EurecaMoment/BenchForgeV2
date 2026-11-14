"""Merge custom presets without rewriting session logs or workspace bindings."""
from copy import deepcopy
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('benchforge_presets',
                                             Path(__file__).with_name('build_presets.py'))
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)
base, spatial = catalog.base, catalog.spatial
UI_ID = spatial.WORKBENCH_PLUGIN_ID
LEGACY_UI_ID = spatial.LEGACY_WORKBENCH_PLUGIN_ID
HOST_IDS = {UI_ID, base.PRESET_ALIASES_PLUGIN_ID, base.CAPTURE_PLUGIN_ID, base.SESSION_OPERATIONS_PLUGIN_ID}
BUSINESS_PLUGINS = {'benchforge-tools', 'spatial-learning-tools', 'benchforge-scene-tools', 'tool-presentation'}


def inserted_rows(profile):
    return [row for patch in profile for row in patch.get('insert', [])]


def insert_host_dependencies(profile):
    """Attach the Host plugins to profiles generated before they were split out."""
    rows = inserted_rows(profile)
    ids = {row.get('id') for row in rows}
    missing = []
    if base.SESSION_OPERATIONS_PLUGIN_ID not in ids and any(preset_id(row) in base.PRESETS for row in rows):
        missing.append(spatial.session_operations_entry())
    workbench = next((row for row in rows if row.get('id') == UI_ID), None)
    if workbench is not None and base.CAPTURE_PLUGIN_ID not in ids:
        missing.append(spatial.capture_entry(workbench))
    if missing:
        profile.append({'insert': missing})
    return bool(missing)


preset_id = base.preset_id

def _merge_plugins(previous, incoming):
    """Refresh owned contracts while keeping deployment options and extra plugins."""
    unnamed = [deepcopy(row) for row in previous if row.get('id') is None]
    previous = {row['id']: row for row in previous if row.get('id') not in {None, LEGACY_UI_ID}}
    result = []
    for row in incoming:
        key = row.get('id')
        old = previous.pop(key, None)
        if old is None and key == 'spatial-learning-tools':
            old = previous.pop('benchforge-tools', None)
        merged = {**deepcopy(old or {}), **deepcopy(row)}
        old_config, new_config = (old or {}).get('config'), row.get('config')
        if isinstance(old_config, dict) and isinstance(new_config, dict):
            merged['config'] = {**deepcopy(old_config), **deepcopy(new_config)}
            if key == 'persona' and 'suffix' in old_config:
                merged['config']['suffix'] = old_config['suffix']
            if key == base.SCENE_PLUGIN_ID and 'serviceConfig' in old_config:
                merged['config']['serviceConfig'] = old_config['serviceConfig']
        elif isinstance(old_config, list) and isinstance(new_config, list):
            merged['config'] = _merge_plugins(old_config, new_config)
        result.append(merged)
    result.extend(deepcopy(row) for key, row in previous.items()
                  if key not in BUSINESS_PLUGINS and key not in {UI_ID, LEGACY_UI_ID})
    result.extend(unnamed)
    return result


def _workbench_config(profile, defaults):
    # Preset-local settings precede host settings. Retain every historical root.
    rows = inserted_rows(profile)
    local = [plugin for row in rows if preset_id(row) == base.WORKBENCH_PRESET_ID
             for plugin in row['config'].get('plugins', []) if plugin.get('id') == LEGACY_UI_ID]
    roots = [row for row in rows if row.get('id') == UI_ID]
    result, workspace_paths = deepcopy(defaults), []
    for row in local + roots:
        config = row.get('config') or {}
        result.update(deepcopy(config))
        workspace_paths.extend(config.get('workspacePaths', []))
    if workspace_paths:
        result['workspacePaths'] = list(dict.fromkeys(workspace_paths))
    return result


def replace_entries(profile, replacements):
    """Replace at the old location, collapse duplicate declarations, retain others."""
    result, remaining = deepcopy(profile), dict(replacements)
    for patch in result:
        if 'insert' not in patch:
            continue
        rows = []
        for row in patch['insert']:
            key = row['id'] if row.get('id') in HOST_IDS else preset_id(row)
            if key not in replacements:
                rows.append(row)
            elif key in remaining:
                replacement = deepcopy(remaining.pop(key))
                # Cordis row identity can differ from the session preset identity.
                replacement['id'] = row['id']
                rows.append(replacement)
        patch['insert'] = rows
    if remaining:
        result.append({'insert': list(deepcopy(remaining).values())})
    return result


def migrate_profile(profile, generated, revision=None, *, root=None, profile_dir=None):
    """Install the two BenchForge presets and a single workbench reader."""
    profile = deepcopy(profile or [])
    base.refresh_preset_identity(profile, root=root, profile_dir=profile_dir)
    old = {}
    for row in inserted_rows(profile):
        if preset_id(row) in base.PRESETS:
            old.setdefault(preset_id(row), row)
    replacements = {}
    for row in inserted_rows(generated):
        key = preset_id(row)
        if key in base.PRESETS:
            previous = old.get(key, {})
            previous_config = previous.get('config', {})
            new = {**deepcopy(previous), **deepcopy(row)}
            new['config'] = {**deepcopy(previous_config), **deepcopy(row['config'])}
            new['config']['plugins'] = _merge_plugins(previous_config.get('plugins', []), row['config']['plugins'])
            base.remove_retired_tool_filter(new['config']['plugins'])
            spatial.configure_synthesis_delegation(new['config']['plugins'])
            if revision is not None:
                new['config']['description'] += ', runtime revision ' + revision
            replacements[key] = new
        elif row.get('id') == UI_ID:
            new = deepcopy(row)
            new['config'] = _workbench_config(profile, new.get('config', {}))
            if revision is not None:
                new['config']['uiRevision'] = revision
            replacements[UI_ID] = new
        elif row.get('id') == base.PRESET_ALIASES_PLUGIN_ID:
            replacements[base.PRESET_ALIASES_PLUGIN_ID] = deepcopy(row)
        elif row.get('id') == base.SESSION_OPERATIONS_PLUGIN_ID:
            replacements[base.SESSION_OPERATIONS_PLUGIN_ID] = spatial.session_operations_entry(revision=revision)
    if base.PRESET_ALIASES_PLUGIN_ID not in replacements:
        replacements[base.PRESET_ALIASES_PLUGIN_ID] = base.preset_alias_entry()
    if UI_ID in replacements:
        replacements[base.CAPTURE_PLUGIN_ID] = spatial.capture_entry(replacements[UI_ID], revision=revision)
    if set(replacements) != set(base.PRESETS) | HOST_IDS:
        raise ValueError('Expected BenchForge, BenchForge_UI and their workbench reader')
    merged = replace_entries(profile, replacements)
    model_patches = [patch for patch in generated if patch.get('id') in {'llm-pi-ai', 'agent-default-model'}]
    if model_patches:
        base.refresh_host_models(merged, model_patches)
    return merged


def update_workbench(profile, root, workspace_paths=None, revision=None, *, profile_dir=None):
    """Refresh only UI presentation; all session identities and data paths survive."""
    profile = deepcopy(profile)
    base.refresh_preset_identity(profile, root=root, profile_dir=profile_dir)
    matches = [row for row in inserted_rows(profile) if preset_id(row) == base.WORKBENCH_PRESET_ID]
    if len(matches) != 1:
        raise ValueError('BenchForge_UI preset is missing or duplicated')
    preset = deepcopy(matches[0])
    preset['config']['name'] = base.PRESETS[base.WORKBENCH_PRESET_ID]['name']
    preset['config']['plugins'] = [row for row in preset['config'].get('plugins', [])
                                    if row.get('id') != LEGACY_UI_ID]
    config = _workbench_config(profile, {})
    if workspace_paths is not None:
        config['workspacePaths'] = [str(path) for path in workspace_paths]
    if revision is not None:
        config['uiRevision'] = revision
    ui = {'id': UI_ID, 'name': (root / 'src/dsh/ui/index.js').resolve().as_uri(), 'config': config}
    aliases = next((row for row in inserted_rows(profile) if row.get('id') == base.PRESET_ALIASES_PLUGIN_ID),
                   base.preset_alias_entry())
    capture = spatial.capture_entry(ui, revision=revision)
    sessions = spatial.session_operations_entry(revision=revision)
    return replace_entries(profile, {base.WORKBENCH_PRESET_ID: preset, UI_ID: ui,
                                     base.PRESET_ALIASES_PLUGIN_ID: aliases,
                                     base.CAPTURE_PLUGIN_ID: capture, base.SESSION_OPERATIONS_PLUGIN_ID: sessions})
