"""Measure complete artifacts, never queue acknowledgements or cached outputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import uuid


def request(url, payload=None, timeout=600):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def percentile(values, quantile):
    if not values:
        return None
    values = sorted(values)
    offset = (len(values)-1)*quantile
    low = int(offset)
    return values[low] + (values[min(low+1, len(values)-1)]-values[low])*(offset-low)


parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['single', 'burst64'], required=True)
parser.add_argument('--root', default='/opt/spatialforge/trellis2-20261109')
parser.add_argument('--url', default='http://172.31.1.7:3956')
parser.add_argument('--image')
args = parser.parse_args()
root = Path(args.root)
run = root / 'benchmarks' / (args.mode + '-' + uuid.uuid4().hex[:12])
run.mkdir(parents=True)
image = args.image or str(root / 'reference.png')
health_code, health = request(args.url + '/ready')
if health_code != 200 or health.get('state') != 'ready':
    raise SystemExit('TRELLIS is not ready: ' + json.dumps(health))

def artifact_valid(payload, directory):
    if payload.get('status') != 'ok' or payload.get('cache_hit') is not False:
        return False
    assets = payload.get('assets', [])
    return len(assets) == 1 and all(
        (directory / asset['asset']).is_file() and (directory / asset['asset']).stat().st_size > 0
        and (directory / asset['asset']).with_suffix('.complete.json').is_file()
        and asset.get('base_color_texture_size') == [4096,4096]
        and asset.get('metallic_roughness_texture_size') == [4096,4096]
        and asset.get('triangles',0)>0 for asset in assets)

if args.mode == 'single':
    payload = {'output_dir': str(run), 'objects': [{'object_id': 'asset', 'image': image, 'seed': 20261109}]}
    started = time.perf_counter()
    status, result = request(args.url + '/infer', payload, timeout=600)
    elapsed = time.perf_counter()-started
    summary = {'mode': 'single', 'request': payload, 'http_status': status,
        'wall_seconds': elapsed, 'complete_artifact': artifact_valid(result, run),
        'result': result, 'profile': health, 'target_under_1s': status==200 and elapsed<=1}
else:
    barrier = threading.Barrier(65)
    burst_started = [None]
    def one(index):
        directory = run / str(index)
        payload = {'output_dir': str(directory), 'deadline_seconds': 1.0,
            'objects': [{'object_id': 'asset', 'image': image, 'seed': 20261109+index}]}
        barrier.wait()
        started = time.perf_counter()
        try:
            status, result = request(args.url + '/infer', payload, timeout=4)
        except Exception as error:
            status, result = 0, {'error': type(error).__name__ + ': ' + str(error)}
        elapsed = time.perf_counter()-started
        return {'index': index, 'seed': 20261109+index, 'http_status': status,
            'response_seconds': elapsed, 'from_burst_start_seconds': time.perf_counter()-burst_started[0],
            'complete_artifact': artifact_valid(result, directory), 'result': result}
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = [pool.submit(one, index) for index in range(64)]
        burst_started[0] = time.perf_counter()
        barrier.wait()
        rows = [future.result() for future in futures]
    wall = time.perf_counter()-burst_started[0]
    counts = {}
    for row in rows:
        key = str(row['http_status'])
        counts[key] = counts.get(key,0)+1
    successful = [row['response_seconds'] for row in rows if row['complete_artifact']]
    within = sum(row['complete_artifact'] and row['from_burst_start_seconds']<=1 for row in rows)
    summary = {'mode': 'burst64', 'concurrency': 64, 'unique_seeds': 64,
        'deadline_seconds': 1.0, 'wall_seconds': wall, 'http_status_counts': counts,
        'completed_artifacts': sum(row['complete_artifact'] for row in rows),
        'completed_artifacts_within_1s': within,
        'successful_artifact_latency_seconds': {'p50': percentile(successful,.5),
            'p95': percentile(successful,.95), 'p99': percentile(successful,.99)},
        'target_met': within==64 and wall<=1,
        'scope': 'server-local complete mesh plus embedded 4K PBR; no cache, no acknowledgement credit; expired queued work is canceled',
        'profile': health, 'requests': rows}
    for _index in range(20):
        _status, after = request(args.url + '/health')
        if not after.get('queue') and not after.get('active_batch'):
            break
        time.sleep(.25)
    summary['after'] = after

write_path = run / 'benchmark.json'
write_path.write_text(json.dumps(summary, indent=2))
(root / ('benchmark-' + args.mode + '.json')).write_text(json.dumps(summary, indent=2))
print(json.dumps({key: value for key, value in summary.items() if key not in ('requests','profile')}, indent=2), flush=True)
print('REPORT ' + str(write_path), flush=True)
