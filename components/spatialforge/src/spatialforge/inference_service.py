"""HTTP execution on a GPU host with operator-mounted shared storage."""
import argparse
import ipaddress
import json
import hmac
import os
from pathlib import Path
import socket
import signal
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal, TypedDict
from urllib.request import Request, build_opener, ProxyHandler


def rpc(url, payload=None, method=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                      headers=headers, method=method)
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
    token = os.environ.get(os.environ.get('SPATIALFORGE_INFERENCE_TOKEN_ENV',
                                         'SPATIALFORGE_INFERENCE_TOKEN'))
    job = rpc(endpoint + '/jobs', {'tool': name, 'request': request, 'work': str(work)}, token=token)
    url = endpoint + '/jobs/' + job['id']
    while job['status'] in {'queued', 'running'}:
        time.sleep(1)
        if stop.is_set():
            rpc(url, {}, method='DELETE', token=token)
            raise RuntimeError('Remote inference canceled; artifacts retained on shared storage')
        job = rpc(url, token=token)
    if job['status'] != 'completed':
        raise RuntimeError(job.get('error', 'Remote inference failed'))
    return job['result']


class InferenceSubmission(TypedDict):
    tool: str
    request: dict[str, Any]
    work: str


class InferenceJobRecord(TypedDict, total=False):
    id: str
    tool: str
    work: str
    status: Literal['queued', 'running', 'completed', 'failed', 'canceled']
    host: str
    submitted: float
    finished: float
    result: dict[str, Any]
    error: str


