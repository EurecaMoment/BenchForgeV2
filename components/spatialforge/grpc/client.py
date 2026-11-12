"""Isaac Sim gRPC 客户端 — BenchForge 侧调用远程仿真服务。

端点读 config/benchforge.local.json 顶层 isaac.grpc（host/port），
也可用 --endpoint host:port 覆盖。

手动验证：
  python client.py "hello isaac"                            # Test RPC
  python client.py --capture req.json --output /tmp/cap     # 走完整采集流程
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import grpc

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isaac_sim_pb2
import isaac_sim_pb2_grpc

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / 'config' / 'benchforge.local.json'
PLACEHOLDER_PREFIX = 'YOUR_CONFIG'
CHUNK_BYTES = 256 * 1024

STATE_NAMES = {
    isaac_sim_pb2.JOB_UNKNOWN: 'unknown',
    isaac_sim_pb2.JOB_QUEUED: 'queued',
    isaac_sim_pb2.JOB_RUNNING: 'running',
    isaac_sim_pb2.JOB_COMPLETED: 'completed',
    isaac_sim_pb2.JOB_FAILED: 'failed',
    isaac_sim_pb2.JOB_CANCELLED: 'cancelled',
}
TERMINAL_STATES = {'completed', 'failed', 'cancelled'}


def load_endpoint(config_path=None):
    """Return (endpoint, timeout_seconds) from isaac.grpc in benchforge.local.json."""
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    cfg = json.loads(config_path.read_text(encoding='utf8'))
    grpc_cfg = (cfg.get('isaac') or {}).get('grpc') or {}
    host = grpc_cfg.get('host', '')
    if not host or str(host).startswith(PLACEHOLDER_PREFIX):
        raise ValueError(
            f'isaac.grpc.host 未配置（{config_path}）；'
            '请填远程 Isaac Sim gRPC 服务器地址，并用 spatialforge_app.py sync 同步。')
    port = grpc_cfg.get('port')
    if not port:
        raise ValueError(f'isaac.grpc.port 未配置（{config_path}）')
    timeout = grpc_cfg.get('timeout_seconds')
    if not timeout:
        raise ValueError(f'isaac.grpc.timeout_seconds 未配置（{config_path}）')
    return f'{host}:{port}', int(timeout)


def new_job_id(prefix='cap'):
    return f'{prefix}-{time.strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:8]}'


def _channel(endpoint, timeout_seconds):
    channel = grpc.insecure_channel(endpoint)
    grpc.channel_ready_future(channel).result(timeout=timeout_seconds or 60)
    return channel


def test(info, endpoint=None, timeout_seconds=None):
    """连通性测试：调用远程服务的 Test RPC，服务端打印 info 并回显。"""
    if endpoint is None:
        endpoint, default_timeout = load_endpoint()
        timeout_seconds = timeout_seconds or default_timeout
    with _channel(endpoint, timeout_seconds) as channel:
        stub = isaac_sim_pb2_grpc.IsaacSimStub(channel)
        response = stub.Test(isaac_sim_pb2.TestRequest(info=str(info)),
                             timeout=timeout_seconds or 60)
    return {'ok': response.ok, 'echo': response.echo}


def upload_asset(endpoint, job_id, name, data, timeout_seconds=None):
    """把单个资产文件分块上传到作业私有目录。"""
    def chunks():
        for offset in range(0, len(data), CHUNK_BYTES):
            yield isaac_sim_pb2.AssetChunk(job_id=job_id, name=name, offset=offset,
                                          data=data[offset:offset + CHUNK_BYTES])
        yield isaac_sim_pb2.AssetChunk(job_id=job_id, name=name, offset=len(data), eof=True)

    with _channel(endpoint, timeout_seconds) as channel:
        reply = isaac_sim_pb2_grpc.IsaacSimStub(channel).UploadAsset(
            chunks(), timeout=timeout_seconds or 600)
    return {'job_id': reply.job_id, 'name': reply.name, 'bytes': reply.bytes_received}


def capture(endpoint, job_id, request_json, timeout_seconds=None):
    """提交采集作业（异步），request_json 为 worker 原本写盘的 request.json 字节。"""
    payload = request_json.encode('utf8') if isinstance(request_json, str) else request_json
    with _channel(endpoint, timeout_seconds) as channel:
        reply = isaac_sim_pb2_grpc.IsaacSimStub(channel).Capture(
            isaac_sim_pb2.CaptureRequest(job_id=job_id, request_json=payload),
            timeout=timeout_seconds or 120)
    return {'job_id': reply.job_id, 'accepted': reply.accepted, 'message': reply.message}


def job_status(endpoint, job_id, timeout_seconds=None):
    with _channel(endpoint, timeout_seconds) as channel:
        reply = isaac_sim_pb2_grpc.IsaacSimStub(channel).JobStatus(
            isaac_sim_pb2.JobStatusRequest(job_id=job_id), timeout=timeout_seconds or 60)
    return {'state': STATE_NAMES.get(reply.state, 'unknown'),
            'message': reply.message, 'artifacts': list(reply.artifacts)}


def cancel(endpoint, job_id, timeout_seconds=None):
    with _channel(endpoint, timeout_seconds) as channel:
        reply = isaac_sim_pb2_grpc.IsaacSimStub(channel).Cancel(
            isaac_sim_pb2.CancelRequest(job_id=job_id), timeout=timeout_seconds or 60)
    return {'cancelled': reply.cancelled, 'message': reply.message}


def wait_job(endpoint, job_id, timeout_seconds, poll_seconds=1.0,
             on_status=None, should_stop=None):
    """轮询直到作业进入终态；on_status 用于心跳，should_stop 返回 True 时取消作业。"""
    deadline = time.time() + timeout_seconds
    while True:
        status = job_status(endpoint, job_id)
        if on_status:
            on_status(status)
        if status['state'] in TERMINAL_STATES:
            return status
        if should_stop and should_stop():
            status['cancel'] = cancel(endpoint, job_id)
            return {**status, 'state': 'cancelled'}
        if time.time() >= deadline:
            status['cancel'] = cancel(endpoint, job_id)
            raise TimeoutError(f'作业 {job_id} 超过 {timeout_seconds}s 未完成（已请求取消）')
        time.sleep(poll_seconds)


def download_artifacts(endpoint, job_id, dest, names=None, timeout_seconds=None):
    """流式下载工件到 dest 目录，返回写出的相对路径列表。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    handles = {}
    try:
        for name in names or [None]:
            request = isaac_sim_pb2.ArtifactRequest(job_id=job_id, name=name or '')
            with _channel(endpoint, timeout_seconds) as channel:
                for chunk in isaac_sim_pb2_grpc.IsaacSimStub(channel).DownloadArtifacts(
                        request, timeout=timeout_seconds or 3600):
                    target = dest / chunk.name
                    handle = handles.get(chunk.name)
                    if handle is None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        handle = handles[chunk.name] = target.open('wb')
                        written.append(chunk.name)
                    if chunk.data:
                        handle.write(chunk.data)
                    if chunk.eof:
                        handle.close()
                        handles.pop(chunk.name, None)
    finally:
        for handle in handles.values():
            handle.close()
    return written


