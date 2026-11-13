#!/usr/bin/env python3
"""Install and run the bundled BenchForgeV2 service and desktop dispatcher."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import venv

ROOT = Path(__file__).resolve().parent
# This repository launcher also runs outside the private backend environment.
sys.path.insert(0, str(ROOT / 'components/spatialforge/src'))
sys.path.insert(0, str(ROOT))
import deployment_config as settings
from spatialforge.runtime_config import load_service_config

CONFIG = ROOT / 'config'
STATE = ROOT / '.spatialforge'
GENERATED = CONFIG / 'generated'
SERVER = GENERATED / 'spatialforge-server.local.json'
PYTHON = STATE / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')


write = settings.write


def build_environment(*, database=True):
    environment = settings.read_env(CONFIG / 'dsh.env', shell=True)
    projected = settings.read_env(GENERATED / 'database.env') if database else {}
    environment = {**environment, **projected, **os.environ}
    if projected.get(settings.MANAGED_MARKER) == 'true':
        # Compose and both server-side readers must address the same managed DB.
        for key in (settings.MANAGED_URL, 'POSTGRES_PASSWORD', 'POSTGRES_PORT'):
            environment[key] = projected[key]
    return environment


def _configuration():
    return settings.read_configuration(CONFIG, GENERATED, SERVER)[0]


def configured_web_port():
    value = os.environ.get('BENCHFORGE_WEB_PORT')
    return settings.port(value if value is not None else _configuration()['web']['port'],
                         'web.port')


def database_is_managed():
    return settings.database_is_managed(_configuration()['database'])


def sync_configuration(*, overrides=None):
    return settings.sync_configuration(CONFIG, GENERATED, SERVER, STATE, overrides=overrides)


def _init_configs(port=None, db_port=None, project=None, *, web_port=None):
    requested = {
        'web': {'port': web_port},
        'server': {'port': port},
        'database': {'port': db_port, 'project': project},
    }
    overrides = {section: {key: value for key, value in fields.items() if value is not None}
                 for section, fields in requested.items()}
    sync_configuration(overrides=overrides)


def _setting(name):
    readers = {
        'web.port': configured_web_port,
        'server.port': lambda: _configuration()['server']['port'],
        'database.managed': lambda: 'true' if database_is_managed() else 'false',
        'database.project': lambda: _configuration()['database']['project'],
    }
    return readers[name]()


def _database_command(project, stop):
    env_file = GENERATED / 'database.env'
    if not stop and not env_file.is_file():
        sync_configuration()
    projected = settings.read_env(env_file)
    managed = projected and projected.get(settings.MANAGED_MARKER) != 'false'
    if not managed and not (stop and project):
        return
    name = settings.compose_name(project or projected.get(
        'COMPOSE_PROJECT_NAME', 'benchforgev2-spatialforge'
    ))
    environment = build_environment(database=False)
    environment.update(projected)
    # Pass the literal projected values as process environment so Compose
    # preserves characters in passwords and skips unrelated dotenv files.
    environment['COMPOSE_DISABLE_ENV_FILE'] = '1'
    if stop:
        # Compose expands its required service environment even for down. The
        # running containers and volumes do not use this interpolation value.
        environment.setdefault('POSTGRES_PASSWORD', 'unused-for-container-stop')
    command = ['docker', 'compose', '-p', name, '-f',
               str(ROOT / 'components/spatialforge/deploy/compose.yml')]
    command += ['down'] if stop else ['up', '-d', '--wait']
    subprocess.run(command, env=environment, check=True)


def _read_runtime_server():
    if not SERVER.is_file():
        sync_configuration()
    # Reuse the backend's env/token/policy resolution without changing the
    # launcher's process environment or passing stale legacy values.
    env = build_environment()
    original = os.environ.copy()
    try:
        os.environ.update(env)
        return load_service_config(SERVER, required_tokens=('operator',))
    finally:
        os.environ.clear()
        os.environ.update(original)


def api(config, operation, value):
    request = Request(f'http://127.0.0.1:{config["port"]}/{operation}',
                      data=json.dumps(value).encode(),
                      headers={'Authorization': 'Bearer ' + config['operator_token'],
                               'Content-Type': 'application/json'})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('setup', help='Install bundled server dependencies in a private Python venv')
    init = sub.add_parser('init', help='Create private config and credentials once')
    init.add_argument('--port', type=int)
    init.add_argument('--web-port', type=int)
    init.add_argument('--db-port', type=int)
    init.add_argument('--project', help='Unique database project name for this installation')
    db = sub.add_parser('db', help='Start or stop the managed PostgreSQL container')
    db.add_argument('--project', help='Use a specific Compose project')
    db.add_argument('--stop', action='store_true')
    sub.add_parser('serve')
    sub.add_parser('status')
    sub.add_parser('sync', help='Generate runtime files from config/benchforge.local.json')
    setting = sub.add_parser('setting', help='Print one non-secret launch setting')
    setting.add_argument('name', choices=('web.port', 'server.port', 'database.managed', 'database.project'))
    dsh = sub.add_parser('dsh-setup')
    dsh.add_argument('--dsh-root', type=Path)
    start = sub.add_parser('dsh-start')
    start.add_argument('--port', type=int)
    start.add_argument('--no-open', action='store_true')
    worker = sub.add_parser('worker')
    worker.add_argument('--config', type=Path)
    worker.add_argument('--once', action='store_true')
    capture = sub.add_parser('capture')
    capture.add_argument('--program', type=Path, required=True)
    capture.add_argument('--request-key', required=True, help='Reuse this key to resume the same request')
    capture.add_argument('--wait', type=int, default=0, help='Seconds to wait for real capture completion')
    args = p.parse_args()
    if args.command == 'setup':
        if not (3, 11) <= sys.version_info < (3, 14):
            p.error('BenchForgeV2 requires Python 3.11 or 3.12/3.13')
        if not PYTHON.exists():
            venv.EnvBuilder(with_pip=True).create(STATE / 'venv')
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-e', str(ROOT / 'components/spatialforge')], check=True)
    elif args.command == 'init':
        _init_configs(args.port, args.db_port, args.project, web_port=args.web_port)
        print(f"Configuration: {CONFIG / 'benchforge.local.json'}")
    elif args.command == 'db':
        _database_command(args.project, args.stop)
    elif args.command == 'serve':
        if not SERVER.is_file():
            sync_configuration()
        subprocess.run([str(PYTHON), '-m', 'spatialforge.service', '--config', str(SERVER)],
                       env=build_environment(), check=True)
    elif args.command.startswith('dsh-'):
        command = [sys.executable, str(ROOT / 'benchforge.py'), args.command.removeprefix('dsh-')]
        if args.command == 'dsh-setup':
            sync_configuration()
            command += ['--spatialforge-config', str(GENERATED / 'spatialforge.local.json')]
            if args.dsh_root:
                command += ['--dsh-root', str(args.dsh_root)]
        else:
            if args.port is not None:
                command += ['--port', str(args.port)]
            if args.no_open:
                command.append('--no-open')
        subprocess.run(command, check=True)
    elif args.command == 'worker':
        if os.name != 'nt':
            p.error('The Isaac dispatcher runs on the Windows desktop only')
        profile = args.config or GENERATED / 'worker.local.json'
        if args.config is None and not profile.is_file():
            sync_configuration()
        command = [sys.executable, str(ROOT / 'components/spatialforge/desktop/worker.py'),
                   '--config', str(profile.resolve())]
        if args.once:
            command.append('--once')
        subprocess.run(command, env=build_environment(database=False), check=True)
    elif args.command == 'sync':
        sync_configuration()
    elif args.command == 'setting':
        print(_setting(args.name))
    elif args.command == 'status':
        result = api(_read_runtime_server(), 'catalog', {})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'capture':
        config = _read_runtime_server()
        task_root = config.get('task_root') or Path(config['artifacts']) / 'operator_workspaces'
        folder = Path(task_root) / 'cli'
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / args.program.name
        shutil.copyfile(args.program, dest)
        result = api(config, 'capture', {'request_key': args.request_key, 'scene_program_path': str(dest)})
        print(json.dumps(result), flush=True)
        until = time.monotonic() + args.wait
        while time.monotonic() < until:
            status = api(config, 'observe', {'run_id': result['run_id']})
            if status['state'] in ('SUCCEEDED', 'FAILED_FINAL', 'CANCELED'):
                print(json.dumps(status, ensure_ascii=False, indent=2))
                if status['state'] != 'SUCCEEDED':
                    raise SystemExit(1)
                return
            time.sleep(5)
        if args.wait:
            print('Capture remains in progress. Reuse the request key; retain this run ID.')
            raise SystemExit(2)


if __name__ == '__main__':
    main()
