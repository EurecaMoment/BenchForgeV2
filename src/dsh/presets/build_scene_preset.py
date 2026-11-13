"""Generate BenchForge with BenchForge capabilities and no workbench UI."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('benchforge_preset_definition',
                                             Path(__file__).with_name('preset_definition.py'))
definition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(definition)
base, yaml = definition.base, definition.yaml

def build(sources, dsh_root, python, config_path, service_config, *, package_imports=False):
    return definition.build(sources, dsh_root, python, service_config, config_path=config_path,
                            with_ui=False, package_imports=package_imports)


def main():
    definition.single_preset_main(__doc__, with_ui=False, require_config=True)

if __name__ == '__main__':
    main()
