"""Diffusion layout references guide proposals; they never become simulator GT."""
import json
import shutil
import re
from pathlib import Path
from PIL import Image
from service_access.artifacts import write_json
from scene_production.server.asset_generation.generation import GenerationTools
from scene_production.server.asset_generation.generation import generation_defaults
from scene_production.server.asset_generation.generation import _file_record
from service_access.progress import record_progress


def default_layout(intent):
    """New scenes begin with a visible design brief; explicit references take priority."""
    return {'mode':'generate','prompt':'Real interior architectural photograph, slightly elevated wide three-quarter perspective showing the complete room layout, major objects, useful aisles and credible support surfaces. Natural window illumination with soft indirect light, contact shadows, restrained highlights retaining texture. Distinct ceramic, metal, wood and fabric roughness; subtle wear and material grain, realistic scale, recognizable object shapes. Show the functional character of a room in real use. Photographic realism, not a floor plan, sketch, watercolor, text-labelled diagram, toy scene or plastic CGI. Scene brief: '+intent['description'][:5000]}


def validate_layout(spec):
    if not isinstance(spec,dict) or set(spec)-{'mode','prompt','source_image','source_view','seed','design_task_id'}:
        raise ValueError('invalid layout guidance fields')
    mode=spec.get('mode')
    if 'design_task_id' in spec:
        if mode!='reference' or set(spec)-{'mode','design_task_id'} or not isinstance(spec['design_task_id'],str) or not re.fullmatch(r'sf_[a-f0-9]{16}\.scene\d+',spec['design_task_id']):
            raise ValueError('design_task_id requires mode=reference and a completed layout task ID, with no other source fields')
    if mode not in {'generate','edit','reference'}:raise ValueError('layout mode must be generate, edit or reference')
    if mode!='reference' and (not isinstance(spec.get('prompt'),str) or not 1<=len(spec['prompt'])<=6000):
        raise ValueError('generated or edited layout needs a visual prompt')
    if 'source_image' in spec and (not isinstance(spec['source_image'],str) or not spec['source_image']):
        raise ValueError('layout source_image must be a registered file path')
    if 'source_view' in spec and (type(spec['source_view']) is not int or not 0<=spec['source_view']<=11):
        raise ValueError('layout source_view must be a captured view index 0..11')
    if 'source_image' in spec and 'source_view' in spec:raise ValueError('choose one layout image source')
    if mode=='generate' and ('source_image' in spec or 'source_view' in spec):raise ValueError('generate mode has no source image; use edit')
    if type(spec.get('seed',42)) is not int or not 0<=spec.get('seed',42)<2**32:raise ValueError('invalid layout seed')
    return spec


def prepare_layout(tools,intent,directory,stop,parent_directory=None,design_directory=None):
    spec=intent.get('layout')
    inherited=None
    prepared=None
    if spec and spec.get('design_task_id'):
        validate_layout(spec)
        if design_directory is None:raise ValueError('design_task_id must be resolved to a completed layout task')
        original=json.loads((design_directory/'layout_reference.json').read_text())
        if original.get('role')!='design_reference_only' or original.get('gt_source') is not False:
            raise ValueError('prepared reference lacks design-only provenance')
        prepared={'design_task_id':spec['design_task_id'],'reference_receipt':original}
    if spec is None:
        if parent_directory is None:return None
        inherited_image=parent_directory/'layout_reference.png'
        inherited_receipt=parent_directory/'layout_reference.json'
        if not inherited_image.exists() and not inherited_receipt.exists():return None
        if not inherited_image.is_file() or not inherited_receipt.is_file():raise ValueError('parent design reference is incomplete; supply an explicit layout source')
        original=json.loads(inherited_receipt.read_text())
        if original.get('role')!='design_reference_only' or original.get('gt_source') is not False:raise ValueError('parent reference lacks design-only provenance')
        spec={'mode':'reference','source_image':str(inherited_image)}
        inherited={'parent_revision_path':str(parent_directory),'reference_receipt':original}
    validate_layout(spec)
    record_progress(directory,'layout_reference',mode=spec['mode'])
    # A task's quality/engineering retries share one frozen design reference.
    work=directory.parent/'layout';work.mkdir(parents=True,exist_ok=True)
    source=None
    if prepared:source=design_directory/'layout_reference.png'
    elif inherited:source=inherited_image  # Parent path was resolved by the trusted scene lineage.
    elif spec.get('source_image'):source=tools.source_path(spec['source_image'])
    elif spec['mode'] in {'edit','reference'}:
        if parent_directory is None:raise ValueError('layout edit/reference needs source_image or a captured parent scene')
        source=parent_directory/'capture'/f'view_{spec.get("source_view",0)}.png'
        if not source.is_file():raise ValueError('requested layout source view is unavailable')
    contract={'spec':spec,'source':_file_record(source) if source else None}
    contract_file=work/'contract.json'
    if contract_file.exists() and json.loads(contract_file.read_text())!=contract:
        raise ValueError('layout source or request changed; create a new scene task')
    write_json(contract_file,contract)
    image=work/'reference.png';receipt=work/'receipt.json'
    if not receipt.exists():
        if stop.is_set():raise RuntimeError('layout generation canceled')
        if spec['mode']=='reference':
            with Image.open(source) as original:original.convert('RGB').save(image)
            tool='prepared_design_reference' if prepared else 'inherited_design_reference' if inherited else 'source_image'
        else:
            prompt=spec['prompt']+'\nCreate a coherent spatial design reference, with readable room layout and furniture relationships. No text labels or invented numeric measurements. This image is a design proposal, not ground truth or a validated simulation.'
            if spec['mode']=='edit':prompt+=' Preserve relevant existing structure and implement the requested layout changes in the supplied view.'
            defaults = generation_defaults('diffusion')
            request = {**defaults, 'prompt': prompt, 'output': str(image), 'seed': spec.get('seed', defaults['seed'])}
            if source:request['image']=str(source)
            generated=tools.execute('diffusion',request,work/'diffusion',stop)
            tool=generated['model']
        with Image.open(image) as result:size=list(result.size)
        write_json(receipt,{'schema':'benchforge_backend.layout-reference/v1','mode':spec['mode'],'tool':tool,'image':'layout_reference.png',
                           'source':contract['source'],'size':size,'seed':spec.get('seed',42),
                           'role':'design_reference_only','metric_layout_verified':False,'gt_source':False,
                           **({'inherited_from':inherited} if inherited else {}),
                           **({'prepared_from':prepared} if prepared else {}),
                           'limitations':['Image edits do not prove preservation of existing 3D geometry.',
                                          'SceneProgram and desktop Isaac determine actual dimensions, collisions and GT.',
                                          'Unseen geometry and objects may differ from the design image.']})
    if not image.is_file() or not image.stat().st_size:raise ValueError('layout receipt has no image')
    result=json.loads(receipt.read_text())
    shutil.copy2(image,directory/'layout_reference.png')
    write_json(directory/'layout_reference.json',result)
    return directory/'layout_reference.png'


