#!/usr/bin/env python3
"""BenchForge: one entry point for demo, DSH setup and isolated web launch."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv],check=True,**kwargs)


def main():
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10+ is required. Run this launcher with your installed Python 3.10+ interpreter.')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['demo','setup','start'])
    parser.add_argument('--dsh-root',type=Path,help='Reuse an already built DSH checkout')
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--spatialforge-config', type=Path, help='Enable SpatialForge tools using an existing service configuration')
    parser.add_argument('--port',type=int,default=3080)
    args=parser.parse_args()
    if args.command=='demo':
        run([sys.executable,ROOT/'quickstart.py'],cwd=ROOT)
        return
    lock=json.loads((ROOT/'third_party/dependencies.json').read_text(encoding='utf-8'))['dsh']
    state=ROOT/'.benchforge'
    state.mkdir(exist_ok=True)
    saved=state/'runtime.json'
    if args.command=='setup':
        node=shutil.which('node')
        if not node:
            parser.error('Install Node.js 22.19+ or 24+ first: https://nodejs.org/')
        version=subprocess.check_output([node,'--version'],text=True).strip().lstrip('v')
        major,minor=map(int,version.split('.')[:2])
        if not ((major==22 and minor>=19) or major>=24):
            parser.error(f'Node {version} is unsupported; DSH requires {lock["node"]}')
        dsh=(args.dsh_root or ROOT/'third_party/deepseek-harness').resolve()
        if not args.dsh_root:
            if not dsh.exists():
                run(['git','clone','--depth','1','--branch',lock['ref'],lock['repository'],dsh])
            pnpm=shutil.which('pnpm')
            command=[pnpm] if pnpm else [shutil.which('npx') or 'npx','--yes',lock['package_manager']]
            if not (dsh/'apps/cli/lib/bin.js').exists():
                run([*command,'install','--frozen-lockfile'],cwd=dsh)
                run([*command,'run','build'],cwd=dsh)
        if not (dsh/'apps/cli/lib/bin.js').is_file():
            parser.error('DSH checkout is not built; run pnpm install and pnpm run build in it')
        run([sys.executable,ROOT/'quickstart.py','--dsh-root',dsh])
        if args.spatialforge_config:
            python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            run([python,ROOT/'integrations/spatialforge/build_preset.py',
                 '--dsh-root',dsh,'--python',python,'--config',ROOT/'config.local.json',
                 '--service-config',args.spatialforge_config.resolve(),'--output',ROOT/'benchforge.local.yml'])
        saved.write_text(json.dumps({'dsh_root':str(dsh),'node':node},indent=2),encoding='utf-8')
        print('Ready. Run: python benchforge.py start')
        return
    if not saved.is_file():
        parser.error('Run python benchforge.py setup first')
    config=json.loads(saved.read_text(encoding='utf-8'))
    env={**os.environ,'DSH_HOME':str(state/'dsh-home')}
    # An overlay and isolated home keep official presets and other installations untouched.
    command=[config['node'],str(Path(config['dsh_root'])/'apps/cli/lib/bin.js'),
             '--profile','web','--patch',str(ROOT/'benchforge.local.yml'),'--host','127.0.0.1','--port',str(args.port)]
    if args.no_open:
        command.append('--no-open')
    run(command,cwd=ROOT,env=env)


if __name__=='__main__':
    main()
