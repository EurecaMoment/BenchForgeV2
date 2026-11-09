"""Resident TRELLIS.2 mesh/PBR service with bounded requests and real deadlines."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import socket
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RequestExpired(RuntimeError):
    pass


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf8')
    temporary.replace(path)


class Item:
    def __init__(self, request, timeout):
        self.id = uuid.uuid4().hex
        self.request = request
        self.arrived = time.perf_counter()
        self.deadline = self.arrived + timeout
        self.canceled = threading.Event()
        self.done = threading.Event()
        self.result = None
        self.error = None

    def check(self, *_args):
        if self.canceled.is_set() or time.perf_counter() >= self.deadline:
            raise RequestExpired('Request deadline exceeded before a complete mesh/PBR artifact was produced')


class TrellisModel:
    def __init__(self, config):
        import sys
        self.root = Path(config['root'])
        sys.path.insert(0, str(self.root / 'src'))
        import numpy as np
        import torch
        import torch.nn.functional as functional
        import timm
        from safetensors.torch import load_file
        from trellis2.modules import image_feature_extractor

        class PublicDinoV3FeatureExtractor(image_feature_extractor.DinoV3FeatureExtractor):
            def __init__(self, model_name, image_size=512):
                from torchvision import transforms
                self.model_name = model_name
                self.model = timm.create_model('vit_large_patch16_dinov3.lvd1689m', pretrained=False,
                    num_classes=0, dynamic_img_size=True)
                self.model.load_state_dict(load_file(model_name), strict=True)
                self.model.norm = torch.nn.Identity()
                self.model.eval()
                self.image_size = image_size
                self.transform = transforms.Compose([transforms.Normalize(
                    mean=[.485, .456, .406], std=[.229, .224, .225])])

            def extract_features(self, image):
                image = image.to(self.model.patch_embed.proj.weight.dtype)
                hidden = self.model.forward_features(image)
                return functional.layer_norm(hidden, hidden.shape[-1:])

        image_feature_extractor.PublicDinoV3FeatureExtractor = PublicDinoV3FeatureExtractor
        from trellis2.pipelines import Trellis2ImageTo3DPipeline
        import o_voxel
        self.np, self.torch, self.voxel = np, torch, o_voxel
        torch.set_num_threads(config.get('cpu_threads', 8))
        torch.cuda.set_per_process_memory_fraction(.94)
        torch.backends.cuda.matmul.allow_tf32 = True
        self.pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(self.root / 'models/trellis2'))
        # The dedicated 80GB GPU retains all weights instead of offloading each stage.
        self.pipeline.low_vram = False
        self.pipeline.cuda()
        self.current = None
        for model in self.pipeline.models.values():
            if hasattr(model, 'register_forward_pre_hook'):
                model.register_forward_pre_hook(self.check)
        self.pipeline.image_cond_model.model.register_forward_pre_hook(self.check)
        torch.cuda.synchronize()

    def check(self, *_args):
        if self.current is not None:
            self.current.check()

    def infer(self, item):
        from PIL import Image
        request = item.request
        output = Path(request['output_dir'])
        output.mkdir(parents=True, exist_ok=True)
        assets = []
        self.current = item
        self.torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        try:
            for index, row in enumerate(request['objects']):
                item.check()
                image_path = Path(row['image'])
                with Image.open(image_path) as source:
                    image = source.convert('RGBA' if row.get('mask') else 'RGB')
                if image.size != (1024, 1024):
                    raise ValueError('TRELLIS service requires a 1024x1024 source image')
                inputs = {'image': {'path': str(image_path), 'bytes': image_path.stat().st_size,
                                    'mtime_ns': image_path.stat().st_mtime_ns}}
                if row.get('mask'):
                    mask_path = Path(row['mask'])
                    with Image.open(mask_path) as source:
                        mask = source.convert('L')
                    if mask.size != image.size or mask.getextrema()[1] < 128:
                        raise ValueError('Object mask must match the image and contain foreground pixels')
                    image.putalpha(mask)
                    inputs['mask'] = {'path': str(mask_path), 'bytes': mask_path.stat().st_size,
                                      'mtime_ns': mask_path.stat().st_mtime_ns}
                seed = int(row.get('seed', request.get('seed', 42) + index))
                generation_start = time.perf_counter()
                with self.torch.inference_mode():
                    mesh = self.pipeline.run(image, seed=seed, pipeline_type='1024_cascade')[0]
                self.torch.cuda.synchronize()
                generation_seconds = time.perf_counter() - generation_start
                item.check()
                mesh.simplify(16777216)
                export_start = time.perf_counter()
                glb = self.voxel.postprocess.to_glb(vertices=mesh.vertices, faces=mesh.faces,
                    attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=mesh.layout,
                    voxel_size=mesh.voxel_size, aabb=[[-.5, -.5, -.5], [.5, .5, .5]],
                    decimation_target=1000000, texture_size=4096,
                    remesh=True, remesh_band=1, remesh_project=0, verbose=True)
                item.check()
                if not len(glb.faces) or not self.np.isfinite(glb.vertices).all():
                    raise ValueError('TRELLIS produced empty or nonfinite mesh geometry')
                material = glb.visual.material
                if getattr(material, 'baseColorTexture', None) is None or getattr(material, 'metallicRoughnessTexture', None) is None:
                    raise ValueError('TRELLIS mesh is missing PBR texture payloads')
                destination = output / (row['object_id'] + '.glb')
                temporary = output / (row['object_id'] + '.' + item.id + '.partial.glb')
                glb.export(str(temporary))
                item.check()
                temporary.replace(destination)
                asset = {'object_id': row['object_id'], 'asset': destination.name,
                    'model': 'microsoft/TRELLIS.2-4B', 'source_frame': 'y_up',
                    'representation': 'mesh_pbr', 'metric_reconstruction': False,
                    'camera_pose_estimated': False, 'seed': seed, 'pipeline': '1024_cascade',
                    'sampling_steps': {'sparse': 12, 'shape': 12, 'texture': 12},
                    'vertices': len(glb.vertices), 'triangles': len(glb.faces),
                    'base_color_texture_size': list(material.baseColorTexture.size),
                    'metallic_roughness_texture_size': list(material.metallicRoughnessTexture.size),
                    'bytes': destination.stat().st_size, 'inputs': inputs,
                    'generation_seconds': generation_seconds,
                    'export_seconds': time.perf_counter() - export_start}
                write_json(destination.with_suffix('.complete.json'), {'asset': asset,
                    'provider': 'trellis2', 'request_id': item.id, 'status': 'complete'})
                assets.append(asset)
                del mesh, glb
            self.torch.cuda.synchronize()
            item.check()
            result = {'status': 'ok', 'provider': 'trellis2', 'model': 'microsoft/TRELLIS.2-4B',
                'assets': assets, 'cache_hit': False, 'representations': ['mesh_pbr'],
                'timing': {'queue_seconds': started-item.arrived,
                    'compute_and_export_seconds': time.perf_counter()-started,
                    'total_seconds': time.perf_counter()-item.arrived},
                'peak_allocated_gib': self.torch.cuda.max_memory_allocated()/1024**3}
            write_json(output / 'trellis_result.json', result)
            return result
        finally:
            self.current = None


class Resident:
    def __init__(self, config, model_factory=TrellisModel):
        self.config = config
        self.queue = queue.Queue(maxsize=config.get('max_requests', 64))
        self.slots = threading.BoundedSemaphore(config.get('max_requests', 64))
        self.state, self.error = 'loading', None
        self.completed = self.failed = self.expired = self.active = 0
        self.history = []
        self.factory = model_factory
        threading.Thread(target=self.run, daemon=True).start()

    def status(self):
        return {'model': 'trellis2', 'model_id': 'microsoft/TRELLIS.2-4B',
            'state': self.state, 'error': self.error, 'host': socket.gethostname(),
            'gpu': os.environ.get('CUDA_VISIBLE_DEVICES'), 'queue': self.queue.qsize(),
            'active_batch': self.active, 'max_requests': self.config.get('max_requests', 64),
            'max_batch': 1, 'completed': self.completed, 'failed': self.failed,
            'expired': self.expired, 'latency_recent': self.history[-64:],
            'representations': ['mesh_pbr'], 'gaussian_supported': False,
            'pipeline': '1024_cascade', 'texture_size': 4096, 'resident': True}

    def submit(self, request, timeout):
        rows = request.get('objects')
        if not isinstance(rows, list) or not rows or not Path(request.get('output_dir', '')).is_absolute():
            raise ValueError('objects and an absolute output_dir are required')
        seen = set()
        for row in rows:
            identity = row.get('object_id')
            if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identity) or identity in seen:
                raise ValueError('object_id must be a unique safe filename component')
            if not isinstance(row.get('image'), str) or not Path(row['image']).is_file():
                raise ValueError('Object image does not exist')
            seen.add(identity)
        if not self.slots.acquire(blocking=False):
            raise queue.Full()
        item = Item(request, timeout)
        try:
            self.queue.put_nowait(item)
        except BaseException:
            self.slots.release()
            raise
        return item

    def run(self):
        try:
            self.model = self.factory(self.config)
            self.state = 'ready'
            print(json.dumps(self.status()), flush=True)
        except Exception:
            self.state, self.error = 'failed', traceback.format_exc()
            print(self.error, flush=True)
            return
        while True:
            item = self.queue.get()
            self.active = 1
            try:
                item.check()
                item.result = self.model.infer(item)
                self.completed += 1
                self.history.append(time.perf_counter()-item.arrived)
            except RequestExpired as error:
                item.error = str(error)
                self.expired += 1
            except Exception as error:
                item.error = str(error)
                self.failed += 1
                print(traceback.format_exc(), flush=True)
            finally:
                item.done.set()
                self.slots.release()
                self.active = 0
                self.queue.task_done()


class Server(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


def make_server(address, resident):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path in ('/health', '/ready', '/metrics'):
                self.reply(503 if self.path == '/ready' and resident.state != 'ready' else 200, resident.status())
            else:
                self.reply(404, {'error': 'Unknown endpoint'})

        def do_POST(self):
            if self.path != '/infer':
                self.reply(404, {'error': 'Unknown endpoint'})
                return
            if resident.state != 'ready':
                self.reply(503, resident.status())
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4*1024**2:
                    raise ValueError('Request JSON size must be between 1 byte and 4 MiB')
                request = json.loads(self.rfile.read(size))
                timeout = float(request.get('deadline_seconds', 3600))
                if not .01 <= timeout <= 3600:
                    raise ValueError('deadline_seconds must be between 0.01 and 3600')
                item = resident.submit(request, timeout)
                if not item.done.wait(max(0, item.deadline-time.perf_counter())):
                    item.canceled.set()
                    self.reply(504, {'status': 'deadline_exceeded', 'request_id': item.id,
                        'completed_artifact': False, 'provider': 'trellis2'})
                elif item.error:
                    self.reply(504 if 'deadline' in item.error.lower() else 500,
                        {'status': 'failed', 'error': item.error, 'provider': 'trellis2'})
                else:
                    self.reply(200, item.result)
            except queue.Full:
                self.reply(429, {'error': '64-request capacity reached; no extra GPU work was dispatched'})
            except (ValueError, KeyError, TypeError) as error:
                self.reply(400, {'error': str(error)})

    return Server(address, Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    resident = Resident(config)
    make_server((config.get('host', '127.0.0.1'), config.get('port', 3956)), resident).serve_forever()


if __name__ == '__main__':
    main()
