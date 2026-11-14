"""Submit frozen capture requests and transfer evidence over gRPC."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time

import grpc

from . import isaac_sim_pb2 as messages
from .isaac_sim_pb2_grpc import IsaacSimStub
from ..files import safe_path


CHUNK_BYTES = 256 * 1024
STATES = {
    messages.JOB_UNKNOWN: 'unknown',
    messages.JOB_QUEUED: 'queued',
    messages.JOB_RUNNING: 'running',
    messages.JOB_COMPLETED: 'completed',
    messages.JOB_FAILED: 'failed',
    messages.JOB_CANCELLED: 'cancelled',
}

class CaptureFailed(RuntimeError):
    """The remote service confirmed a terminal capture failure."""


def _asset_chunks(job_id, name, stream):
    offset = 0
    while data := stream.read(CHUNK_BYTES):
        yield messages.AssetChunk(job_id=job_id, name=name, offset=offset, data=data)
        offset += len(data)
    yield messages.AssetChunk(job_id=job_id, name=name, offset=offset, eof=True)


def _download(stub, job_id, output, names, timeout):
    with TemporaryDirectory(prefix='isaac-download-', dir=output.parent) as directory:
        incoming = Path(directory) / 'capture'
        incoming.mkdir()
        for name in names:
            target = safe_path(incoming, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            request = messages.ArtifactRequest(job_id=job_id, name=name)
            size, complete = 0, False
            with target.open('wb') as stream:
                for chunk in stub.DownloadArtifacts(request, timeout=timeout):
                    if (chunk.job_id, chunk.name, chunk.offset) != (job_id, name, size):
                        raise RuntimeError(f'Isaac returned an invalid artifact stream for {name}')
                    size += stream.write(chunk.data)
                    complete = chunk.eof
            if not complete:
                raise RuntimeError(f'Isaac artifact stream ended before EOF for {name}')
        incoming.replace(output)


def run_capture(endpoint, job_id, request_json, output, *, assets, timeout_seconds, rpc_timeout,
                on_status, should_stop):
    output = Path(output)
    with grpc.insecure_channel(endpoint) as channel:
        stub = IsaacSimStub(channel)
        query = messages.JobStatusRequest(job_id=job_id)
        status = stub.JobStatus(query, timeout=rpc_timeout)
        if status.state == messages.JOB_UNKNOWN:
            on_status({'state': 'preparing'})
            if should_stop():
                raise CaptureFailed(f'Isaac job {job_id} canceled before submission')
            for name, path in assets.items():
                with Path(path).open('rb') as stream:
                    stub.UploadAsset(_asset_chunks(job_id, name, stream), timeout=rpc_timeout)
            submitted = stub.Capture(messages.CaptureRequest(job_id=job_id, request_json=request_json),
                                     timeout=rpc_timeout)
            if not submitted.accepted:
                raise CaptureFailed(f'Isaac declined {job_id}: {submitted.message}')
            status = stub.JobStatus(query, timeout=rpc_timeout)
        deadline = time.monotonic() + timeout_seconds
        cancel_sent = False
        while status.state in (messages.JOB_QUEUED, messages.JOB_RUNNING):
            on_status({'state': STATES[status.state]})
            timed_out = time.monotonic() >= deadline
            if not cancel_sent and (should_stop() or timed_out):
                stub.Cancel(messages.CancelRequest(job_id=job_id), timeout=rpc_timeout)
                cancel_sent = True
                deadline = time.monotonic() + rpc_timeout
            elif timed_out:
                raise TimeoutError(f'Isaac job {job_id} is still stopping')
            time.sleep(2)
            status = stub.JobStatus(query, timeout=rpc_timeout)
        if status.state != messages.JOB_COMPLETED:
            raise CaptureFailed(f'Isaac job {job_id} {STATES[status.state]}: {status.message}')
        names = list(status.artifacts)
        if 'report.json' not in names:
            raise CaptureFailed(f'Isaac job {job_id} did not publish report.json')
        _download(stub, job_id, output, names, rpc_timeout)
    return {'job_id': job_id, 'state': 'completed', 'artifacts': names}
