"""Generate the combined mode without changing any installed DSH preset."""
import argparse
import importlib.util
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('benchforge_preset', ROOT/'integrations/dsh/build_preset.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsh-root', required=True, type=Path)
    parser.add_argument('--python', required=True)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--service-config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    directory = args.dsh_root/'packages/bundle/web-app/presets'
    sources = {name: yaml.load((directory/(name+'.patch.yml')).read_text(encoding='utf-8'), Loader=base.Loader)
               for name in ['standard', 'ptc', 'minimal', 'cordis']}
    result = base.build(sources, args.dsh_root, args.python, args.config)
    row = result[0]['insert'][0]
    row['id'] = 'preset-benchforgev2'
    row['config'].update(id='benchforgev2', name='BenchForgeV2')
    plugins = row['config']['plugins']
    persona = next(p for p in plugins if p['id'] == 'persona')
    persona['config']['prefix'] += """
Use SpatialForge tools for reference generation, assets, SceneProgram capture and actual interaction evidence.
Generate and inspect the design reference before authoring a new scene. Inspect returned pixels and correct visible omissions by updating task code and capturing again.
A successful capture or completed TODO is not delivery acceptance. Do not substitute a list of fixable limitations for completing the requested work.
Finish with a concise user-facing delivery, rather than internal review narration. Keep physics, visual quality and usable files distinct.
The configured service owns the single desktop Isaac queue. Never launch a second simulator or modify Harness code, service configuration, acceptance rules or GT.
GT comes from official sources, task programs or simulation. Do not call target-model APIs to evaluate it.
"""
    plugins.append({'id': 'spatialforge-tools', 'name': str(ROOT/'integrations/spatialforge/plugin/tools.mjs'),
                    'config': {'dshRoot': str(args.dsh_root.resolve()), 'serviceConfig': str(args.service_config.resolve())}})
    args.output.write_text(yaml.dump(result, Dumper=base.Dumper, sort_keys=False, allow_unicode=True), encoding='utf-8')

if __name__ == '__main__':
    main()
