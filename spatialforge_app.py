#!/usr/bin/env python3
"""Install and run the bundled SpatialForge service and desktop dispatcher."""
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
from urllib.request import Request, urlopen
import venv

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config'
STATE = ROOT / '.spatialforge'
GENERATED = CONFIG / 'generated'
SERVER = GENERATED / 'spatialforge-server.local.json'
PORTS = CONFIG / 'ports.env'
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


def sync_ports():
    """Apply config/ports.env to every generated config; tokens/passwords are preserved."""
    ports = read_ports()
    service_port = int(ports.get('SPATIALFORGE_PORT', 3857))
    db_port = int(ports.get('POSTGRES_PORT', 55547))
    if not SERVER.exists():
        raise SystemExit(f'缺少 {SERVER}，请先运行 init')
    benchforge_path = ROOT / 'config' / 'benchforge.local.json'
    benchforge = json.loads(benchforge_path.read_text(encoding='utf8')) if benchforge_path.exists() else {}
    config = read()
    config['port'] = service_port
    config['database_url'] = re.sub(r'@([^:/]+):\d+/',
                                    lambda m: f'@{m.group(1)}:{db_port}/',
                                    config['database_url'])
    write(SERVER, config)
    client = GENERATED / 'spatialforge.local.json'
    if client.exists():
        value = json.loads(client.read_text(encoding='utf8'))
        value['service_url'] = f'http://127.0.0.1:{service_port}'
        write(client, value)
    worker = GENERATED / 'worker.local.json'
    if worker.exists():
        value = json.loads(worker.read_text(encoding='utf8'))
        value['url'] = f'http://127.0.0.1:{service_port}'
        value['ssh_forward'] = f'{service_port}:127.0.0.1:{service_port}'
        # 统一 Isaac 入口：把 benchforge.local.json 的 isaac 区块同步到 worker.local.json
        # 同步字段：grpc/isaac_asset_root/runs/capture_timeout_seconds（gRPC 远程调用，本地/SSH/HTTP-RPC 模式已删除）
        # 不覆盖 worker 专属字段：worker_token/worker_id/ssh_host/ssh_forward/url
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
    password = None
    env = GENERATED / 'database.env'
    if env.exists():
        for line in env.read_text(encoding='utf8').splitlines():
            if line.startswith('POSTGRES_PASSWORD='):
                password = line.split('=', 1)[1]
    if password is None:
        password = re.search(r'//spatialforge:([^@]+)@', config['database_url']).group(1)
    env.write_text(f'POSTGRES_PASSWORD={password}\nPOSTGRES_PORT={db_port}\n', encoding='utf8')
    if os.name != 'nt':
        env.chmod(0o600)
    print(f'ports.env 已同步: service={service_port} postgres={db_port}')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    if os.name != 'nt':
        path.chmod(0o600)


def read():
    return json.loads(SERVER.read_text(encoding='utf8'))


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
    db = sub.add_parser('db', help='Start this repository\'s PostgreSQL container')
    db.add_argument('--project', default='benchforgev2-spatialforge')
    sub.add_parser('serve')
    sub.add_parser('status')
    sub.add_parser('sync', help='Apply config/ports.env to all generated configs')
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
        if SERVER.exists():
            print(f'Existing configuration retained: {SERVER}')
            return
        password = secrets.token_urlsafe(24)
        config = dict(port=args.port, artifacts=str(STATE / 'artifacts'),
                      harness=str(ROOT / 'components/benchclaw'),
                      database_url=f'postgresql+psycopg://spatialforge:{password}@127.0.0.1:{args.db_port}/spatialforge',
                      operator_token=secrets.token_urlsafe(32), worker_token=secrets.token_urlsafe(32),
                      models_config=str(GENERATED / 'models.local.json'), gpu_candidates='0',
                      task_root=str(STATE / 'artifacts/operator_workspaces'))
        write(SERVER, config)
        env = GENERATED / 'database.env'
        env.write_text(f'POSTGRES_PASSWORD={password}\nPOSTGRES_PORT={args.db_port}\n', encoding='utf8')
        if os.name != 'nt':
            env.chmod(0o600)
        write(GENERATED / 'spatialforge.local.json', {'service_url': f'http://127.0.0.1:{args.port}',
                                               'operator_token': config['operator_token']})
        shutil.copy2(CONFIG / 'models.example.json', GENERATED / 'models.local.json')
        worker = json.loads((CONFIG / 'worker.example.json').read_text())
        worker['worker_token'] = config['worker_token']
        worker['url'] = f'http://127.0.0.1:{args.port}'
        worker['ssh_forward'] = f'{args.port}:127.0.0.1:{args.port}'
        write(GENERATED / 'worker.local.json', worker)
        print(f'Configuration: {SERVER}; desktop configuration: {GENERATED / "worker.local.json"}')
    elif args.command == 'db':
        subprocess.run(['docker', 'compose', '-p', args.project, '--env-file', str(GENERATED / 'database.env'),
                        '-f', str(ROOT / 'components/spatialforge/deploy/compose.yml'), 'up', '-d', '--wait'], check=True)
    elif args.command == 'serve':
        subprocess.run([str(PYTHON), '-m', 'spatialforge.service', '--config', str(SERVER)], check=True)
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
