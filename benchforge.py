#!/usr/bin/env python3
"""Set up and launch BenchForge in an isolated DSH Web profile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import benchforge_app

ROOT=Path(__file__).resolve().parent


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv],check=True,**kwargs)


def uses_local_service(preset):
    import yaml
    from integrations.benchforge.check_config import service_config_paths

    profile = yaml.load(preset.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    config = ROOT / 'config'
    local = benchforge_app.settings.local_service_configs(config, config / 'generated')
    return any(isinstance(reference, str) and (ROOT / reference).resolve() in local
               for reference in service_config_paths(profile))


def main():
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10+ is required. Run this launcher with your installed Python 3.10+ interpreter.')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['setup','start'])
    parser.add_argument('--dsh-root',type=Path,help='Reuse an already built DSH checkout')
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--benchforge-config', '--service-config', type=Path,
                        help='Enable BenchForge tools using an existing service configuration')
    parser.add_argument('--port', type=int, help='Override the configured Web port')
    parser.add_argument('--check-config', action='store_true', help='Validate the Web setup before launching it')
    parser.add_argument('--config-synced', action='store_true', help=argparse.SUPPRESS)
    args=parser.parse_args()
    preset=ROOT/'config/generated/benchforge.local.yml'
    model_config=ROOT/'config/benchforge.local.json'
    generated = ROOT / 'config/generated'
    service_config = (args.benchforge_config or generated / benchforge_app.settings.CLIENT_CONFIG).resolve()
    if args.command=='setup':
        if args.check_config:
            parser.error('--check-config requires start')
        local = benchforge_app.settings.local_service_configs(generated.parent, generated)
        if service_config in local:
            run([sys.executable, ROOT/'benchforge_app.py', 'sync'], cwd=ROOT)
            service_config = local[service_config]
        if not service_config.is_file():
            parser.error(f'BenchForge configuration not found: {service_config}. '
                         'Run python benchforge_app.py init, or pass --benchforge-config with the actual file path.')
    lock=json.loads((ROOT/'third_party/dependencies.json').read_text(encoding='utf-8'))['dsh']
    state=ROOT/'.benchforge'
    state.mkdir(exist_ok=True)
    saved=state/'runtime.json'
    environment=ROOT/'.venv'
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
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
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        run([python,'-m','pip','install',str(ROOT)+'[dsh,production,research]'],cwd=ROOT)
        if not model_config.exists():
            shutil.copyfile(ROOT/'config/benchforge.example.json',model_config)
        preset.parent.mkdir(parents=True,exist_ok=True)
        run([python,ROOT/'integrations/dsh/build_presets.py',
             '--dsh-root',dsh,'--node',node,'--python',python,'--config',model_config,
             '--service-config',service_config,'--output',preset])
        saved.write_text(json.dumps({'dsh_root':str(dsh),'node':node},indent=2),encoding='utf-8')
        print('Ready. Run: python benchforge.py start')
        return
    if not saved.is_file():
        parser.error('Run python benchforge.py setup first')
    config=json.loads(saved.read_text(encoding='utf-8'))
    if not python.is_file():
        parser.error('The BenchForge Python environment is missing; run python benchforge.py setup first')
    if preset.is_file() and not args.config_synced and uses_local_service(preset):
        run([python, ROOT/'benchforge_app.py', 'sync'], cwd=ROOT)
    env = benchforge_app.build_environment(database=False)
    env['DSH_HOME'] = str(state/'dsh-home')
    paths = [str(ROOT / 'src')]
    if env.get('PYTHONPATH'):
        paths.append(env['PYTHONPATH'])
    env['PYTHONPATH'] = os.pathsep.join(paths)
    try:
        port = args.port if args.port is not None else benchforge_app.configured_web_port()
    except ValueError as error:
        parser.error(str(error))
    from integrations.dsh.build_preset import refresh_model_patches
    if not args.config_synced or args.check_config:
        refresh_model_patches(preset, model_config)
    try:
        run([python,ROOT/'integrations/benchforge/check_config.py','--preset',preset],cwd=ROOT,env=env)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    if args.check_config:
        return
    # An overlay and isolated home keep official presets and other installations untouched.
    command=[config['node'],str(Path(config['dsh_root'])/'apps/cli/lib/bin.js'),
             '--profile','web','--patch',str(preset),'--host','127.0.0.1','--port',str(port)]
    if args.no_open:
        command.append('--no-open')
    run(command,cwd=ROOT,env=env)


if __name__=='__main__':
    main()
