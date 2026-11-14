"""Durable production tasks for the configured model providers."""
import json
from pathlib import Path

from storage.files import write_json
from capabilities.asset_generation.generation import GenerationTools
from capabilities.asset_generation.generation import generation_defaults
from capabilities.asset_generation.generation import _file_record
from service_access.configuration import MODEL_PROVIDERS
from service_access.progress import record_progress


TOOLS = {*MODEL_PROVIDERS, 'mesh_import'}


def validate_generation_request(tools, name, parameters):
    """Resolve production input files and normalize tool parameters."""
    if name not in TOOLS:
        raise ValueError('generation tool must be diffusion, sam3, trellis, depth or mesh_import')
    if not isinstance(parameters, dict):
        raise ValueError('generation parameters must be an object')
    value = dict(parameters)
    defaults = generation_defaults(name) if name != 'mesh_import' else {}
    for key in ('source_image', 'source_mesh', 'source_gaussian'):
        if value.get(key):
            value[key] = str(tools.source_path(value[key]))
    if name == 'diffusion':
        if not isinstance(value.get('prompt'), str) or not value['prompt'].strip():
            raise ValueError('diffusion requires prompt')
        for key in ('width', 'height', 'steps'):
            if key in defaults:
                value.setdefault(key, defaults[key])
            if key in value and (type(value[key]) is not int or value[key] <= 0):
                raise ValueError(f'{key} must be a positive integer')
        value.setdefault('seed', defaults.get('seed', 42))
    elif name == 'depth':
        if not value.get('source_image'):
            raise ValueError('depth requires source_image')
        value.setdefault('input_size', defaults.get('process_res', 1024))
        if type(value['input_size']) is not int or not 140 <= value['input_size'] <= 1024:
            raise ValueError('DA3 input_size must be an integer from 140 to 1024')
        if ('intrinsics' in value) != ('extrinsics' in value):
            raise ValueError('DA3 pose conditioning requires both intrinsics and extrinsics')
    elif name in {'sam3', 'trellis'}:
        if not value.get('source_image'):
            raise ValueError(f'{name} requires source_image')
        if name == 'sam3':
            if not value.get('prompts') and not value.get('instances'):
                raise ValueError('sam3 requires prompts or instances')
            value.setdefault('confidence', defaults.get('threshold', .2))
        else:
            if not isinstance(value.get('objects'), list) or not value['objects']:
                raise ValueError('trellis requires objects with object_id and source_mask')
            objects = []
            identities = set()
            for item in value['objects']:
                object_id = item.get('object_id')
                if (not isinstance(object_id, str) or not object_id or object_id in {'.', '..'} or
                        '/' in object_id or '\\' in object_id or object_id in identities):
                    raise ValueError('trellis object_id must be a unique filename component')
                identities.add(object_id)
                objects.append({**item, 'source_mask': str(tools.source_path(item['source_mask']))})
            value['objects'] = objects
            value.setdefault('seed', defaults.get('seed', 42))
    else:
        if not value.get('source_mesh') or not isinstance(value.get('label'), str) or not value['label'].strip():
            raise ValueError('mesh_import requires source_mesh and label')
    return value


def _published(tools, spec, work, source, frame, provenance, status, image=None, mask=None):
    """Retain registration identity when a completed worker stage is resumed."""
    work.mkdir(parents=True, exist_ok=True)
    receipt = work / 'asset_ref.json'
    if receipt.is_file():
        result = json.loads(receipt.read_text(encoding='utf8'))
        tools.asset_path(result['asset_id'], 'mesh.json')
        return result
    return tools._publish(spec, work, source, frame, provenance, status, image, mask)


def execute_generation_stage(store, task, stop):
    tools = GenerationTools(store.root)
    intent = task['unit']['intent']
    name = intent['tool']
    value = validate_generation_request(tools, name, intent['parameters'])
    directory = store.directory(task['id'], task['unit']['revision'])
    work = directory / 'generation_stage'
    work.mkdir(parents=True, exist_ok=True)
    record_progress(directory, name)
    result = {'tool': name, 'status': 'ok', 'gt_source': False, 'parameters': value}
    masks = set()
    if name == 'diffusion':
        output = work / 'image.png'
        request = {key: value[key] for key in ('prompt', 'width', 'height', 'steps', 'seed') if key in value}
        request['output'] = str(output)
        if value.get('source_image'):
            request['image'] = value['source_image']
        result['worker'] = tools.execute(name, request, work / 'worker', stop)
        result['source_path'] = str(output)
    elif name == 'depth':
        request = {'image': value['source_image'], 'output_dir': str(work / 'depth'),
                   'input_size': value['input_size']}
        request.update({key: value[key] for key in ('intrinsics', 'extrinsics') if key in value})
        worker = tools.execute(name, request, work / 'worker', stop)
        result.update(worker=worker, source_path=worker['depth'], visualization=worker['visualization'],
                      depth_type=worker['depth_type'], units=worker['units'], scale=worker['scale'])
    elif name == 'sam3':
        output = work / 'segmentation'
        request = {'image': value['source_image'], 'output_dir': str(output), 'confidence': value['confidence']}
        request.update({key: value[key] for key in ('prompts', 'instances', 'box_padding_ratio') if key in value})
        worker = tools.execute(name, request, work / 'worker', stop)
        result['worker'] = worker
        result['segments'] = [{**segment, 'source_path': str(output / segment['mask'])}
                              for segment in worker['segments']]
        masks.update(Path(segment['source_path']) for segment in result['segments'])
    elif name == 'trellis':
        output = work / 'meshes'
        objects = [{'object_id': item['object_id'], 'image': value['source_image'],
                    'mask': item['source_mask'], 'seed': item.get('seed', value['seed'])} for item in value['objects']]
        request = {'output_dir': str(output), 'objects': objects}
        worker = tools.execute(name, request, work / 'worker', stop)
        result['worker'] = worker
        result['assets'] = []
        for asset in worker['assets']:
            source = output / asset['asset']
            result['assets'].append({**asset, 'source_path': str(source), 'metric_reconstruction': False})
    else:
        if stop.is_set():
            raise RuntimeError('mesh import canceled')
        frame = value.get('source_frame', str(value.get('source_up_axis', 'Z')).lower() + '_up')
        if frame not in {'sam3d_camera', 'y_up', 'z_up'}:
            raise ValueError('source_frame must be sam3d_camera, y_up or z_up')
        source = Path(value['source_mesh'])
        registration = _published(tools, value, work / 'registered', source, frame,
            {'tools': ['mesh_import'], 'input': _file_record(source),
             'source_frame': frame}, 'imported')
        result['assets'] = [{'asset_id': registration['asset_id'], 'source_path': str(source),
                             'registration': registration}]
    def kind(path):
        if path in masks:
            return 'mask'
        return {'.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.glb': 'mesh',
                '.gltf': 'mesh', '.ply': 'mesh', '.obj': 'mesh', '.npy': 'array', '.npz': 'array',
                '.json': 'json'}.get(path.suffix.lower(), 'file')
    result['files'] = [{'file': path.relative_to(directory).as_posix(), 'source_path': str(path),
                        'kind': kind(path), 'bytes': path.stat().st_size}
                       for path in sorted(work.rglob('*')) if path.is_file()]
    write_json(directory / 'generation_stage.json', result)
    record_progress(directory, 'complete', tool=name)
    store.update(task['id'], state='SUCCEEDED', result=result, unit={**task['unit'], 'phase': 'complete'})
    return result