class Jobs:
    def __init__(self, executor, *, work_root=None, state_path=None, max_active=32, max_history=256):
        self.executor = executor
        self.records: dict[str, InferenceJobRecord] = {}
        self.stops: dict[str, threading.Event] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()
        self.shutting_down = False
        executor_config = getattr(executor, 'config', {})
        default_root = executor_config.get('work_root', executor_config.get('project', Path.cwd()))
        self.work_root = Path(work_root or default_root).resolve()
        self.state_path = Path(state_path).resolve() if state_path else None
        self.max_active = max_active
        self.max_history = max_history
        self._restore()

    def _save(self):
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(list(self.records.values()), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _restore(self):
        if self.state_path is None or not self.state_path.is_file():
            return
        try:
            stored = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f'Cannot restore inference job registry: {self.state_path}') from exc
        if not isinstance(stored, list):
            raise RuntimeError(f'Invalid inference job registry: {self.state_path}')
        for record in stored[-self.max_history:]:
            if not isinstance(record, dict) or not isinstance(record.get('id'), str):
                continue
            if record.get('status') in {'queued', 'running'}:
                record.update(status='failed', error='Inference service restarted before the job completed',
                              finished=time.time())
            self.records[record['id']] = record
        self._save()

    def _work_directory(self, value):
        if not isinstance(value, str) or not value:
            raise ValueError('work must be a nonempty path')
        work = Path(value).resolve()
        try:
            work.relative_to(self.work_root)
        except ValueError as exc:
            raise ValueError('work must stay inside the configured inference work root') from exc
        if work == self.work_root:
            raise ValueError('work must name a job subdirectory below the configured work root')
        return work

    def _trim_history(self):
        if len(self.records) <= self.max_history:
            return
        terminal = sorted(
            (record for record in self.records.values() if record['status'] not in {'queued', 'running'}),
            key=lambda record: record.get('submitted', 0),
        )
        for record in terminal[:max(0, len(self.records) - self.max_history)]:
            self.records.pop(record['id'], None)
            self.stops.pop(record['id'], None)

    def submit(self, payload: InferenceSubmission) -> InferenceJobRecord:
        if not isinstance(payload, dict):
            raise ValueError('Request body must be an object')
        configured_tools = getattr(self.executor, 'config', {}).get('tools')
        if (not isinstance(payload.get('tool'), str) or
                (configured_tools is not None and payload['tool'] not in configured_tools)):
            raise ValueError('tool must name a configured inference operation')
        if not isinstance(payload.get('request'), dict):
            raise ValueError('request must be an object')
        work = self._work_directory(payload.get('work'))
        payload = {**payload, 'work': str(work)}
        job_id = uuid.uuid4().hex
        record: InferenceJobRecord = {
            'id': job_id,
            'tool': payload['tool'],
            'work': payload['work'],
            'status': 'queued',
            'host': socket.gethostname(),
            'submitted': time.time(),
        }
        stop = threading.Event()
        with self.lock:
            if self.shutting_down:
                raise RuntimeError('Inference service is shutting down; retry after it restarts')
            active = sum(record['status'] in {'queued', 'running'} for record in self.records.values())
            if active >= self.max_active:
                raise RuntimeError('Inference queue is full; retry after active jobs finish')
            if any(item['work'] == payload['work'] and item['status'] in {'queued', 'running'}
                   for item in self.records.values()):
                raise ValueError('An active inference job already owns this work directory')
            self.records[job_id] = record
            self.stops[job_id] = stop
            self._trim_history()
            self._save()
        try:
            work.mkdir(parents=True, exist_ok=True)
            if work.resolve() != work:
                raise ValueError('work directory cannot resolve through a symbolic link')
            self._write_work_record(work, record)
        except (OSError, ValueError) as exc:
            with self.lock:
                record.update(status='failed', error=f'Could not prepare job directory: {exc}',
                              finished=time.time())
                self._save()
                snapshot = dict(record)
            if work.is_dir():
                self._write_work_record(work, snapshot)
            raise
        def run():
            with self.lock:
                record['status'] = 'running'
                self._save()
            try:
                result = self.executor(payload['tool'], payload['request'], Path(payload['work']), stop)
                with self.lock:
                    record['result'] = result
                status = 'completed'
            except Exception as exc:
                status = 'canceled' if stop.is_set() else 'failed'
                error = str(exc)
            finally:
                record['finished'] = time.time()
                with self.lock:
                    if 'status' not in locals():
                        status = 'failed'
                        error = 'Inference worker exited unexpectedly'
                    record['status'] = status
                    if status == 'failed' or status == 'canceled':
                        record['error'] = error
                    self._trim_history()
                    self._save()
                    snapshot = dict(record)
                try:
                    self._write_work_record(work, snapshot)
                finally:
                    with self.lock:
                        self.threads.pop(job_id, None)

        thread = threading.Thread(target=run, name='spatialforge-inference-' + job_id, daemon=True)
        with self.lock:
            if self.shutting_down or stop.is_set() or record['status'] != 'queued':
                if record['status'] == 'queued':
                    record.update(
                        status='canceled' if stop.is_set() else 'failed',
                        error='Inference service shut down before the worker started',
                        finished=time.time(),
                    )
                    self._save()
                snapshot = dict(record)
                start_worker = False
            else:
                self.threads[job_id] = thread
                try:
                    thread.start()
                    start_worker = True
                except RuntimeError as exc:
                    self.threads.pop(job_id, None)
                    record.update(status='failed', error=f'Could not start inference worker: {exc}',
                                  finished=time.time())
                    self._save()
                    snapshot = dict(record)
                    start_worker = False
        if not start_worker:
            self._write_work_record(work, snapshot)
            if snapshot['status'] == 'queued':
                raise RuntimeError('Inference service is shutting down; job was not started')
            if snapshot['status'] == 'failed' and snapshot.get('error', '').startswith('Could not start'):
                raise RuntimeError(snapshot['error'])
            raise RuntimeError(snapshot.get('error', 'Inference job was not started'))
        return dict(record)

    def shutdown(self, timeout_seconds: float = 30) -> None:
        """Cancel owned work and persist the outcome before the service exits."""
        with self.lock:
            self.shutting_down = True
            active_ids = [
                job_id for job_id, record in self.records.items()
                if record['status'] in {'queued', 'running'}
            ]
            for job_id in active_ids:
                stop = self.stops.get(job_id)
                if stop is not None:
                    stop.set()
            threads = [self.threads[job_id] for job_id in active_ids if job_id in self.threads]
            for job_id in active_ids:
                if job_id not in self.threads:
                    self.records[job_id].update(
                        status='failed',
                        error='Inference service shut down before the worker started',
                        finished=time.time(),
                    )
            self._save()

        deadline = time.monotonic() + timeout_seconds
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))

        with self.lock:
            now = time.time()
            for job_id in active_ids:
                record = self.records.get(job_id)
                if record and record['status'] in {'queued', 'running'}:
                    record.update(
                        status='failed',
                        error='Inference service shutdown exceeded its cancellation deadline',
                        finished=now,
                    )
            self._trim_history()
            self._save()
            snapshots = [dict(self.records[job_id]) for job_id in active_ids if job_id in self.records]
        for record in snapshots:
            work = Path(record['work'])
            if work.is_dir():
                self._write_work_record(work, record)

    @staticmethod
    def _write_work_record(work, record):
        temporary = work / ('remote_job.json.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, work / 'remote_job.json')
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, job_id: str) -> InferenceJobRecord:
        with self.lock:
            return dict(self.records[job_id])

    def cancel(self, job_id: str) -> InferenceJobRecord:
        with self.lock:
            stop = self.stops.get(job_id)
            if stop is not None:
                stop.set()
            return dict(self.records[job_id])


