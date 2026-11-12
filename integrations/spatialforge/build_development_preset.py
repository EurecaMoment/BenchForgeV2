"""Compatibility CLI for the BenchForgeV2_UI preset (retained legacy entry point)."""
import argparse
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('spatialforge_preset_definition',
                                             Path(__file__).with_name('preset_definition.py'))
definition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(definition)

# Keep callers of the older builder working without maintaining a second policy.
base, yaml = definition.base, definition.yaml
PERSONA, PARALLEL_SYNTHESIS = definition.PERSONA, definition.PARALLEL_SYNTHESIS
LEARNING_TOOLS, MODEL_TOOLS = definition.LEARNING_TOOLS, definition.MODEL_TOOLS
SYNTHESIS_WORKER_PERSONA = definition.SYNTHESIS_WORKER_PERSONA
PARENT_OWNED_SYNTHESIS_TOOLS = definition.PARENT_OWNED_SYNTHESIS_TOOLS
DEFAULT_SYNTHESIS_REASONING_EFFORT = definition.DEFAULT_SYNTHESIS_REASONING_EFFORT
configured_synthesis_tools = definition.configured_synthesis_tools
configure_synthesis_delegation = definition.configure_synthesis_delegation
build = definition.build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base.add_source_arguments(parser)
    parser.add_argument('--python', required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--service-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.service_config.is_file():
        parser.error(f'BenchForgeV2 configuration not found: {args.service_config.resolve()}. '
                     'Run python spatialforge_app.py init, or pass --service-config with the actual file path.')
    sources = base.load_sources(args.dsh_root, args.node, args.dsh_resolve_from)
    result = build(sources, args.dsh_root, args.python, args.service_config, config_path=args.config)
    args.output.write_text(yaml.dump(result, Dumper=base.Dumper, sort_keys=False, allow_unicode=True),
                           encoding='utf-8')


if __name__ == '__main__':
    main()
