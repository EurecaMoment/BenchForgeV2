#!/usr/bin/env python3
"""Install and run the bundled BenchForgeV2 service and desktop dispatcher."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import tempfile
from urllib.request import Request, urlopen
import venv

ROOT = Path(__file__).resolve().parent
# This repository launcher also runs outside the private backend environment.
# Reuse its configuration parser directly from the bundled source.
sys.path.insert(0, str(ROOT / 'components/spatialforge/src'))
from spatialforge.runtime_config import read_json
from spatialforge.model_configuration import initialize_model_config

CONFIG = ROOT / 'config'
STATE = ROOT / '.spatialforge'
GENERATED = CONFIG / 'generated'
SERVER = GENERATED / 'spatialforge-server.local.json'
PORTS = CONFIG / 'ports.env'
SERVER_TEMPLATE = CONFIG / 'spatialforge-server.example.json'
WORKER_TEMPLATE = CONFIG / 'worker.example.json'
PYTHON = STATE / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')


def read_ports():
    ports = {}
    if PORTS.exists():
        for line in PORTS.read_text(encoding='utf8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                ports[key.strip()] = value.strip()
    return ports


def _rewrite_database_port(url, db_port):
    return re.sub(r'@([^:/]+):\d+/', lambda match: f'@{match.group(1)}:{db_port}/', url)


def sync_ports():
    """Apply config/ports.env to every generated config; tokens/passwords are preserved."""
    sync_model_config()
    ports = read_ports()
    if not SERVER.exists():
        raise SystemExit(f'缺少 {SERVER}，请先运行 init')
    service_port = int(ports['SPATIALFORGE_PORT']) if 'SPATIALFORGE_PORT' in ports else None
    db_port = int(ports['POSTGRES_PORT']) if 'POSTGRES_PORT' in ports else None
    config = read()
    if service_port is not None:
        config['port'] = service_port
    if db_port is not None and isinstance(config.get('database_url'), str):
        config['database_url'] = _rewrite_database_port(config['database_url'], db_port)
    write(SERVER, config)
    harness = config.get('harness')
    if isinstance(harness, str) and harness and config.get('database_url'):
        # 工作台 python 读取器从 <harness>/deployment.local.json 取数据库地址
        write(Path(harness, 'deployment.local.json'), {'database_url': config['database_url']})
    client = GENERATED / 'spatialforge.local.json'
    if client.exists() and service_port is not None:
        value = json.loads(client.read_text(encoding='utf8'))
        if 'service_url' in value:
            value['service_url'] = f'http://127.0.0.1:{service_port}'
            write(client, value)
    worker = GENERATED / 'worker.local.json'
    if worker.exists():
        value = json.loads(worker.read_text(encoding='utf8'))
        if service_port is not None and 'url' in value:
            value['url'] = f'http://127.0.0.1:{service_port}'
            value['ssh_forward'] = f'{service_port}:127.0.0.1:{service_port}'
        # 统一 Isaac 入口：把 benchforge.local.json 的 isaac 区块同步到 worker.local.json
        # 同步字段：grpc/isaac_asset_root/runs/capture_timeout_seconds（gRPC 远程调用，本地/SSH/HTTP-RPC 模式已删除）
        # 不覆盖 worker 专属字段：worker_token/worker_id/ssh_host/ssh_forward/url
        benchforge_path = CONFIG / 'benchforge.local.json'
        benchforge = json.loads(benchforge_path.read_text(encoding='utf8')) if benchforge_path.exists() else {}
        isaac_cfg = benchforge.get('isaac') or {}
        isaac_passthrough_keys = [
            ('grpc', 'isaac_grpc'), ('isaac_asset_root', 'isaac_asset_root'),
            ('runs', 'runs'), ('capture_timeout_seconds', 'capture_timeout_seconds'),
        ]
        for src_key, dst_key in isaac_passthrough_keys:
            if src_key in isaac_cfg:
                value[dst_key] = isaac_cfg[src_key]
        # 清除旧三模式（local/remote/rpc）遗留的 key，避免 worker 误读死配置
        for stale_key in ('isaac_mode', 'isaac_root', 'isaac_python', 'isaac_remote',
                          'isaac_rpc', 'isaac_resident', 'isaac_idle_seconds'):
            value.pop(stale_key, None)
        write(worker, value)
    env = GENERATED / 'database.env'
    values = {}
    if env.exists():
        for line in env.read_text(encoding='utf8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key:
                values[key] = value
    if 'POSTGRES_PASSWORD' not in values:
        match = re.search(r'//spatialforge:([^@]+)@', config.get('database_url') or '')
        if not match:
            raise SystemExit(f'{env} 缺少 POSTGRES_PASSWORD，且服务端配置没有内嵌数据库密码')
        values['POSTGRES_PASSWORD'] = match.group(1)
    if db_port is not None:
        values['POSTGRES_PORT'] = str(db_port)
        if 'SPATIALFORGE_DATABASE_URL' in values:
            values['SPATIALFORGE_DATABASE_URL'] = _rewrite_database_port(
                values['SPATIALFORGE_DATABASE_URL'], db_port)
    env.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf8')
    if os.name != 'nt':
        env.chmod(0o600)
    print(f'ports.env 已同步: service={service_port} postgres={db_port}')


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
    return read_json(SERVER)


def compose_project(env_file, default='benchforgev2-spatialforge'):
    """Read the database project name saved by init, falling back to the legacy default."""
    if env_file.exists():
        for line in env_file.read_text(encoding='utf8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key == 'COMPOSE_PROJECT_NAME' and value:
                return value
    return default


def sync_model_config():
    """Keep model declarations in config/benchforge.local.json only."""
    if not SERVER.is_file():
        raise SystemExit(f'缺少 {SERVER}，请先运行 init')
    config = read()
    path = CONFIG / 'benchforge.local.json'
    initialize_model_config(path, CONFIG / 'benchforge.example.json', SERVER, config, write)
    reference = Path(os.path.relpath(path, SERVER.parent)).as_posix()
    changed = config.get('models_config') != reference
    config['models_config'] = reference
    for key in ('model_url', 'model_id', 'model_api_key_env'):
        changed = key in config or changed
        config.pop(key, None)
    if changed:
        write(SERVER, config)


def _init_configs(port, db_port, project='benchforgev2-spatialforge'):
    existing_server = SERVER.exists()
    SERVER.parent.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    policy_dir = SERVER.parent / 'scene-library'
    policy_path = policy_dir / 'policy.json'
    if not policy_path.exists():
        policy_dir.mkdir(parents=True, exist_ok=True)
        write(policy_path, {'enabled': True, 'enforce_realism': True, 'require_scene_brief': True,
                            'excluded_tasks': [], 'excluded_runs': [], 'excluded_scene_groups': [], 'excluded_paths': []})
    if not existing_server:
        config = read_json(SERVER_TEMPLATE)
        config.update(port=port, artifacts=str(STATE / 'artifacts'),
                      task_root=str(STATE / 'artifacts/operator_workspaces'),
                      models_config=Path(os.path.relpath(CONFIG / 'benchforge.local.json', SERVER.parent)).as_posix(),
                      scene_policy_path='scene-library/policy.json')
        config.pop('operator_token_env', None)
        config.pop('worker_token_env', None)
        config['operator_token'] = secrets.token_urlsafe(32)
        config['worker_token'] = secrets.token_urlsafe(32)
        write(SERVER, config)
    sync_model_config()
    config = read()
    database_password = secrets.token_urlsafe(24)
    db_env = SERVER.parent / 'database.env'
    if not db_env.exists() and not existing_server:
        database_url = config.get('database_url') or f'postgresql+psycopg://spatialforge:{database_password}@127.0.0.1:{db_port}/spatialforge'
        db_env.write_text(f'POSTGRES_PASSWORD={database_password}\nPOSTGRES_PORT={db_port}\n'
                          f'COMPOSE_PROJECT_NAME={project}\nSPATIALFORGE_DATABASE_URL={database_url}\n', encoding='utf8')
        if os.name != 'nt': db_env.chmod(0o600)
    elif db_env.exists() and config.get('database_url_env') and not os.environ.get(config['database_url_env']):
        lines = db_env.read_text(encoding='utf8').splitlines()
        if not any(line.partition('=')[0] == config['database_url_env'] for line in lines):
            password = next((line.partition('=')[2] for line in lines if line.startswith('POSTGRES_PASSWORD=')), database_password)
            db_port_value = next((line.partition('=')[2] for line in lines if line.startswith('POSTGRES_PORT=')), str(db_port))
            database_url = f'postgresql+psycopg://spatialforge:{password}@127.0.0.1:{db_port_value}/spatialforge'
            with db_env.open('a', encoding='utf8') as stream:
                stream.write(f'{config["database_url_env"]}={database_url}\n')
    worker_path = SERVER.parent / 'worker.local.json'
    if not worker_path.exists():
        worker = read_json(WORKER_TEMPLATE)
        worker.update(service_config=SERVER.name,
                      isaac_asset_root=os.environ.get('ISAAC_ASSET_ROOT', worker.get('isaac_asset_root', '')))
        worker.setdefault('runs', str(STATE / 'worker-runs'))
        write(worker_path, worker)
    client_path = SERVER.parent / 'spatialforge.local.json'
    if not client_path.exists():
        client = read_json(CONFIG / 'spatialforge.example.json')
        client['service_config'] = SERVER.name
        write(client_path, client)


def api(config, operation, value):
    request = Request(f'http://127.0.0.1:{config["port"]}/{operation}',
                      data=json.dumps(value).encode(),
                      headers={'Authorization': 'Bearer ' + config['operator_token'],
                               'Content-Type': 'application/json'})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    GENERATED.mkdir(parents=True, exist_ok=True)
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('setup', help='Install bundled server dependencies in a private Python venv')
    init = sub.add_parser('init', help='Create private config and credentials once')
    init.add_argument('--port', type=int, default=3841)
    init.add_argument('--db-port', type=int, default=55432)
    init.add_argument('--project', default='benchforgev2-spatialforge',
                      help='Unique database project name, saved in config/generated/database.env')
    db = sub.add_parser('db', help='Start this repository\'s PostgreSQL container')
    db.add_argument('--project', help='Override the project saved in config/generated/database.env')
    sub.add_parser('serve')
    sub.add_parser('status')
    sub.add_parser('sync', help='Sync the unified model registry and config/ports.env')
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
            p.error('BenchForgeV2 requires Python 3.11 or 3.12/3.13')
        if not PYTHON.exists():
            venv.EnvBuilder(with_pip=True).create(STATE / 'venv')
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-e', str(ROOT / 'components/benchclaw') + '[postgres,imports]',
                        '-e', str(ROOT / 'components/spatialforge')], check=True)
    elif args.command == 'init':
        _init_configs(args.port, args.db_port, args.project)
        print(f'Configuration: {SERVER}; desktop configuration: {SERVER.parent / "worker.local.json"}')
    elif args.command == 'db':
        env_file = GENERATED / 'database.env'
        project = args.project or compose_project(env_file)
        subprocess.run(['docker', 'compose', '-p', project, '--env-file', str(env_file),
                        '-f', str(ROOT / 'components/spatialforge/deploy/compose.yml'), 'up', '-d', '--wait'], check=True)
    elif args.command == 'serve':
        environment = os.environ.copy()
        for env_file in (GENERATED / 'database.env', CONFIG / 'dsh.env'):
            if env_file.is_file():
                for line in env_file.read_text(encoding='utf8').splitlines():
                    name, separator, value = line.partition('=')
                    if separator and name and not name.startswith('#') and name not in environment:
                        environment[name] = value
        subprocess.run([str(PYTHON), '-m', 'spatialforge.service', '--config', str(SERVER)],
                       env=environment, check=True)
    elif args.command.startswith('dsh-'):
        command = [sys.executable, str(ROOT / 'benchforge.py'), args.command.removeprefix('dsh-')]
        if args.command == 'dsh-setup':
            command += ['--spatialforge-config', str(GENERATED / 'spatialforge.local.json')]
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
    elif args.command == 'sync':
        sync_ports()
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
