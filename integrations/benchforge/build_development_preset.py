"""Compatibility CLI for the BenchForge_UI preset (retained legacy entry point)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('benchforge_preset_definition',
                                             Path(__file__).parents[1] / 'dsh/preset_definition.py')
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
    definition.single_preset_main(__doc__, with_ui=True)


if __name__ == '__main__':
    main()