def design_directory(store, layout):
    task_id = (layout or {}).get('design_task_id')
    if not task_id:
        return None
    validate_layout(layout)
    snapshot = store.snapshot(task_id.split('.')[0])
    task = next((t for t in snapshot['tasks'] if t['id'] == task_id), None)
    if not task or task['unit'].get('workflow') != 'layout':
        raise ValueError('design_task_id must identify a benchforge_layout task')
    if snapshot['state'] != 'SUCCEEDED' or task['state'] != 'SUCCEEDED':
        raise ValueError('design reference is not complete; use status/wait on its existing run')
    directory = store.root / task_id / f"revision_{task['unit']['revision']}"
    if not (directory / 'layout_reference.png').is_file() or not (directory / 'layout_reference.json').is_file():
        raise ValueError('completed design has no reference image/receipt')
    return directory


def require_prior_reference(store, intent, parent_directory=None):
    """Validate an explicit reference; the pipeline generates omitted references."""
    design_directory(store, intent.get('layout'))


def start_design_request(store, value):
    if not isinstance(value, dict) or set(value) - {'request_key', 'name', 'description', 'layout'}:
        raise ValueError('layout request fields: request_key, name, description, optional layout')
    for key, limit in (('request_key', 200), ('name', 200), ('description', 12000)):
        if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= limit:
            raise ValueError('invalid layout ' + key)
    layout = validate_layout(value.get('layout') or default_layout(value))
    if 'source_view' in layout or (layout['mode'] != 'generate' and not layout.get('source_image')):
        raise ValueError('standalone edit/reference needs source_image; copy a prior PNG with evidence and workspace_id')
    intent = {'name': value['name'], 'description': value['description'], 'layout': layout}
    return {'run_id': store.submit(value['request_key'], [intent], 'layout'), 'state': 'accepted',
            'workflow': 'layout', 'next_action': 'wait_then_inspect_design', 'gt_source': False}


def execute_design(store, task, stop):
    directory = store.directory(task['id'], task['unit']['revision'])
    prepare_layout(GenerationTools(store.root), task['unit']['intent'], directory, stop)
    receipt = json.loads((directory / 'layout_reference.json').read_text())
    result = {'role': 'design_reference_only', 'gt_source': False, 'simulator_capture': False,
              'reference': {'tool': 'benchforge_scene_evidence', 'task_id': task['id'], 'file': 'layout/reference.png'},
              'scene_layout': {'mode': 'reference', 'design_task_id': task['id']}, 'receipt': receipt,
              'next_action': 'inspect_reference_then_write_scene_program'}
    record_progress(directory, 'complete', role='design_reference_only')
    store.update(task['id'], state='SUCCEEDED', result=result, unit={**task['unit'], 'phase': 'complete'})
