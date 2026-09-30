"""Diffusion layout references guide proposals; they never become simulator GT."""
import json
import os
import shutil
import re
from pathlib import Path
from PIL import Image
from benchclaw.store import write_json
from .generation import _file_record
from .progress import record_progress


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
            model_path=os.environ.get('SPATIALFORGE_DIFFUSION_MODEL') or tools.config.model('flux')['path']
            request={'model_path':model_path,'prompt':prompt,'output':str(image),'width':1024,'height':768,'steps':4,'seed':spec.get('seed',42)}
            if source:request['image']=str(source)
            generated=tools.execute('diffusion',request,work/'diffusion',stop)
            tool=generated.get('model') or Path(model_path).name
        with Image.open(image) as result:size=list(result.size)
        write_json(receipt,{'schema':'spatialforge.layout-reference/v1','mode':spec['mode'],'tool':tool,'image':'layout_reference.png',
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
