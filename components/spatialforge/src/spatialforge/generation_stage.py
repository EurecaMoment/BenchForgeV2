"""Independent generation steps using the existing durable worker execution."""
import json
import os
from pathlib import Path

from benchclaw.store import write_json
from .generation import GenerationTools, _file_record
from .progress import record_progress


TOOLS = {'diffusion', 'sam3', 'sam3d', 'depth_anything', 'mesh_import'}


def validate_generation_request(tools, name, parameters):
    """Resolve input files and check parameters required by the selected worker."""
    if name not in TOOLS:
        raise ValueError('generation tool must be diffusion, sam3, sam3d, depth_anything or mesh_import')
    if not isinstance(parameters, dict):
        raise ValueError('generation parameters must be an object')
    value = dict(parameters)
    for key in ('source_image', 'source_mesh', 'source_gaussian'):
        if value.get(key):
            value[key] = str(tools.source_path(value[key]))
    if name == 'diffusion':
        if not isinstance(value.get('prompt'), str) or not value['prompt'].strip():
            raise ValueError('diffusion requires prompt')
        for key, default in (('width', 768), ('height', 768), ('steps', 4)):
            value.setdefault(key, default)
            if type(value[key]) is not int or value[key] <= 0:
                raise ValueError(f'{key} must be a positive integer')
        value.setdefault('seed', 42)
    elif name == 'depth_anything':
        if not value.get('source_image'):
            raise ValueError('depth_anything requires source_image')
        value.setdefault('input_size', 518)
        if type(value['input_size']) is not int or value['input_size'] <= 0:
            raise ValueError('input_size must be a positive integer')
    elif name in {'sam3', 'sam3d'}:
        if not value.get('source_image'):
            raise ValueError(f'{name} requires source_image')
        if name == 'sam3':
            if not value.get('prompts') and not value.get('instances'):
                raise ValueError('sam3 requires prompts or instances')
            value.setdefault('confidence', .2)
        else:
            if 'texture_baking' in value and type(value['texture_baking']) is not bool:
                raise ValueError('texture_baking must be a boolean')
            if not isinstance(value.get('objects'), list) or not value['objects']:
                raise ValueError('sam3d requires objects with object_id and source_mask')
            objects = []
            identities = set()
            for item in value['objects']:
                object_id = item.get('object_id')
                if (not isinstance(object_id, str) or not object_id or
                        '/' in object_id or '\\' in object_id or object_id in identities):
                    raise ValueError('sam3d object_id must be a unique filename component')
                identities.add(object_id)
                objects.append({**item, 'source_mask': str(tools.source_path(item['source_mask']))})
            value['objects'] = objects
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
        request = {key: value[key] for key in ('prompt', 'width', 'height', 'steps', 'seed')}
        request.update(model_path=os.environ.get('SPATIALFORGE_DIFFUSION_MODEL',
                       tools.config.model('flux')['path']), output=str(output))
        if value.get('source_image'):
            request['image'] = value['source_image']
        result['worker'] = tools.execute(name, request, work / 'worker', stop)
        result['source_path'] = str(output)
    elif name == 'depth_anything':
        request = {'image': value['source_image'], 'output_dir': str(work / 'depth'),
                   'model_path': os.environ.get('SPATIALFORGE_DEPTH_MODEL',
                       tools.config.model('depth_anything')['path']),
                   'source_root': tools.config.data['sources']['depth_anything'],
                   'device': 'cpu', 'cpu_threads': 4, 'input_size': value['input_size']}
        worker = tools.execute(name, request, work / 'worker', stop)
        result.update(worker=worker, source_path=worker['depth'], visualization=worker['visualization'],
                      depth_type=worker['depth_type'], units=worker['units'], scale=worker['scale'])
    elif name == 'sam3':
        output = work / 'segmentation'
        request = {'checkpoint': str(Path(tools.config.model('sam3')['path']) / 'sam3.pt'),
                   'image': value['source_image'], 'output_dir': str(output), 'confidence': value['confidence']}
        request.update({key: value[key] for key in ('prompts', 'instances', 'box_padding_ratio') if key in value})
        worker = tools.execute(name, request, work / 'worker', stop)
        result['worker'] = worker
        result['segments'] = [{**segment, 'source_path': str(output / segment['mask'])}
                              for segment in worker['segments']]
        masks.update(Path(segment['source_path']) for segment in result['segments'])
    elif name == 'sam3d':
        output = work / 'meshes'
        objects = [{'object_id': item['object_id'], 'image': value['source_image'],
                    'mask': item['source_mask'], 'seed': item.get('seed', value.get('seed',42))} for item in value['objects']]
        request = {'source_root': tools.config.data['sources']['sam3d'],
                   'config_path': str(Path(tools.config.model('sam3d')['path']) / 'checkpoints/pipeline.yaml'),
                   'output_dir': str(output), 'objects': objects}
        if value.get('texture_baking'):request['texture_baking']=True
        worker = tools.execute(name, request, work / 'worker', stop)
        result['worker'] = worker
        result['assets'] = []
        for asset in worker['assets']:
            source = output / asset['asset']
            result['assets'].append({**asset, **({'gaussian_source_path':str(output / asset['gaussian'])} if asset.get('gaussian') else {}), 'source_path': str(source),
                                     'source_frame': 'sam3d_camera', 'metric_reconstruction': False})
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
                '.gltf': 'mesh', '.ply': 'mesh', '.obj': 'mesh', '.npy': 'array',
                '.json': 'json'}.get(path.suffix.lower(), 'file')
    result['files'] = [{'file': path.relative_to(directory).as_posix(), 'source_path': str(path),
                        'kind': kind(path), 'bytes': path.stat().st_size}
                       for path in sorted(work.rglob('*')) if path.is_file()]
    write_json(directory / 'generation_stage.json', result)
    record_progress(directory, 'complete', tool=name)
    store.update(task['id'], state='SUCCEEDED', result=result, unit={**task['unit'], 'phase': 'complete'})
    return result
