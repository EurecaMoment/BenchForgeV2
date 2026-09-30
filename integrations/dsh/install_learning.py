"""Add spatial-learning tools to explicitly selected custom DSH presets."""
import argparse
from pathlib import Path
import shutil
import yaml
from build_preset import Loader,Dumper

TOOLS=['spatial_catalog','spatial_generate','spatial_export','spatial_evaluate','curriculum','spatial_train','spatial_experiment','training_monitor']


def install(path,python,dsh_root):
    path=Path(path);data=yaml.load(path.read_text(encoding='utf8'),Loader=Loader)
    plugin={'id':'spatial-learning-tools','name':str(Path(__file__).with_name('tools.mjs').resolve()),
        'config':{'python':str(Path(python).expanduser().absolute()),'dshRoot':str(Path(dsh_root).resolve()),'includeTools':TOOLS}}
    changed=[]
    for patch in data:
        for preset in patch.get('insert',[]):
            if preset.get('name')!='@deepseek-ai/dsh-agent-preset':continue
            plugins=preset['config']['plugins']
            existing=next((p for p in plugins if p['id']=='spatial-learning-tools'),None)
            if existing is None:plugins.append(plugin)
            else:existing.update(plugin)
            changed.append(preset['config']['id'])
    backup=path.with_suffix(path.suffix+'.before-spatial-learning')
    if not backup.exists():shutil.copy2(path,backup)
    path.write_text(yaml.dump(data,Dumper=Dumper,sort_keys=False,allow_unicode=True),encoding='utf8')
    return changed


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--preset',required=True);parser.add_argument('--python',required=True);parser.add_argument('--dsh-root',required=True)
    args=parser.parse_args();print(install(args.preset,args.python,args.dsh_root))