def run_capture(endpoint, job_id, request_json, output, assets=None,
                timeout_seconds=3600, on_status=None, should_stop=None):
    """完整采集流程：上传资产 -> 提交 -> 轮询 -> 下载工件。"""
    for name, path in (assets or {}).items():
        upload_asset(endpoint, job_id, name, Path(path).read_bytes())
    submitted = capture(endpoint, job_id, request_json, timeout_seconds=min(120, timeout_seconds))
    if not submitted['accepted']:
        raise RuntimeError(f'远程服务拒绝作业 {job_id}: {submitted["message"]}')
    status = wait_job(endpoint, job_id, timeout_seconds, on_status=on_status,
                      should_stop=should_stop)
    if status['state'] != 'completed':
        raise RuntimeError(f'作业 {job_id} 结束状态为 {status["state"]}: {status["message"]}')
    files = download_artifacts(endpoint, job_id, output, timeout_seconds=timeout_seconds)
    return {'job_id': job_id, 'state': status['state'], 'artifacts': files, 'output': str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('info', nargs='?', default='ping', help='Test RPC 的测试数据')
    parser.add_argument('--endpoint', help='host:port，覆盖配置文件')
    parser.add_argument('--config', help='benchforge.local.json 路径')
    parser.add_argument('--timeout', type=int, default=None, help='超时秒数')
    parser.add_argument('--capture', help='走采集流程：request.json 路径')
    parser.add_argument('--assets', help='资产目录，目录内文件按相对路径上传')
    parser.add_argument('--output', default='./capture', help='工件输出目录（配合 --capture）')
    parser.add_argument('--job-id', help='作业 ID，默认自动生成')
    args = parser.parse_args()

    endpoint = args.endpoint
    timeout = args.timeout
    if endpoint is None:
        endpoint, default_timeout = load_endpoint(args.config)
        timeout = timeout or default_timeout

    if not args.capture:
        print(json.dumps(test(args.info, endpoint=endpoint, timeout_seconds=timeout),
                         ensure_ascii=False))
        return

    assets = {}
    if args.assets:
        base = Path(args.assets)
        assets = {str(path.relative_to(base)): path for path in sorted(base.rglob('*')) if path.is_file()}
    job_id = args.job_id or new_job_id()
    result = run_capture(endpoint, job_id, Path(args.capture).read_bytes(), args.output,
                         assets=assets, timeout_seconds=timeout or 3600,
                         on_status=lambda s: print(json.dumps({'job_id': job_id, **s}, ensure_ascii=False),
                                                   file=sys.stderr, flush=True))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
