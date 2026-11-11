"""Generate BenchForgeV2 with SpatialForge capabilities and no workbench UI."""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('spatialforge_preset_definition',
                                             Path(__file__).with_name('preset_definition.py'))
definition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(definition)
base, yaml = definition.base, definition.yaml

def build(sources, dsh_root, python, config_path, service_config, *, package_imports=False):
    return definition.build(sources, dsh_root, python, service_config, config_path=config_path,
                            with_ui=False, package_imports=package_imports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base.add_source_arguments(parser)
    parser.add_argument('--python', required=True)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--service-config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.service_config.is_file():
        parser.error(f'SpatialForge configuration not found: {args.service_config.resolve()}. '
                     'Run python spatialforge_app.py init, or pass --service-config with the actual file path.')
    sources = base.load_sources(args.dsh_root, args.node, args.dsh_resolve_from)
    result = build(sources, args.dsh_root, args.python, args.config, args.service_config)
    args.output.write_text(yaml.dump(result, Dumper=base.Dumper, sort_keys=False, allow_unicode=True), encoding='utf-8')

if __name__ == '__main__':
    main()
