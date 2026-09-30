"""Bounded, resumable native capture transfer. Sizes and offsets, no mesh hashing."""
import json
import os
from pathlib import Path
import re
import threading
import zlib
from .capture_scope import capture_scope

CHUNK_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_FILE_BYTES = 2 * 1024**3
MAX_FILES = 160
SUFFIXES = {'.usda', '.usd', '.usdc', '.json', '.png', '.npy', '.txt', '.log', '.mp4', '.zip',
            '.jpg', '.jpeg', '.hdr', '.exr', '.tif', '.tiff', '.webp', '.bmp', '.dds', '.tga', '.tx', '.mdl'}


def capture_identity(job):
    # A new explicit transfer budget reuses files; lifecycle separately checks retry generation.
    return {key:job[key] for key in ('task_id','revision','token')}


def decode_chunk(raw, encoding='identity'):
    if not 0<len(raw)<=CHUNK_BYTES:raise ValueError('invalid wire chunk size')
    if encoding=='identity':return raw
    if encoding!='deflate':raise ValueError('unsupported chunk encoding')
    decoder=zlib.decompressobj()
    result=decoder.decompress(raw,CHUNK_BYTES+1)
    if len(result)>CHUNK_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('compressed chunk exceeds limit or is incomplete')
    return result


def validate_manifest(files):
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('capture must contain 1..160 files')
    names = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {'name', 'size', 'mtime_ns'}:
            raise ValueError('manifest requires name, size, mtime_ns')
        name = item['name']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,149}', name) or Path(name).suffix not in SUFFIXES or name in names:
            raise ValueError('invalid or duplicate capture filename')
        names.add(name)
        if type(item['size']) is not int or not 0 <= item['size'] <= MAX_FILE_BYTES:
            raise ValueError('capture file exceeds 2 GiB transfer limit')
        if type(item['mtime_ns']) is not int or item['mtime_ns'] < 0:
            raise ValueError('invalid capture mtime')
    if sum(item['size'] for item in files) > MAX_TOTAL_BYTES:
        raise ValueError('capture exceeds 4 GiB transfer limit')
    if 'report.json' not in names:
        raise ValueError('capture report missing')
    return files


def validate_capture(directory, job, store):
    report = json.loads((directory/'report.json').read_text())
    if report.get('token') != job['token']:
        raise ValueError('foreign report')
    if report.get('status') not in {'captured', 'failed'}:
        raise ValueError('invalid capture status')
    if report['status'] == 'captured':
        stored = json.loads((store.directory(job['task_id'], job['revision'])/'program.json').read_text())
        task = next(t for t in store.snapshot(job['task_id'].split('.')[0])['tasks'] if t['id'] == job['task_id'])
        scope = capture_scope(stored, task['unit']['intent'].get('capture_options'))
        required = ['evidence.json'] + (['scene.usda'] if scope['scene_export_requested'] else [])
        required += [f'view_{i}{suffix}' for i in scope['view_indices'] for suffix in ('.png', '.json', '_depth.npy', '_semantic.npy', '_instance.npy')]
        if report.get('scene_format')=='usdc':required.append('scene.usdc')
        required.extend(resource['file'] for resource in report.get('scene_resources',[]))
        if not all((directory/p).is_file() and (directory/p).stat().st_size for p in required):
            raise ValueError('incomplete native capture bundle')


class CaptureTransfer:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def folder(self, job):
        if not re.fullmatch(r'attempt_[a-f0-9]{16}', job['token']):
            raise ValueError('invalid capture token')
        return self.store.root/'transfers'/job['token']

    def begin(self, job, files):
        validate_manifest(files)
        with self.lock:
            state = self.store.worker_update(job)
            if state.get('cancel') or state.get('committed'):
                return state
            folder = self.folder(job); folder.mkdir(parents=True, exist_ok=True)
            manifest = {'job': capture_identity(job), 'files': files}
            path = folder/'manifest.json'
            if path.exists():
                if json.loads(path.read_text()) != manifest:
                    raise ValueError('immutable transfer manifest changed; retain original capture')
            else:
                temporary = folder/'manifest.tmp'
                temporary.write_text(json.dumps(manifest), encoding='utf8'); temporary.replace(path)
            data = folder/'capture'; data.mkdir(exist_ok=True)
            offsets = {}
            for item in files:
                target = data/item['name']
                if not target.exists(): target.touch()
                offsets[item['name']] = target.stat().st_size
                if offsets[item['name']] > item['size']:
                    raise ValueError('stored transfer exceeds manifest')
            self.store.worker_update(job, progress={'stage': 'upload', 'bytes_received': sum(offsets.values()), 'total_bytes': sum(f['size'] for f in files), 'files': len(files)})
            return {'offsets': offsets, 'chunk_bytes': CHUNK_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES}

    def chunk(self, job, name, offset, raw):
        if type(offset) is not int or offset < 0 or not 0 < len(raw) <= CHUNK_BYTES:
            raise ValueError('invalid capture chunk')
        with self.lock:
            state = self.store.worker_update(job)
            if state.get('cancel') or state.get('committed'): return state
            folder = self.folder(job)
            manifest = json.loads((folder/'manifest.json').read_text())
            if manifest['job'] != capture_identity(job): raise ValueError('foreign transfer job')
            item = next((f for f in manifest['files'] if f['name'] == name), None)
            if item is None: raise ValueError('file not in manifest')
            path = folder/'capture'/name
            size = path.stat().st_size
            if offset > size or offset + len(raw) > item['size']:
                raise ValueError('chunk outside expected offset or size')
            # A lost HTTP reply can replay the last chunk; compare only that chunk.
            overlap = min(size - offset, len(raw))
            with path.open('r+b') as stream:
                stream.seek(offset)
                if overlap and stream.read(overlap) != raw[:overlap]:
                    raise ValueError('conflicting duplicate capture chunk')
                stream.write(raw[overlap:]); stream.flush(); os.fsync(stream.fileno())
            received = sum((folder/'capture'/f['name']).stat().st_size for f in manifest['files'])
            self.store.worker_update(job, progress={'stage': 'upload', 'file': name, 'bytes_received': received, 'total_bytes': sum(f['size'] for f in manifest['files'])})
            return {'offset': path.stat().st_size}

    def commit(self, job):
        with self.lock:
            state = self.store.worker_update(job)
            if state.get('cancel') or state.get('committed'): return state
            folder = self.folder(job)
            manifest = json.loads((folder/'manifest.json').read_text())
            if manifest['job'] != capture_identity(job): raise ValueError('foreign transfer job')
            data = folder/'capture'
            if not all((data/f['name']).is_file() and (data/f['name']).stat().st_size == f['size'] for f in manifest['files']):
                raise ValueError('capture transfer incomplete; resume offsets')
            validate_capture(data, job, self.store)
            return self.store.commit_capture(job, data)
