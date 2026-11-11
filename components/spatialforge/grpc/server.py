"""Isaac Sim gRPC 服务端 — 在仿真器所在的远程服务器上运行。

部署步骤（在远程服务器 xx.xx.xx.xx 上）：
  1. 复制本目录（isaac_sim.proto / isaac_sim_pb2*.py / server.py）
  2. pip install grpcio（生成 mock 工件时需要 numpy、Pillow，缺失时自动降级）
  3. python server.py --port 50051

本机跑这份 server.py 时它就是远程服务的“镜子”：接口与远程完全一致，
但 Capture 只生成 mock 工件。远程侧后续补全 _capture_worker 的实际 Isaac 采集逻辑即可，
BenchForge 侧代码与配置都无需改动。
"""
import argparse
import json
import os
import shutil
import threading
import time
from concurrent import futures
from pathlib import Path

import grpc

import isaac_sim_pb2
import isaac_sim_pb2_grpc

CHUNK_BYTES = int(os.environ.get('ISAAC_SIM_MOCK_CHUNK', 256 * 1024))
MOCK_SECONDS = float(os.environ.get('ISAAC_SIM_MOCK_SECONDS', 2))

# 无 Pillow 时使用的 1x1 占位 PNG（合法 PNG，便于下游正常解码）。
MINIMAL_PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000'
    '01f15c4890000000d4944415478da63fcffff3f0300050001a5f645'
    '400000000049454e44ae426082')


def _safe_name(name):
    """拒绝绝对路径和 .. 逃逸。"""
    parts = [p for p in Path(name).parts if p not in ('', '.', '..', '/')]
    if not parts:
        raise ValueError('非法工件名')
    return str(Path(*parts))


class Job:
    def __init__(self, job_id, root):
        self.job_id = job_id
        self.dir = root / job_id
        self.assets = self.dir / 'assets'
        self.capture = self.dir / 'capture'
        self.state = isaac_sim_pb2.JOB_QUEUED
        self.message = 'queued'
        self.artifacts = []
        self.cancel = threading.Event()
        self.submitted = False
        self.lock = threading.Lock()


class IsaacSimServicer(isaac_sim_pb2_grpc.IsaacSimServicer):
    """远程服务实现。Test/资产/作业接口已定型，Capture 的工件来源由 mock 填充。"""

    def __init__(self, root):
        self.root = root
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
                    name = _safe_name(chunk.name)
                    job = self._job(job_id)
                    target = job.assets / name
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
            wanted = _safe_name(request.name)
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
                safe_id = _safe_name(job_id)
                job = Job(safe_id, self.root)
                job.assets.mkdir(parents=True, exist_ok=True)
                job.capture.mkdir(parents=True, exist_ok=True)
                self.jobs[safe_id] = job
            return job

    def _capture_worker(self, job, request_json):
        """mock 采集：等待一小段时间后写入与真实采集同名的工件。

        远程服务器上把这里替换为实际的 Isaac Sim 采集（读取 request.json、驱动仿真器、
        写 capture/ 目录），RPC 契约和客户端代码都不需要改。
        """
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
            'status': 'ok',
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
        if self._write_npy(out / 'depth_0.npy'):
            names.append('depth_0.npy')
        (out / 'scene.usda').write_text('#usda 1.0\n(mock scene)\n', encoding='utf8')
        names.append('scene.usda')
        return names

    @staticmethod
    def _write_png(path):
        try:
            from PIL import Image
        except ImportError:
            path.write_bytes(MINIMAL_PNG)
            return
        import numpy as np
        image = np.zeros((64, 96, 3), dtype=np.uint8)
        image[:] = (24, 32, 48)
        image[16:48, 24:72] = (200, 180, 120)
        Image.fromarray(image, 'RGB').save(path)

    @staticmethod
    def _write_npy(path):
        try:
            import numpy as np
        except ImportError:
            return False
        np.save(path, np.linspace(0.0, 1.0, 96 * 64, dtype=np.float32).reshape(64, 96))
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0', help='监听地址，默认 0.0.0.0')
    parser.add_argument('--port', type=int, default=50051, help='监听端口，默认 50051')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent / '_mock_jobs'),
                        help='作业与工件存放目录（mock 使用）')
    parser.add_argument('--reset', action='store_true', help='启动前清空作业目录')
    args = parser.parse_args()
    root = Path(args.root)
    if args.reset and root.is_dir():
        shutil.rmtree(root)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    isaac_sim_pb2_grpc.add_IsaacSimServicer_to_server(IsaacSimServicer(root), server)
    address = f'{args.host}:{args.port}'
    server.add_insecure_port(address)
    server.start()
    print(f'Isaac Sim gRPC server listening on {address}', flush=True)
    server.wait_for_termination()


if __name__ == '__main__':
    main()
