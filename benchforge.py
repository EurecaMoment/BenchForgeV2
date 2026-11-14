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
    from dsh.check_config import service_config_paths

    profile = yaml.load(preset.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    config = ROOT / 'config'
    local = benchforge_app.settings.local_service_configs(config / 'generated')
    return any(isinstance(reference, str) and (ROOT / reference).resolve() in local
               for reference in service_config_paths(profile))


def pinned_dsh_revision(lock):
    entry = subprocess.check_output(['git', 'ls-tree', 'HEAD', '--', lock['path']], cwd=ROOT, text=True)
    return entry.split()[2]


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
        local = benchforge_app.settings.local_service_configs(generated)
        if service_config in local:
            run([sys.executable, ROOT/'benchforge_app.py', 'sync'], cwd=ROOT)
            service_config = local[service_config]
        if not service_config.is_file():
            parser.error(f'BenchForge configuration not found: {service_config}. '
                         'Run python benchforge_app.py init, or pass --benchforge-config with the actual file path.')
    example_config = ROOT / 'config/benchforge.example.json'
    lock = benchforge_app.settings.read_object(example_config)['dsh']
    state=ROOT/'.benchforge'
    state.mkdir(exist_ok=True)
    saved=state/'runtime.json'
    environment=ROOT/'.venv'
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if args.command=='setup':
        node=shutil.which('node')
        if not node:
            parser.error(f'Install Node.js {lock["node"]} first: https://nodejs.org/')
        version=subprocess.check_output([node,'--version'],text=True).strip().lstrip('v')
        installed_node = tuple(map(int, version.split('-', 1)[0].split('.')))
        minimum_node = tuple(map(int, lock['node'].removeprefix('>=').split('.')))
        if installed_node < minimum_node:
            parser.error(f'Node {version} is unsupported; DSH requires {lock["node"]}')
        dsh=(args.dsh_root or ROOT/lock['path']).resolve()
        cli = dsh/'apps/cli/lib/bin.js'
        if not args.dsh_root:
            run(['git', '-c', 'core.longpaths=true', 'submodule', 'update', '--init', '--recursive',
                 '--depth', '1', '--', lock['path']], cwd=ROOT)
        manifest = benchforge_app.settings.read_object(dsh / 'package.json', optional=True)
        if manifest.get('version') != lock['version']:
            parser.error(f'DSH at {dsh} must be version {lock["version"]}; found {manifest.get("version", "no package.json")}')
        runtime = {'dsh_root': str(dsh), 'node': node, 'dsh_version': lock['version']}
        if not args.dsh_root:
            revision = subprocess.check_output(['git', '-C', str(dsh), 'rev-parse', 'HEAD'], text=True).strip()
            runtime['dsh_revision'] = revision
            try:
                previous = json.loads(saved.read_text(encoding='utf-8'))
            except (FileNotFoundError, ValueError):
                previous = {}
            if not cli.is_file() or previous != runtime:
                pnpm = shutil.which('pnpm')
                package_manager = lock['package_manager']
                if pnpm and subprocess.check_output([pnpm, '--version'], cwd=dsh, text=True).strip() == package_manager.removeprefix('pnpm@'):
                    command = [pnpm]
                elif npx := shutil.which('npx'):
                    command = [npx, '--yes', package_manager]
                elif pnpm:
                    command = [pnpm, 'dlx', package_manager]
                else:
                    parser.error(f'Install {package_manager} or npm to build DSH')
                run([*command,'install','--frozen-lockfile'],cwd=dsh)
                run([*command,'run','build:artifacts'],cwd=dsh)
        if not cli.is_file():
            parser.error('DSH checkout is not built; run pnpm install and pnpm run build in it')
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        run([python,'-m','pip','install',str(ROOT)+'[dsh,production,research]'],cwd=ROOT)
        if not model_config.exists():
            shutil.copyfile(example_config,model_config)
        preset.parent.mkdir(parents=True,exist_ok=True)
        run([python,ROOT/'src/dsh/presets/build_presets.py',
             '--dsh-root',dsh,'--node',node,'--python',python,'--config',model_config,
             '--service-config',service_config,'--output',preset])
        saved.write_text(json.dumps(runtime,indent=2),encoding='utf-8')
        print('Ready. Run: python benchforge.py start')
        return
    if not saved.is_file():
        parser.error('Run python benchforge.py setup first')
    config=json.loads(saved.read_text(encoding='utf-8'))
    if (config.get('dsh_version') != lock['version'] or
            'dsh_revision' in config and config['dsh_revision'] != pinned_dsh_revision(lock)):
        parser.error(f'Run python benchforge_app.py dsh-setup to build the pinned DSH {lock["version"]} and refresh the presets')
    if not python.is_file():
        parser.error('The BenchForge Python environment is missing; run python benchforge.py setup first')
    upgrading = model_config.is_file() and benchforge_app.settings.read_object(model_config).get(
        'config_version'
    ) != benchforge_app.settings.CONFIG_VERSION
    if not args.config_synced and (upgrading or (preset.is_file() and uses_local_service(preset))):
        run([python, ROOT/'benchforge_app.py', 'sync'], cwd=ROOT)
    env = benchforge_app.build_environment(database=False)
    env['DSH_HOME'] = str(state/'dsh-home')
    paths = [str(ROOT / 'src')]
    if env.get('PYTHONPATH'):
        paths.append(env['PYTHONPATH'])
    env['PYTHONPATH'] = os.pathsep.join(paths)
    try:
        port = args.port if args.port is not None else benchforge_app.configured_web_port()
        workspace = benchforge_app.configured_default_workspace()
    except ValueError as error:
        parser.error(str(error))
    from dsh.presets.build_preset import refresh_model_patches
    from dsh.presets.profile_migration import insert_host_dependencies
    if not args.config_synced or args.check_config:
        refresh_model_patches(preset, model_config, refresh_host=insert_host_dependencies)
    try:
        run([python,ROOT/'src/dsh/check_config.py','--preset',preset],cwd=ROOT,env=env)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    if args.check_config:
        return
    # An overlay and isolated home keep official presets and other installations untouched.
    command = [config['node'], str(Path(config['dsh_root']) / 'apps/cli/lib/bin.js'),
               '--profile', 'web', '--patch', str(preset)]
    if workspace is not None:
        workspace_patch = generated / 'workspace.local.yml'
        benchforge_app.settings.write(workspace_patch, [
            {'id': 'workspace-controller', 'config': {'defaultWorkspace': str(workspace)}},
        ])
        command.extend(['--patch', str(workspace_patch)])
    command.extend(['--host', '127.0.0.1', '--port', str(port)])
    if args.no_open:
        command.append('--no-open')
    run(command,cwd=ROOT,env=env)


if __name__=='__main__':
    main()
