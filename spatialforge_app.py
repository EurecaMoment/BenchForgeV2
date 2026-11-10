#!/usr/bin/env python3
"""Install and run the bundled SpatialForge service and desktop dispatcher."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import tempfile
from urllib.request import Request, urlopen
import venv

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config'
STATE = ROOT / '.deployment'
SERVER = CONFIG / 'spatialforge-server.local.json'
SERVER_TEMPLATE = CONFIG / 'spatialforge-server.example.json'
MODELS_TEMPLATE = CONFIG / 'models.example.json'
WORKER_TEMPLATE = CONFIG / 'worker.example.json'
PYTHON = STATE / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    if os.name != 'nt': path.chmod(0o600)


def read():
    from spatialforge.runtime_config import read_json
    return read_json(SERVER)


def _init_configs(port, db_port):
    from spatialforge.runtime_config import read_json
    SERVER.parent.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    models_path = CONFIG / 'models.local.json'
    policy_dir = CONFIG / 'scene-library'
    policy_path = policy_dir / 'policy.json'
    if not models_path.exists(): write(models_path, read_json(MODELS_TEMPLATE))
    if not policy_path.exists():
        policy_dir.mkdir(parents=True, exist_ok=True)
        write(policy_path, {'enabled': True, 'enforce_realism': True, 'require_scene_brief': True,
                            'excluded_tasks': [], 'excluded_runs': [], 'excluded_scene_groups': [], 'excluded_paths': []})
    if not SERVER.exists():
        config = read_json(SERVER_TEMPLATE)
        config.update(port=port, models_config=models_path.name, scene_policy_path='scene-library/policy.json')
        config.pop('operator_token_env', None)
        config.pop('worker_token_env', None)
        config['operator_token'] = secrets.token_urlsafe(32)
        config['worker_token'] = secrets.token_urlsafe(32)
        write(SERVER, config)
    config = read()
    database_password = secrets.token_urlsafe(24)
    db_env = CONFIG / 'database.env'
    if not db_env.exists():
        database_url = config.get('database_url') or f'postgresql+psycopg://spatialforge:{database_password}@127.0.0.1:{db_port}/spatialforge'
        db_env.write_text(f'POSTGRES_PASSWORD={database_password}\nPOSTGRES_PORT={db_port}\nSPATIALFORGE_DATABASE_URL={database_url}\n', encoding='utf8')
        if os.name != 'nt': db_env.chmod(0o600)
    elif config.get('database_url_env') and not os.environ.get(config['database_url_env']):
        lines = db_env.read_text(encoding='utf8').splitlines()
        if not any(line.partition('=')[0] == config['database_url_env'] for line in lines):
            password = next((line.partition('=')[2] for line in lines if line.startswith('POSTGRES_PASSWORD=')), database_password)
            db_port_value = next((line.partition('=')[2] for line in lines if line.startswith('POSTGRES_PORT=')), str(db_port))
            database_url = f'postgresql+psycopg://spatialforge:{password}@127.0.0.1:{db_port_value}/spatialforge'
            with db_env.open('a', encoding='utf8') as stream:
                stream.write(f'{config["database_url_env"]}={database_url}\n')
    config['execution_mode'] = config.get('execution_mode', 'production')
    write(SERVER, config)
    worker_path = CONFIG / 'worker.local.json'
    if not worker_path.exists():
        worker = read_json(WORKER_TEMPLATE)
        worker.update(service_config=SERVER.name,
                      isaac_root=os.environ.get('ISAAC_SIM_ROOT', worker['isaac_root']),
                      isaac_asset_root=os.environ.get('ISAAC_ASSET_ROOT', worker['isaac_asset_root']),
                      runs='../.deployment/worker-runs')
        write(worker_path, worker)
    client_path = CONFIG / 'spatialforge.local.json'
    if not client_path.exists():
        client = read_json(CONFIG / 'spatialforge.example.json')
        write(client_path, client)


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
    init.add_argument('--port', type=int, default=3841)
    init.add_argument('--db-port', type=int, default=55432)
    db = sub.add_parser('db', help='Start this repository\'s PostgreSQL container')
    db.add_argument('--project', default='benchforgev2-spatialforge')
    sub.add_parser('serve')
    sub.add_parser('status')
    dsh = sub.add_parser('dsh-setup')
    dsh.add_argument('--dsh-root', type=Path)
    start = sub.add_parser('dsh-start')
    start.add_argument('--port', type=int, default=3080)
    start.add_argument('--no-open', action='store_true')
    worker = sub.add_parser('worker')
    worker.add_argument('--config', type=Path, required=True)
    worker.add_argument('--once', action='store_true')
    capture = sub.add_parser('capture')
    capture.add_argument('--program', type=Path, required=True)
    capture.add_argument('--request-key', required=True, help='Reuse this key to resume the same request')
    capture.add_argument('--wait', type=int, default=0, help='Seconds to wait for real capture completion')
    args = p.parse_args()
    if args.command == 'setup':
        if not (3, 11) <= sys.version_info < (3, 14):
            p.error('SpatialForge requires Python 3.11 or 3.12/3.13')
        if not PYTHON.exists():
            venv.EnvBuilder(with_pip=True).create(STATE / 'venv')
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-e', str(ROOT / 'components/benchclaw') + '[postgres,imports]',
                        '-e', str(ROOT / 'components/spatialforge')], check=True)
    elif args.command == 'init':
        _init_configs(args.port, args.db_port)
        print(f'Configuration: {SERVER}; desktop configuration: {CONFIG / "worker.local.json"}')
    elif args.command == 'db':
        subprocess.run(['docker', 'compose', '-p', args.project, '--env-file', str(CONFIG / 'database.env'),
                        '-f', str(ROOT / 'components/spatialforge/deploy/compose.yml'), 'up', '-d', '--wait'], check=True)
    elif args.command == 'serve':
        environment = os.environ.copy()
        env_file = CONFIG / 'database.env'
        if env_file.is_file():
            for line in env_file.read_text(encoding='utf8').splitlines():
                name, separator, value = line.partition('=')
                if separator and name and name not in environment:
                    environment[name] = value
        subprocess.run([str(PYTHON), '-m', 'spatialforge.service', '--config', str(SERVER)],
                       env=environment, check=True)
    elif args.command.startswith('dsh-'):
        command = [sys.executable, str(ROOT / 'benchforge.py'), args.command.removeprefix('dsh-')]
        if args.command == 'dsh-setup':
            command += ['--spatialforge-config', str(CONFIG / 'spatialforge.local.json')]
            if args.dsh_root:
                command += ['--dsh-root', str(args.dsh_root)]
        else:
            command += ['--port', str(args.port), *(['--no-open'] if args.no_open else [])]
        subprocess.run(command, check=True)
    elif args.command == 'worker':
        if os.name != 'nt':
            p.error('The Isaac dispatcher runs on the Windows desktop only')
        subprocess.run([sys.executable, str(ROOT / 'components/spatialforge/desktop/worker.py'),
                        '--config', str(args.config.resolve()), *(['--once'] if args.once else [])], check=True)
    elif args.command == 'status':
        result = api(read(), 'catalog', {})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'capture':
        config = read()
        folder = Path(config['artifacts']) / 'operator_workspaces/cli'
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
