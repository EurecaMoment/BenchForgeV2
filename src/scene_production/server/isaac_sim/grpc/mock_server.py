"""Local-only mock for exercising the Isaac capture transport."""
import argparse
import json
import os
import threading
import time
from concurrent import futures
from pathlib import Path
from tempfile import TemporaryDirectory

import grpc

import numpy as np
from PIL import Image

from scene_production.server.isaac_sim.grpc import isaac_sim_pb2
from scene_production.server.isaac_sim.grpc import isaac_sim_pb2_grpc
from service_access.artifacts import safe_path

CHUNK_BYTES = int(os.environ.get('ISAAC_SIM_MOCK_CHUNK', 256 * 1024))
MOCK_SECONDS = float(os.environ.get('ISAAC_SIM_MOCK_SECONDS', 2))

class Job:
    def __init__(self, job_id, root):
        self.job_id = job_id
        self.dir = root / job_id
        self.assets = self.dir / 'assets'
        self.capture = self.dir / 'capture'
        self.state = isaac_sim_pb2.JOB_UNKNOWN
        self.message = 'queued'
        self.artifacts = []
        self.cancel = threading.Event()
        self.submitted = False
        self.lock = threading.Lock()


class IsaacSimServicer(isaac_sim_pb2_grpc.IsaacSimServicer):
    """Serve the capture protocol with explicitly synthetic artifacts."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.lock = threading.Lock()

    def Test(self, request, context):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Test called, info: {request.info}", flush=True)
        return isaac_sim_pb2.TestResponse(ok=True, echo=request.info)

    def UploadAsset(self, request_iterator, context):
        job_id = None
        name = None
        received = 0
        handle = None
        try:
            for chunk in request_iterator:
                if job_id is None:
                    job_id = chunk.job_id
                    job = self._job(job_id)
                    target = safe_path(job.assets, chunk.name)
                    name = chunk.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    handle = target.open('wb')
                handle.write(chunk.data)
                received += len(chunk.data)
        finally:
            if handle:
                handle.close()
        if job_id is None:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, '空的上传流')
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] UploadAsset {job_id}/{name} {received} bytes", flush=True)
        return isaac_sim_pb2.UploadAssetReply(job_id=job_id, name=name, bytes_received=received)

    def Capture(self, request, context):
        if not request.job_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'job_id 不能为空')
        # 资产上传可能已创建过该作业，这里只按“是否提交过采集”去重。
        job = self._job(request.job_id)
        with job.lock:
            if job.submitted:
                return isaac_sim_pb2.CaptureReply(job_id=job.job_id, accepted=True,
                                                  message='already submitted')
            job.submitted = True
            job.state = isaac_sim_pb2.JOB_QUEUED
            job.message = 'queued'
        (job.dir / 'request.json').write_bytes(request.request_json)
        threading.Thread(target=self._capture_worker, args=(job, request.request_json), daemon=True).start()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Capture accepted {job.job_id}", flush=True)
        return isaac_sim_pb2.CaptureReply(job_id=job.job_id, accepted=True, message='accepted')

    def JobStatus(self, request, context):
        job = self.jobs.get(request.job_id)
        if job is None:
            return isaac_sim_pb2.JobStatusReply(state=isaac_sim_pb2.JOB_UNKNOWN, message='unknown job')
        with job.lock:
            return isaac_sim_pb2.JobStatusReply(state=job.state, message=job.message,
                                                artifacts=list(job.artifacts))

    def Cancel(self, request, context):
        job = self.jobs.get(request.job_id)
        if job is None:
            return isaac_sim_pb2.CancelReply(cancelled=False, message='unknown job')
        job.cancel.set()
        with job.lock:
            if job.state in (isaac_sim_pb2.JOB_QUEUED, isaac_sim_pb2.JOB_RUNNING):
                job.state = isaac_sim_pb2.JOB_CANCELLED
                job.message = 'cancelled by client'
        return isaac_sim_pb2.CancelReply(cancelled=True, message='cancel requested')

    def DownloadArtifacts(self, request, context):
        job = self.jobs.get(request.job_id)
        if job is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f'unknown job {request.job_id}')
        with job.lock:
            if job.state != isaac_sim_pb2.JOB_COMPLETED:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, f'job state={job.state}')
            names = list(job.artifacts)
        if request.name:
            wanted = request.name
            if wanted not in names:
                context.abort(grpc.StatusCode.NOT_FOUND, f'unknown artifact {wanted}')
            names = [wanted]
        for name in names:
            path = job.capture / name
            offset = 0
            with path.open('rb') as handle:
                while True:
                    data = handle.read(CHUNK_BYTES)
                    if not data:
                        break
                    yield isaac_sim_pb2.ArtifactChunk(job_id=job.job_id, name=name,
                                                      offset=offset, data=data)
                    offset += len(data)
            yield isaac_sim_pb2.ArtifactChunk(job_id=job.job_id, name=name, offset=offset, eof=True)

    # ---- 内部 ----

    def _job(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                job_dir = safe_path(self.root, job_id)
                job = Job(str(job_dir.relative_to(self.root)), self.root)
                job.assets.mkdir(parents=True, exist_ok=True)
                job.capture.mkdir(parents=True, exist_ok=True)
                self.jobs[job_id] = job
            return job

    def _capture_worker(self, job, request_json):
        with job.lock:
            job.state = isaac_sim_pb2.JOB_RUNNING
            job.message = 'mock capture running'
        deadline = time.time() + MOCK_SECONDS
        while time.time() < deadline:
            if job.cancel.is_set():
                return
            time.sleep(0.05)
        try:
            payload = json.loads(request_json.decode('utf8') or '{}')
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        artifacts = self._write_mock_artifacts(job, payload)
        with job.lock:
            if job.cancel.is_set():
                return
            job.artifacts = artifacts
            job.state = isaac_sim_pb2.JOB_COMPLETED
            job.message = f'mock capture completed ({len(artifacts)} artifacts)'
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Capture done {job.job_id}: {artifacts}", flush=True)

    def _write_mock_artifacts(self, job, payload):
        out = job.capture
        names = []
        report = {
            'status': 'mock',
            'errors': ['Synthetic Isaac capture, for transport verification only'],
            'source': 'isaac_sim_mock',
            'job_id': job.job_id,
            'mock': True,
            'request_echo': payload,
            'views': [{'id': 'view_0', 'image': 'view_0.png', 'depth': 'depth_0.npy'}],
        }
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        names.append('report.json')
        (out / 'evidence.json').write_text(json.dumps({'mock': True, 'job_id': job.job_id}), encoding='utf8')
        names.append('evidence.json')
        self._write_png(out / 'view_0.png')
        names.append('view_0.png')
        np.save(out / 'depth_0.npy', np.ones((64, 96), dtype=np.float32))
        names.append('depth_0.npy')
        return names

    @staticmethod
    def _write_png(path):
        image = np.zeros((64, 96, 3), dtype=np.uint8)
        image[:] = (24, 32, 48)
        image[16:48, 24:72] = (200, 180, 120)
        Image.fromarray(image).save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=50051)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='benchforge-isaac-mock-') as directory:
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
        isaac_sim_pb2_grpc.add_IsaacSimServicer_to_server(IsaacSimServicer(Path(directory)), server)
        address = f'127.0.0.1:{args.port}'
        port = server.add_insecure_port(address)
        server.start()
        print(f'Isaac mock listening on 127.0.0.1:{port}', flush=True)
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop(0).wait()


if __name__ == '__main__':
    main()
