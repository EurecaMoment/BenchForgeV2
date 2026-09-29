"""Composable generation tools backed by the installed BenchForge workers.

The durable unit is an asset and its receipt, not a permanently loaded GPU
service. Existing images/meshes and newly generated images share the same catalog.
"""
import contextlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

from benchclaw.store import write_json
from .progress import record_progress
from .mesh_appearance import inspect_mesh_appearance


class ResourceWait(RuntimeError):
    pass


def _file_record(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class GenerationTools:
    def __init__(self, artifact_root):
        self.root = Path(artifact_root).resolve()
        self.assets = self.root / 'generated_assets'
        self.assets.mkdir(parents=True, exist_ok=True)
        self.project = Path(os.environ.get('SPATIALFORGE_BENCHFORGE_ROOT', Path(__file__).resolve().parents[2]))
        self._config = None

    @property
    def config(self):
        if self._config is None:
            source = str(self.project / 'src')
            if source not in sys.path:
                sys.path.insert(0, source)
            from .runtime_config import RuntimeConfig
            self._config = RuntimeConfig(os.environ.get('SPATIALFORGE_MODELS_CONFIG', self.project / 'models.local.json'))
        return self._config

    def catalog(self, asset_ids=None):
        records = []
        for path in sorted(self.assets.glob('*/asset.json')):
            if asset_ids is not None and path.parent.name not in asset_ids:
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            record={k: data.get(k) for k in ('asset_id', 'label', 'prompt', 'size_bounds', 'source', 'physics', 'appearance', 'status', 'gaussian')}
            # Compact geometry bounds let the planner choose an explicit pose
            # and size envelope without inspecting tens of thousands of vertices.
            mesh_path=path.parent/'mesh.json'
            if mesh_path.is_file():
                mesh=json.loads(mesh_path.read_text(encoding='utf8'))
                record['appearance']={**(record.get('appearance') or {}), 'transport':inspect_mesh_appearance(mesh)}
                bounds=mesh.get('bounds')
                record['geometry']={'coordinate_frame':mesh.get('coordinate_frame'),'source_bounds':bounds,
                    **({'camera_coordinates':mesh['camera_coordinates']} if 'camera_coordinates' in mesh else {}),
                    **({'source_camera':mesh['source_camera']} if 'source_camera' in mesh else {}),
                    'source_extent': [bounds[1][i]-bounds[0][i] for i in range(3)] if bounds else None,
                    'scale_policy':'uniform_fit; requested size is a bounding envelope; choose explicit Euler pose and preserve source proportions',
                    'gravity_alignment':'unmeasured'}
            records.append(record)
        return records

    def asset_path(self, asset_id, filename='asset.json'):
        if not isinstance(asset_id, str) or not re.fullmatch(r'asset_[a-f0-9]{16}', asset_id):
            raise ValueError('invalid registered asset ID')
        root = self.assets / asset_id
        path = (root / filename).resolve()
        if not _inside(path, root) or not path.is_file():
            raise ValueError('registered asset file is unavailable')
        return path

    def source_path(self, value):
        """Only operator-configured import roots can supply production inputs."""
        path = Path(value).expanduser().resolve()
        roots = [self.root, Path(os.environ.get('SPATIALFORGE_TASK_ROOT', self.root / 'operator_workspaces')).resolve(),
                 *(Path(p).expanduser().resolve() for p in os.environ.get('SPATIALFORGE_IMPORT_ROOTS', '').split(os.pathsep) if p)]
        if not path.is_file() or not any(_inside(path, root) for root in roots):
            raise ValueError('source must be a file inside the artifact root, task workspace or SPATIALFORGE_IMPORT_ROOTS')
        return path

    @contextlib.contextmanager
    def gpu(self, minimum_mib):
        import fcntl
        candidates = {p.strip() for p in os.environ.get('SPATIALFORGE_GPU_CANDIDATES', '0').split(',')}
        query = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.free', '--format=csv,noheader,nounits'], text=True)
        available = sorted([(int(line.split(',')[1]), line.split(',')[0].strip()) for line in query.splitlines() if ',' in line], reverse=True)
        for free, index in available:
            if index not in candidates or free < minimum_mib:
                continue
            lock = open('/tmp/benchforge_gpu_' + index + '.lock', 'a')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                continue
            try:
                yield index
                return
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()
        raise ResourceWait(f'Waiting for a generation GPU with {minimum_mib} MiB free')

    @staticmethod
    def _outputs_exist(name, request, result):
        if result.get('status') != 'ok':
            return False
        if name in {'diffusion', 'flux', 'qwen_image_edit', 'objectclear', 'lama'}:
            paths = [Path(request['output'])]
        elif name == 'sam3':
            paths = [Path(request['output_dir']) / s['mask'] for s in result.get('segments', [])]
        elif name == 'sam3d':
            if len(result.get('assets', [])) != len(request.get('objects', [])):
                return False
            paths = [Path(request['output_dir']) / s['asset'] for s in result['assets']]
        elif name == 'depth_anything':
            paths = [Path(result[key]) for key in ('depth', 'visualization')]
        else:
            return True
        return all(p.is_file() and p.stat().st_size > 0 for p in paths)

    def execute(self, name, request, work, stop):
        work = Path(work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        record_progress(work,name,object_id=work.parent.name,work=str(work))
        response, contract_path = work / 'response.json', work / 'contract.json'
        # Size/mtime receipts protect edited sources without hashing assets.
        inputs = []
        for item in [request, *request.get('objects', [])]:
            for key in ('image', 'mask'):
                if item.get(key):
                    inputs.append(_file_record(item[key]))
        contract = {'tool': name, 'request': request, 'inputs': inputs}
        if contract_path.exists():
            if json.loads(contract_path.read_text(encoding='utf-8')) != contract:
                raise ValueError('generation request changed; create a new revision to preserve previous evidence')
            if response.exists():
                result = json.loads(response.read_text(encoding='utf-8'))
                if self._outputs_exist(name, request, result):
                    return result
        if stop.is_set():
            raise RuntimeError('generation canceled; partial artifacts retained')
        # Loading config also adds BenchForge to this process import path.
        config = self.config
        WORKER_MODULES = {'sam3': 'pic2sim.workers.sam3'}
        if name == 'depth_anything':
            python = os.environ.get('SPATIALFORGE_DEPTH_PYTHON') or config.model('depth_anything')['python']
            module, minimum = 'spatialforge.depth_worker', 0
        elif name == 'diffusion':
            python, module, minimum = config.model('flux')['python'], 'spatialforge.diffusion_worker', 28000
        elif name == 'sam3d':
            python, module, minimum = config.model('sam3d')['python'], 'spatialforge.sam3d_texture_worker', 23000
        else:
            python, module = config.model(name)['python'], WORKER_MODULES[name]
            minimum = {'sam3': 7000, 'sam3d': 23000, 'flux': 34000}.get(name, 24000)
        write_json(work / 'request.json', request)
        write_json(contract_path, contract)
        device = contextlib.nullcontext(None) if name == 'depth_anything' else self.gpu(minimum)
        with device as gpu:
            env = {**os.environ, 'CUDA_VISIBLE_DEVICES': gpu or '', 'PYTHONUNBUFFERED': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
            env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).resolve().parents[1]), str(self.project / 'src'), *config.data['sources'].values()])
            command = [python, '-m', module, '--request', str(work / 'request.json'), '--response', str(response)]
            execution = {'tool': name, 'gpu': gpu, 'command': command, 'started': time.time()}
            write_json(work / 'execution.json', execution)
            with (work / 'worker.log').open('a', encoding='utf-8') as log:
                process = subprocess.Popen(command, cwd=self.project, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                started = time.monotonic()
                while process.poll() is None:
                    if stop.is_set() or time.monotonic() - started > 1800:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        except ProcessLookupError:
                            pass
                        raise RuntimeError('generation canceled or timed out; partial artifacts retained')
                    time.sleep(1)
            write_json(work / 'execution.json', {**execution, 'finished': time.time(), 'exit_code': process.returncode})
            if process.returncode:
                raise RuntimeError(f'{name} execution failed; log={work}/worker.log')
        result = json.loads(response.read_text(encoding='utf-8'))
        if not self._outputs_exist(name, request, result):
            raise ValueError(f'{name} returned incomplete output; partial artifacts retained')
        return result

    def _convert(self, source, work, frame):
        conversion, glb = work / 'mesh_data.json', work / 'portable.glb'
        command = [sys.executable, '-m', 'spatialforge.mesh_export', '--source', str(source), '--output', str(conversion), '--glb-output', str(glb), '--source-frame', frame]
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        with (work / 'conversion.log').open('a', encoding='utf-8') as log:
            subprocess.run(command, check=True, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        return conversion, glb

    def _publish(self, spec, work, source, frame, provenance, status, image=None, mask=None):
        conversion, glb = self._convert(source, work, frame)
        mesh = json.loads(conversion.read_text(encoding='utf-8'))
        source_receipt=source.with_suffix('.complete.json')
        if frame=='sam3d_camera' and source_receipt.is_file():
            reconstructed=json.loads(source_receipt.read_text(encoding='utf8'))['asset']
            if 'camera_coordinates' in reconstructed:
                mesh['camera_coordinates']=reconstructed['camera_coordinates']
                provenance={**provenance,'camera_coordinates_source':_file_record(source_receipt)}
            if 'source_camera' in reconstructed:
                mesh['source_camera']=reconstructed['source_camera']
                provenance={**provenance,'source_camera_receipt':_file_record(source_receipt)}
        size = spec.get('size_hint_m')
        if size is not None and (not isinstance(size, list) or len(size) != 3 or not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in size)):
            raise ValueError('size_hint_m must contain three finite positive meter dimensions')
        asset_id = 'asset_' + uuid.uuid4().hex[:16]
        dest = self.assets / asset_id
        dest.mkdir()
        gaussian_source = spec.get('source_gaussian')
        paired = source.with_suffix('.gaussian.npz')
        if gaussian_source or paired.is_file():
            from .gaussian_asset import register_gaussian
            gaussian_source = self.source_path(gaussian_source) if gaussian_source else paired
            mesh['gaussian'] = register_gaussian(gaussian_source, dest / 'gaussian.npz', frame)
            provenance = {**provenance, 'gaussian_input': _file_record(gaussian_source)}
        write_json(dest / 'mesh.json', mesh)
        shutil.copy2(glb, dest / 'asset.glb')
        source_textures = work / 'textures'
        if source_textures.is_dir():
            shutil.copytree(source_textures, dest / 'textures', dirs_exist_ok=True)
        if image:
            shutil.copy2(image, dest / 'reference.png')
        if mask:
            shutil.copy2(mask, dest / 'mask.png')
        record = {'asset_id': asset_id, 'label': spec['label'], 'prompt': spec.get('prompt', ''), 'status': status,
                  'source': provenance['tools'], 'provenance': provenance, 'source_work': str(work), 'size_bounds': size,
                  'geometry': {'coordinate_frame': mesh['coordinate_frame'], 'bounds': mesh['bounds'], 'watertight': mesh['watertight'], 'gravity_alignment': 'unmeasured' if frame == 'sam3d_camera' else 'declared_up_axis'},
                  'physics': {'origin': 'synthetic_prior', 'calibration': 'unmeasured', 'metric_size_origin': 'requested_dimension' if size else 'unspecified'},
                  'appearance': {'encoding': mesh['appearance']['encoding'], 'pbr_textures': 'transported' if any(m.get('textures') for m in mesh.get('materials', [])) else 'absent_in_mesh_transport', 'desktop_texture_sampling': 'pending_capture', 'transport': inspect_mesh_appearance(mesh), 'materials': len(mesh.get('materials', [])), 'texture_files': sorted(str(p.relative_to(dest)) for p in (dest / 'textures').rglob('*') if p.is_file()) if (dest / 'textures').is_dir() else []},
                  'files': {p.name: p.stat().st_size for p in dest.iterdir()}}
        if mesh.get('gaussian'):record['gaussian']=mesh['gaussian']
        if 'camera_coordinates' in mesh:record['geometry']['camera_coordinates']=mesh['camera_coordinates']
        if 'source_camera' in mesh:record['geometry']['source_camera']=mesh['source_camera']
        write_json(dest / 'asset.json', record)
        write_json(work / 'asset_ref.json', record)
        return record

    def import_asset(self, source, spec, work, stop):
        """Register an existing GLB/glTF/OBJ/PLY/STL mesh without model inference."""
        work = Path(work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        if stop.is_set():
            raise RuntimeError('asset import canceled')
        source = self.source_path(source)
        frame = str(spec.get('source_up_axis', 'Z')).lower() + '_up'
        if frame not in {'y_up', 'z_up'}:
            raise ValueError('source_up_axis must be Y or Z')
        return self._publish(spec, work, source, frame, {'tools': ['mesh_import'], 'input': _file_record(source), 'declared_up_axis': spec.get('source_up_axis', 'Z')}, 'imported')

    def generate_asset(self, spec, work, stop):
        """Text/image reconstruction, mesh import, or registered asset reuse.

        label/prompt/size_hint_m/seed; optional asset_id, source_mesh,
        source_image/source_mask, source_gaussian, source_up_axis, subject_box, edit_reference, texture_baking.
        """
        from PIL import Image
        if 'texture_baking' in spec and type(spec['texture_baking']) is not bool:
            raise ValueError('texture_baking must be a boolean')
        work = Path(work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        receipt, spec_path = work / 'asset_ref.json', work / 'asset_request.json'
        source_contract = {k: _file_record(self.source_path(spec[k])) for k in ('source_image', 'source_mask', 'source_mesh', 'source_gaussian') if spec.get(k)}
        contract = {'spec': spec, 'sources': source_contract}
        if spec_path.exists() and json.loads(spec_path.read_text(encoding='utf-8')) != contract:
            raise ValueError('asset intent changed; use a new revision')
        write_json(spec_path, contract)
        if receipt.exists():
            result = json.loads(receipt.read_text(encoding='utf-8'))
            self.asset_path(result['asset_id'], 'mesh.json')
            return result
        if spec.get('asset_id'):
            result = json.loads(self.asset_path(spec['asset_id']).read_text(encoding='utf-8'))
            write_json(receipt, result)
            return result
        if not isinstance(spec.get('label'), str) or not spec['label'].strip():
            raise ValueError('asset requires a semantic label')
        if spec.get('source_mesh'):
            return self.import_asset(spec['source_mesh'], spec, work, stop)
        image = work / 'reference.png'
        tools, sources = [], {}
        if spec.get('source_image') and not spec.get('edit_reference'):
            if not image.exists():
                with Image.open(self.source_path(spec['source_image'])) as original:
                    original.convert('RGB').save(image)
            sources['image'] = source_contract['source_image']
        else:
            prompt = spec.get('prompt', spec['label'])
            if not spec.get('source_image'):
                prompt += '. A realistic product photograph of one complete standalone object, three quarter view, centered, entire object visible, neutral light gray seamless background, fine material detail, no text, no other objects, no cropping.'
            request = {'model_path': os.environ.get('SPATIALFORGE_DIFFUSION_MODEL', self.config.model('flux')['path']), 'prompt': prompt, 'output': str(image), 'seed': spec.get('seed', 42), 'width': 768, 'height': 768, 'steps': 4}
            if spec.get('source_image'):
                request['image'] = str(self.source_path(spec['source_image']))
                sources['image'] = source_contract['source_image']
            self.execute('diffusion', request, work / 'diffusion', stop)
            tools.append('FLUX.2-klein-9B')
        with Image.open(image) as original:
            image_size = original.size
        if spec.get('source_mask'):
            if spec.get('edit_reference'):
                raise ValueError('an edited reference needs a new segmentation mask')
            mask = work / 'input_mask.png'
            with Image.open(self.source_path(spec['source_mask'])) as supplied:
                if supplied.size != image_size:
                    raise ValueError('source mask and reference image dimensions differ')
                if not mask.exists():
                    supplied.convert('L').save(mask)
            selection = {'source': 'supplied_mask'}
            sources['mask'] = source_contract['source_mask']
        else:
            segment_dir = work / 'segmentation'
            request = {'checkpoint': str(Path(self.config.model('sam3')['path']) / 'sam3.pt'), 'image': str(image), 'output_dir': str(segment_dir), 'confidence': .2}
            if spec.get('subject_box'):
                request['instances'] = [{'id': 0, 'label': spec['label'], 'box': spec['subject_box']}]
            else:
                request['prompts'] = [spec['label']]
            segments = self.execute('sam3', request, work / 'sam3', stop)['segments']
            if not segments:
                raise ValueError('SAM3 did not locate the subject; image retained for a new prompt or explicit mask')
            selection = max(segments, key=lambda s: s['score'] * max(0, s['box'][2] - s['box'][0]) * max(0, s['box'][3] - s['box'][1]))
            mask = segment_dir / selection['mask']
            tools.append('SAM3')
        with Image.open(mask) as selected_mask:
            if selected_mask.convert('L').getextrema()[1] < 128:
                raise ValueError('subject mask is empty')
        request = {'source_root': self.config.data['sources']['sam3d'], 'config_path': str(Path(self.config.model('sam3d')['path']) / 'checkpoints/pipeline.yaml'), 'output_dir': str(work / 'mesh'), 'objects': [{'object_id': 'subject', 'image': str(image), 'mask': str(mask), 'seed': spec.get('seed', 42)}]}
        if spec.get('texture_baking'):request['texture_baking']=True
        reconstructed = self.execute('sam3d', request, work / 'sam3d', stop)
        selected_asset = next(a for a in reconstructed['assets'] if a['object_id'] == 'subject')
        source = work / 'mesh' / selected_asset['asset']
        tools.append('SAM3D')
        provenance = {'tools': tools, 'inputs': sources, 'segmentation': selection, 'reconstruction': selected_asset, 'seed': spec.get('seed', 42), 'metric_reconstruction': False}
        return self._publish(spec, work, source, 'sam3d_camera', provenance, 'generated', image, mask)
