"""HTTP execution on a GPU host with operator-mounted shared storage."""
import argparse
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler


def rpc(url, payload=None, method=None):
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'}, method=method)
    with build_opener(ProxyHandler({})).open(request, timeout=30) as response:
        return json.load(response)


def rewrite_paths(value, replacements):
    """Resolve configured storage locations at the compute endpoint."""
    if isinstance(value, dict):
        return {key: rewrite_paths(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_paths(item, replacements) for item in value]
    if isinstance(value, str):
        for source, destination in replacements.items():
            if value == source or value.startswith(source + '/'):
                return destination + value[len(source):]
    return value


def execute_remote(endpoint, name, request, work, stop):
    endpoint = endpoint.rstrip('/')
    job = rpc(endpoint + '/jobs', {'tool': name, 'request': request, 'work': str(work)})
    url = endpoint + '/jobs/' + job['id']
    while job['status'] in {'queued', 'running'}:
        time.sleep(1)
        if stop.is_set():
            rpc(url, {}, method='DELETE')
            raise RuntimeError('Remote inference canceled; artifacts retained on shared storage')
        job = rpc(url)
    if job['status'] != 'completed':
        raise RuntimeError(job.get('error', 'Remote inference failed'))
    return job['result']


class Jobs:
    def __init__(self, executor):
        self.executor = executor
        self.records = {}
        self.lock = threading.Lock()

    def submit(self, payload):
        job_id = uuid.uuid4().hex
        record = {'id': job_id, 'tool': payload['tool'], 'work': payload['work'],
                  'status': 'queued', 'host': socket.gethostname(), 'submitted': time.time()}
        stop = threading.Event()
        with self.lock:
            self.records[job_id] = (record, stop)
        def run():
            record['status'] = 'running'
            try:
                record['result'] = self.executor(payload['tool'], payload['request'], Path(payload['work']), stop)
                record['status'] = 'completed'
            except Exception as exc:
                record.update(status='canceled' if stop.is_set() else 'failed', error=str(exc))
            finally:
                record['finished'] = time.time()
                Path(payload['work']).mkdir(parents=True, exist_ok=True)
                Path(payload['work'], 'remote_job.json').write_text(json.dumps(record, indent=2), encoding='utf8')
        threading.Thread(target=run, daemon=True).start()
        return dict(record)

    def get(self, job_id):
        with self.lock:
            return dict(self.records[job_id][0])

    def cancel(self, job_id):
        with self.lock:
            self.records[job_id][1].set()
        return self.get(job_id)


def make_server(address, jobs):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/health':
                self.reply({'status': 'ready', 'host': socket.gethostname(),
                            'gpus': os.environ.get('SPATIALFORGE_GPU_CANDIDATES'),
                            'storage': os.environ.get('SPATIALFORGE_STORAGE_MODE', 'shared'),
                            'jobs': len(jobs.records)})
            elif self.path.startswith('/jobs/'):
                try:
                    self.reply(jobs.get(self.path.rsplit('/', 1)[-1]))
                except KeyError:
                    self.reply({'error': 'Unknown job'}, 404)
            else:
                self.reply({'error': 'Unknown endpoint'}, 404)

        def do_POST(self):
            if self.path != '/jobs':
                self.reply({'error': 'Unknown endpoint'}, 404)
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.reply(jobs.submit(payload), 202)
            except (KeyError, ValueError) as exc:
                self.reply({'error': str(exc)}, 400)

        def do_DELETE(self):
            try:
                self.reply(jobs.cancel(self.path.rsplit('/', 1)[-1]))
            except KeyError:
                self.reply({'error': 'Unknown job'}, 404)

    return ThreadingHTTPServer(address, Handler)


class Executor:
    """Launch configured model entrypoints; only the operator selects hardware."""
    def __init__(self, config, gpus):
        self.config = config
        self.gpus = gpus.split(',')
        self.condition = threading.Condition()
        self.busy = set()

    def __call__(self, name, request, work, stop):
        spec = self.config['tools'][name]
        with self.condition:
            while True:
                if stop.is_set():
                    raise RuntimeError('Canceled before GPU assignment')
                query = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.free', '--format=csv,noheader,nounits'], text=True)
                free = {index.strip(): int(memory) for index, memory in (line.split(',') for line in query.splitlines())}
                available = [gpu for gpu in self.gpus if gpu not in self.busy and free[gpu] >= spec.get('minimum_mib', 0)]
                if available:
                    gpu = available[0]
                    self.busy.add(gpu)
                    break
                self.condition.wait(2)
        try:
            work.mkdir(parents=True, exist_ok=True)
            request_path, response_path = work/'request.json', work/'response.json'
            request = rewrite_paths(request, self.config.get('path_rewrites', {}))
            request_path.write_text(json.dumps(request), encoding='utf8')
            env = {**os.environ, **self.config.get('environment', {}), **spec.get('environment', {}), 'CUDA_VISIBLE_DEVICES': gpu,
                   'PYTHONDONTWRITEBYTECODE': '1', 'CUDA_CACHE_DISABLE': '1',
                   'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONUNBUFFERED': '1'}
            command = [spec['python'], '-m', spec['module'], '--request', str(request_path), '--response', str(response_path)]
            execution = {'host': socket.gethostname(), 'gpu': gpu, 'tool': name, 'started': time.time(), 'command': command}
            (work/'execution.json').write_text(json.dumps(execution), encoding='utf8')
            with (work/'worker.log').open('a') as log:
                process = subprocess.Popen(command, cwd=self.config['project'], env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                execution['pid'] = process.pid
                (work/'execution.json').write_text(json.dumps(execution), encoding='utf8')
                while process.poll() is None:
                    if stop.wait(1):
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        raise RuntimeError('Inference canceled')
            execution.update(finished=time.time(), exit_code=process.returncode)
            (work/'execution.json').write_text(json.dumps(execution), encoding='utf8')
            if process.returncode:
                raise RuntimeError(f'{name} failed; see {work}/worker.log')
            result = json.loads(response_path.read_text(encoding='utf8'))
            if result.get('status') != 'ok':
                raise RuntimeError(str(result))
            return result
        finally:
            with self.condition:
                self.busy.remove(gpu)
                self.condition.notify_all()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3951)
    parser.add_argument('--config', required=True)
    parser.add_argument('--gpus', required=True)
    args = parser.parse_args()
    # The GPU host is the execution endpoint, never a forwarding client.
    os.environ.pop('SPATIALFORGE_INFERENCE_URL', None)
    os.environ['SPATIALFORGE_GPU_CANDIDATES'] = args.gpus
    config = json.loads(Path(args.config).read_text(encoding='utf8'))
    os.environ['SPATIALFORGE_STORAGE_MODE'] = ('local-models-shared-code-output'
        if config.get('path_rewrites') else 'shared')
    executor = Executor(config, args.gpus)
    server = make_server((args.host, args.port), Jobs(executor))
    print(json.dumps({'listening': server.server_address, 'host': socket.gethostname(), 'gpus': args.gpus}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
