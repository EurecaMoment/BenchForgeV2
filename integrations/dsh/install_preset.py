"""Install only the new BenchForge preset row into an explicitly supplied profile."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import yaml
from build_preset import Loader, Dumper


def install(profile, preset):
    current=yaml.load(profile.read_text(encoding='utf-8'),Loader=Loader) or []
    incoming=yaml.load(preset.read_text(encoding='utf-8'),Loader=Loader)[0]['insert'][0]
    if incoming['id']!='preset-benchforge':
        raise ValueError('Expected the independently generated BenchForge preset')
    found=False
    for patch in current:
        for index,row in enumerate(patch.get('insert',[])):
            if row.get('id')==incoming['id']:
                patch['insert'][index]=incoming
                found=True
    if not found:
        current.append({'insert':[incoming]})
    backup=profile.with_name(profile.name+'.before-benchforge-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    shutil.copy2(profile,backup)
    temporary=profile.with_name(profile.name+'.benchforge-new')
    temporary.write_text(yaml.dump(current,Dumper=Dumper,sort_keys=False,allow_unicode=True),encoding='utf-8')
    shutil.copymode(profile,temporary)
    temporary.replace(profile)
    return backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True,type=Path)
    parser.add_argument('--preset',required=True,type=Path)
    args=parser.parse_args()
    print('Installed BenchForge only; backup:',install(args.profile,args.preset))


if __name__=='__main__':
    main()
