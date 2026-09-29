#!/usr/bin/env python3
"""Run an offline demo, or install this independent mode into an existing DSH."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=Path('runs/quickstart'))
    parser.add_argument('--dsh-root',type=Path,help='Optional existing deepseek-harness checkout')
    parser.add_argument('--profile',type=Path,help='Optional DSH profile patch to install this mode into; backs up before editing')
    parser.add_argument('--config',type=Path,help='Existing machine config; otherwise creates config.local.json from example')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if args.profile and not args.dsh_root:
        parser.error('--profile requires --dsh-root')
    if not args.dsh_root:
        env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONIOENCODING':'utf-8'}
        subprocess.run([sys.executable,str(root/'examples/offline_demo.py'),'--workspace',str(args.workspace.resolve())],env=env,check=True)
        result=json.loads((args.workspace/'demo-result.json').read_text(encoding='utf-8'))
        print('Offline demo complete: 2 items, exact-match accuracy 0.5 (one deliberately wrong prediction).')
        print('Public package:',result['package']['package'])
        print('For DSH mode setup, rerun with --dsh-root PATH; add --profile PATH to install the new preset.')
        return
    dsh=args.dsh_root.resolve()
    presets=dsh/'packages/bundle/web-app/presets'
    if not (presets/'standard.patch.yml').is_file():
        parser.error(f'DSH preset directory not found: {presets}. Supply the deepseek-harness checkout root.')
    environment=root/'.venv'
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python),'-m','pip','install',str(root)+'[dsh,production,research]'],check=True)
    config=(args.config or root/'config.local.json').resolve()
    if not config.exists():
        config.write_text((root/'config.example.json').read_text(encoding='utf-8'),encoding='utf-8')
    output=root/'benchforge.local.yml'
    subprocess.run([str(python),str(root/'integrations/dsh/build_preset.py'),
        '--dsh-root',str(dsh),'--python',str(python),'--config',str(config),'--output',str(output)],check=True)
    if args.profile:
        subprocess.run([str(python),str(root/'integrations/dsh/install_preset.py'),
            '--preset',str(output),'--profile',str(args.profile.resolve())],check=True)
        print('Installed BenchForge. Select it for a new conversation; existing sessions stay unchanged.')
    else:
        print('Generated mode:',output)
        print('Add --profile PATH to install it into your DSH profile, or load the patch using your DSH configuration.')
    print('Core benchmark tools are ready. Configure only the GPU services and simulators you intend to use:',config)


if __name__=='__main__':
    main()
