"""Install the generated BenchForge declarations in a DSH profile."""
from copy import deepcopy

if __package__:
    from . import build_preset as base
    from . import preset_definition as definition
else:
    import build_preset as base
    import preset_definition as definition


HOST_IDS = {base.WORKBENCH_PLUGIN_ID, base.CAPTURE_PLUGIN_ID, base.SESSION_OPERATIONS_PLUGIN_ID}


def insert_host_dependencies(profile):
    """Attach the Host services used by generated presets."""
    rows = [row for patch in profile for row in patch.get('insert', [])]
    ids = {row.get('id') for row in rows}
    entries = []
    if base.SESSION_OPERATIONS_PLUGIN_ID not in ids and any(base.preset_id(row) in base.PRESETS for row in rows):
        entries.append(definition.session_operations_entry())
    workbench = next((row for row in rows if row.get('id') == base.WORKBENCH_PLUGIN_ID), None)
    if workbench and base.CAPTURE_PLUGIN_ID not in ids:
        entries.append(definition.capture_entry(workbench))
    if entries:
        profile.append({'insert': entries})


def _merge_configuration(old, new):
    if isinstance(old, dict) and isinstance(new, dict):
        return {**old, **new}
    return new


def _merge_preset(row, previous):
    incoming = row['config']
    prior = previous.get('config', {})
    previous_plugins = {plugin['id']: plugin for plugin in prior.get('plugins', []) if 'id' in plugin}
    plugins = []
    for plugin in incoming['plugins']:
        old = previous_plugins.pop(plugin['id'], {})
        if 'config' in plugin:
            options = _merge_configuration(old.get('config'), plugin['config'])
            merged = {**old, **plugin, 'config': options}
            if plugin['id'] == 'persona' and 'suffix' in old.get('config', {}):
                options['suffix'] = old['config']['suffix']
        else:
            merged = {**old, **plugin}
        plugins.append(merged)
    plugins.extend(previous_plugins.values())
    plugins.extend(plugin for plugin in prior.get('plugins', []) if 'id' not in plugin)
    return {**previous, **row, 'id': previous.get('id', row['id']),
            'config': {**prior, **incoming, 'plugins': plugins}}


def migrate_profile(profile, generated, revision=None):
    """Merge the generated presets and Host options into an existing profile."""
    profile = deepcopy(profile or [])
    generated = deepcopy(generated)
    base.refresh_preset_identity(profile)
    entries = next(patch['insert'] for patch in generated if 'insert' in patch)

    def identity(row):
        return row['id'] if row.get('id') in HOST_IDS else base.preset_id(row)

    remaining = {identity(row): row for row in entries}
    declared = set(remaining)
    installed = {}
    for patch in profile:
        if 'insert' not in patch:
            continue
        rows = []
        for old in patch['insert']:
            key = identity(old)
            if key not in declared:
                rows.append(old)
                continue
            new = remaining.pop(key, None)
            if new is None:
                if key in base.PRESETS:
                    merged = _merge_preset(installed[key], old)
                    installed[key].clear()
                    installed[key].update(merged)
                continue
            if key in base.PRESETS:
                new = _merge_preset(new, old)
            elif 'config' in new:
                defaults = new['config']
                old_config = old.get('config', {})
                new['config'] = {**old_config, **defaults}
                if old_config.get('workspacePaths'):
                    new['config']['workspacePaths'] = old_config['workspacePaths']
            rows.append(new)
            installed[key] = new
        patch['insert'] = rows

    if remaining:
        profile.append({'insert': list(remaining.values())})
    rows = [row for patch in profile for row in patch.get('insert', [])]
    workbench = next(row for row in rows if row.get('id') == base.WORKBENCH_PLUGIN_ID)
    capture = next(row for row in rows if row.get('id') == base.CAPTURE_PLUGIN_ID)
    capture['config'].update(definition.capture_entry(workbench)['config'])
    if revision is not None:
        workbench['config']['uiRevision'] = revision
        capture['config']['revision'] = revision
        next(row for row in rows if row.get('id') == base.SESSION_OPERATIONS_PLUGIN_ID)['config']['revision'] = revision
        for row in rows:
            if base.preset_id(row) in base.PRESETS:
                row['config']['description'] += ', runtime revision ' + revision
    base.refresh_host_models(profile, [patch for patch in generated if 'insert' not in patch])
    return profile