def make_server(address, jobs, auth_token=None):
    try:
        is_loopback = ipaddress.ip_address(address[0]).is_loopback
    except ValueError:
        is_loopback = address[0].casefold() == 'localhost'
    if not is_loopback and not auth_token:
        raise ValueError('A non-loopback inference listener requires an authentication token')

    class Handler(BaseHTTPRequestHandler):
        def authorized(self):
            if auth_token is None:
                return True
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + auth_token)

        def reply(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.authorized():
                self.reply({'error': 'unauthorized'}, 401)
                return
            if self.path == '/health':
                with jobs.lock:
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
            if not self.authorized():
                self.reply({'error': 'unauthorized'}, 401)
                return
            if self.path != '/jobs':
                self.reply({'error': 'Unknown endpoint'}, 404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 2 * 1024 * 1024:
                    self.reply({'error': 'request body exceeds 2 MiB'}, 413)
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('Incomplete request body')
                payload = json.loads(raw)
                self.reply(jobs.submit(payload), 202)
            except RuntimeError as exc:
                self.reply({'error': str(exc)}, 503)
            except (KeyError, TypeError, ValueError) as exc:
                self.reply({'error': str(exc)}, 400)

        def do_DELETE(self):
            if not self.authorized():
                self.reply({'error': 'unauthorized'}, 401)
                return
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
            env.pop('SPATIALFORGE_INFERENCE_TOKEN', None)
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
    parser.add_argument('--work-root')
    parser.add_argument('--state-file')
    parser.add_argument('--auth-token-env', default='SPATIALFORGE_INFERENCE_TOKEN')
    args = parser.parse_args()
    # The GPU host is the execution endpoint, never a forwarding client.
    os.environ.pop('SPATIALFORGE_INFERENCE_URL', None)
    os.environ['SPATIALFORGE_GPU_CANDIDATES'] = args.gpus
    config = json.loads(Path(args.config).read_text(encoding='utf8'))
    work_root = Path(args.work_root or config.get('work_root', config['project'])).resolve()
    state_path = Path(args.state_file or config.get(
        'state_file', str(Path(config['project']) / '.deployment' / 'inference-jobs.json')
    )).resolve()
    auth_token = os.environ.get(args.auth_token_env) or None
    try:
        is_loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        is_loopback = args.host.casefold() == 'localhost'
    if not is_loopback and not auth_token:
        parser.error('A non-loopback --host requires the environment token named by --auth-token-env')
    os.environ['SPATIALFORGE_STORAGE_MODE'] = ('local-models-shared-code-output'
        if config.get('path_rewrites') else 'shared')
    executor = Executor(config, args.gpus)
    jobs = Jobs(executor, work_root=work_root, state_path=state_path)
    server = make_server(
        (args.host, args.port),
        jobs,
        auth_token=auth_token,
    )
    print(json.dumps({'listening': server.server_address, 'host': socket.gethostname(), 'gpus': args.gpus}), flush=True)

    def request_shutdown(signum, frame):
        server.shutdown()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    serving = threading.Thread(target=server.serve_forever, name='spatialforge-inference-http')
    serving.start()
    try:
        serving.join()
    finally:
        jobs.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
