"""Check the configuration paths actually recorded in a DSH preset before startup."""
import argparse
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from benchforge_core.service_config import resolve_service_config_file


def service_config_paths(value):
    if isinstance(value, list):
        for child in value:
            yield from service_config_paths(child)
    elif isinstance(value, dict):
        if value.get('disabled') == 'true':
            return
        config = value.get('config')
        if value.get('id') == 'spatialforge-tools' and isinstance(config, dict):
            if 'serviceConfig' in config:
                yield config['serviceConfig']
        for child in value.values():
            yield from service_config_paths(child)


def check_preset(preset):
    # BaseLoader treats !!js and all other scalar tags as text; it executes nothing.
    profile = yaml.load(Path(preset).read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    checked = set()
    for value in service_config_paths(profile):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('spatialforge-tools.serviceConfig must name a configuration file')
        path = resolve_service_config_file(value)
        if path in checked:
            continue
        if not path.is_file():
            raise FileNotFoundError(
                f'BenchForgeV2 configuration referenced by {preset} does not exist: {path}. '
                'Run python spatialforge_app.py init to create the default client configuration. '
                'If the configuration was moved, update serviceConfig in this preset to its actual path '
                '(for example config/generated/spatialforge.local.json).')
        config = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ValueError(f'BenchForgeV2 configuration must be a JSON object: {path}')
        checked.add(path)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', required=True, type=Path)
    args = parser.parse_args()
    try:
        checked = check_preset(args.preset)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    print(f'Checked {len(checked)} BenchForgeV2 configuration file(s).')


if __name__ == '__main__':
    main()
