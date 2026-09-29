"""Generate a new BenchForge mode. Never writes official presets or profiles."""
import argparse
from copy import deepcopy
from pathlib import Path
import yaml


class JavaScript(str):
    pass


class Loader(yaml.SafeLoader):
    pass


class Dumper(yaml.SafeDumper):
    pass


Loader.add_constructor('tag:yaml.org,2002:js', lambda loader,node:JavaScript(loader.construct_scalar(node)))
Dumper.add_representer(JavaScript, lambda dumper,value:dumper.represent_scalar('tag:yaml.org,2002:js',str(value)))

PERSONA = '''You operate BenchForge, an independent benchmark construction mode.
Keep Standard's conversational interaction, file tools, image inspection and task code. Choose the available tools that fit the current objective; catalog, methods, source processing, annotation, compilation, synthesis, scoring, review and reporting are composable capabilities rather than a required sequence.
Use direct tools, PTC and collaboration tools when they help. Split genuinely independent work among available agents, keep a shared workspace, and publish concise handoffs so another agent can resume, reply, reconcile evidence or take over a blocked piece. Handoffs may link related work and state a decision, but no fixed graph, round count, role roster or approval step is implied. Coordinate simulator submissions through the configured execution boundary and avoid overwriting active artifacts.
Discover exact tool contracts from the session catalog when needed, then use the listed tools directly. Arrays of capabilities, sources, templates and metrics contain objects with id fields. Prefer supplied domain methods, compilers, annotation chains and validation evidence; write an adapter only when the source or task actually needs one.
Inspect relevant images and returned evidence, and let observations guide the next code or tool call. Preserve source labels, simulator state and provenance. Model masks, inferred depth and review findings are predictions or guidance; they do not replace GT from official records, task programs or simulation.
For simulation distance questions, use the declared depth semantics and camera intrinsics so the oracle matches the wording. Keep authority data and raw arrays separate from public media, and resolve relative evidence paths from their source document.
Package public questions/media separately from authority data. Scale synthesis when the requested coverage and scorer controls are met; use configured model evaluation only on public inputs and label proxy baselines as such. Report concrete artifacts, evidence and remaining gaps.
Prefer task code and inputs for task-specific changes. Keep verification proportional to the deliverable and avoid checksum manifests or broad filesystem audits unless they answer a concrete question.
'''


def build(sources, root, python, config_path):
    def preset(name):
        return next(row for patch in sources[name] for row in patch.get('insert',[]) if row['id']=='preset-'+name)
    result=deepcopy(preset('standard'))
    result['id']='preset-benchforge'
    cfg=result['config']
    cfg.update(id='benchforge',name='BenchForge',order=-2,
               description='Composable benchmark construction, annotation, simulation and evidence.')
    plugins=cfg['plugins']
    persona=next(p for p in plugins if p['id']=='persona')
    persona['config']['prefix']=PERSONA
    presentation=deepcopy(next(p for p in preset('ptc')['config']['plugins'] if p['id']=='tool-presentation'))
    presentation['config']['mode']='both'
    plugins.append(presentation)
    persistent=deepcopy(next(p for p in preset('minimal')['config']['plugins'] if p['id']=='persistent-shell'))
    for row in persistent['config']:
        if row['id'] in ('persistent-bash','persistent-pwsh'):
            shell='bash' if row['id']=='persistent-bash' else 'pwsh'
            row['name']=str(Path(__file__).with_name('persistent-shell.mjs').resolve())
            row['config']={'shell':shell,'timeoutMs':row['config']['timeoutMs'],'dshRoot':str(root.resolve())}
    plugins.append(persistent)
    plugins.append(deepcopy(next(p for p in preset('cordis')['config']['plugins'] if p['id']=='tool-cordis')))
    plugins.append({'id':'benchforge-tools','name':str(Path(__file__).with_name('tools.mjs').resolve()),
                    'config':{'dshRoot':str(root.resolve()),'python':python,'configPath':str(config_path.resolve())}})
    return [{'insert':[result]}]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsh-root',required=True,type=Path)
    parser.add_argument('--python',default='python')
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    base=args.dsh_root/'packages/bundle/web-app/presets'
    sources={name:yaml.load((base/(name+'.patch.yml')).read_text(encoding='utf-8'),Loader=Loader) for name in ['standard','ptc','minimal','cordis']}
    result=build(sources,args.dsh_root,args.python,args.config)
    args.output.write_text(yaml.dump(result,Dumper=Dumper,sort_keys=False,allow_unicode=True),encoding='utf-8')


if __name__=='__main__':
    main()
