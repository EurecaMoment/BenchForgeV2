"""Bounded, on-demand discovery with lossless copies in the task workspace."""
import json
from pathlib import Path
import re
import uuid
from service_access.runtime_config import environment_value
from capabilities.scene_authoring.catalog.capabilities import scene_contract_capabilities
from capabilities.scene_authoring.contracts.scene_program import SCENE_SCHEMA_DESCRIPTION
from capabilities.scene_authoring.catalog.native import ASSETS
from capabilities.scene_authoring.catalog.native import NATIVE_MATERIALS
from capabilities.scene_authoring.catalog.environments import ENVIRONMENTS
from capabilities.asset_generation.generation import GenerationTools

MAX_RESPONSE_BYTES = 16000
SECTIONS = {
    'overview': 'Workflow, permissions and available catalog sections',
    'contracts': 'Executable scene capabilities and feedback contracts',
    'scene_schema': 'Complete SceneProgram writing contract, in ordered text fragments',
    'native_assets': 'Installed USD kinds, dimensions and native appearance controls',
    'generated_assets': 'Reusable mesh metadata; item_id loads only that mesh geometry detail',
    'generation_tools': 'Independent image generation, segmentation, reconstruction, depth and mesh import',
    'materials': 'Registered texture materials with source/repeat preview paths for read_image',
    'environments': 'Registered HDR environments',
}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')


def _rows(value):
    if isinstance(value, dict):
        return [{'id': key, 'value': child} for key, child in value.items()]
    return [{'id': str(v.get('id', v.get('plugin_id', v.get('template_id', i)))) if isinstance(v, dict) else str(i), 'value': v}
            for i, v in enumerate(value)]


def _overview():
    return {
        'name': 'BenchForge', 'catalog_schema': 'benchforge.operator-catalog/v2',
        'simulator': 'configured Isaac Sim capture provider',
        'model': environment_value('BENCHFORGE_MODEL_ID') or 'unconfigured',
        'sections': SECTIONS, 'query': {'section': 'one listed section', 'query': 'case-insensitive literal substring; no semantic ranking',
            'item_id': 'exact listed id; use for full selected details', 'offset': 'use next_offset with the same filters',
            'limit': 'positive count, default 20; pages fit the response byte budget', 'workspace_id': 'optional lossless JSON copy of all matches'},
        'workflow': [
            'For a new scene, first generate or reuse a scene-wide diffusion design reference and inspect its image. Use an existing user reference when supplied. Choose benchforge_diffusion or the optional benchforge_layout pipeline; asset product images do not replace the scene reference. Use the reference to choose spatial composition, asset reuse or generation, material detail and lighting, then build SceneProgram and compare actual captures against it. Keep the reference available for later corrections; it is a design target, not geometry or GT.',
            'TRELLIS.2 returns Y-up PBR meshes. Register them with mesh_import, then choose their placement and physical dimensions.',
            'Independent tools produce images, masks, meshes and depth predictions. Read task evidence before using outputs.',
            'Optional pipelines: layout prepares a design reference; asset generates a registered asset; run plans, captures and exports a scene.',
            'Write SceneProgram with standard file tools or task_code and submit scene_program_path to preserve your design. Scene data, assets, lights and cameras are operator-controlled.',
            'Submitted ScenePrograms retain operator control after review: inspect screenshots and scene_review, then revise your program as needed. The run exports eligible data with its actual quality outcome; it does not launch an automatic rewriting planner. Text-only scene requests keep their existing automatic repair budget.',
            'Evidence displays reference images, masks and actual captures, including earlier revisions. source_path outputs connect tools without copying or regenerating files.',
            'Scene data derives from Isaac capture. Use benchforge_pipeline_catalog and data.capability for template-based dataset production.'
        ],
        'task_workspace': {'writable': '/workspace', 'read_only': ['/harness', '/assets'],
            'path_mapping': 'workspace_file is usable inside task_code; source_path is for service tool parameters',
            'authority_gt_mounted': False, 'host_network': False},
        'model_can_edit_harness_code': False, 'model_can_write_task_code': True,
        'target_model_evaluation': False,
        'quality': 'GT is official or simulator/program-derived. Status, registration and reviewer opinions do not certify photorealism or benchmark quality.',
        'copy_example': {'section': 'scene_schema', 'workspace_id': 'scene_design'},
    }


def _load_rows(store, section, item_id):
    if section=='generation_tools':
        tools = {
            'diffusion':{'tool':'benchforge_diffusion','inputs':'prompt; optional source_image for editing','outputs':'image source_path'},
            'sam3':{'tool':'benchforge_scene_sam3','inputs':'source_image and prompts or pixel box instances','outputs':'all masks, boxes and scores'},
            'trellis':{'tool':'benchforge_trellis','inputs':'source_image and objects with selected source_mask','outputs':'Y-up PBR meshes with unmeasured scale'},
            'depth':{'tool':'benchforge_depth','inputs':'source_image','outputs':'predicted depth arrays, camera parameters and visualization'},
            'mesh_import':{'tool':'benchforge_mesh_import','inputs':'source_mesh, label and source frame; optional source_gaussian','outputs':'registered asset_id and geometry'},
        }
        return _rows(tools)
    if section == 'contracts':
        return _rows({k: v for k, v in scene_contract_capabilities().items()
                      if k not in {'native_assets', 'texture_ids', 'environment_maps'}})
    if section == 'scene_schema':
        # Exact concatenation reconstructs the contract, including long registry lines.
        return [{'id': str(i // 2400), 'text': SCENE_SCHEMA_DESCRIPTION[i:i + 2400]}
                for i in range(0, len(SCENE_SCHEMA_DESCRIPTION), 2400)]
    if section in {'native_assets', 'materials', 'environments'}:
        values = {'native_assets': ASSETS, 'materials': NATIVE_MATERIALS, 'environments': ENVIRONMENTS}[section]
        records = {key: {k: v for k, v in value.items() if k not in {'path', 'textures', 'preview_file'}} for key, value in values.items()}
        if section == 'materials':
            for key, value in values.items():
                if value.get('preview_file'):
                    records[key]['preview'] = {
                        'source_path': str((Path(__file__).resolve().parents[1] / 'resources' / value['preview_file']).resolve()),
                        'task_code_path': '/harness/scene_production/scene_program/' + value['preview_file'],
                        'use': 'Open source_path with standard read_image, or task_code_path inside task_code.',
                        'content': 'Source base color and 2x2 repeats; not rendered PBR or measured reflectance.'}
        return _rows(records)
    if section == 'generated_assets':
        tools = GenerationTools(store.root)
        if item_id:
            # Filter first; never read every multi-megabyte mesh for an overview.
            return [{'id': value['asset_id'], 'value': value} for value in tools.catalog(asset_ids=[item_id])]
        result = []
        for path in sorted(tools.assets.glob('*/asset.json')):
            if path.is_symlink(): continue
            try: value = json.loads(path.read_text(encoding='utf8'))
            except (OSError, ValueError): continue
            result.append({'id': value.get('asset_id', path.parent.name),
                           'value': {key: value.get(key) for key in ('asset_id', 'label', 'prompt', 'size_bounds', 'source', 'status', 'geometry', 'physics', 'appearance')},
                           'detail': 'Use item_id for current mesh bounds and transported appearance; metadata does not prove semantic orientation.'})
        return result
    raise ValueError('Unknown BenchForge catalog section: ' + section)


def _copy(store, workspace_id, section, rows, filters):
    if not isinstance(workspace_id, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', workspace_id):
        raise ValueError('invalid workspace_id')
    base = store.root.resolve() / 'operator_workspaces'
    base.mkdir(exist_ok=True)
    if base.is_symlink(): raise ValueError('invalid workspace root')
    workspace = base / workspace_id
    workspace.mkdir(exist_ok=True)
    if workspace.is_symlink() or workspace.resolve().parent != base.resolve():
        raise ValueError('invalid workspace path')
    data = _encoded({'section': section, **filters, 'items': rows, 'scope': 'catalog metadata snapshot; not GT or verified scene quality'})
    name = 'catalog_' + section + '_' + uuid.uuid4().hex[:12] + '.json'
    target = workspace / name
    with target.open('xb') as output: output.write(data)
    return {'workspace_file': '/workspace/' + name, 'source_path': str(target), 'bytes': len(data),
            'items': len(rows), 'scope': 'lossless copy of all matches before pagination; original registries unchanged'}


def catalog_response(store, request):
    if not isinstance(request, dict) or set(request) - {'section', 'query', 'item_id', 'offset', 'limit', 'workspace_id'}:
        raise ValueError('catalog parameters: section, query, item_id, offset, limit, workspace_id')
    section = request.get('section', 'overview')
    if section not in SECTIONS: raise ValueError('unknown catalog section; choose ' + ', '.join(SECTIONS))
    query = request.get('query', ''); item_id = request.get('item_id')
    if not isinstance(query, str) or len(query) > 200: raise ValueError('query must be at most 200 characters')
    if item_id is not None and (not isinstance(item_id, str) or not 1 <= len(item_id) <= 300): raise ValueError('invalid item_id')
    offset = request.get('offset', 0); limit = request.get('limit', 20)
    if type(offset) is not int or offset < 0: raise ValueError('offset must be a nonnegative integer')
    if type(limit) is not int or limit < 1: raise ValueError('limit must be a positive integer')
    if section == 'overview':
        if query or item_id or offset: raise ValueError('choose a catalog section before filtering/paging')
        result = _overview()
        if request.get('workspace_id') is not None:
            result['copy'] = _copy(store, request['workspace_id'], section, [result.copy()], {})
        return result
    rows = _load_rows(store, section, item_id)
    if item_id is not None: rows = [r for r in rows if r['id'] == item_id]
    if query: rows = [r for r in rows if query.casefold() in _encoded(r).decode('utf8').casefold()]
    result = {'section': section, 'query': query, 'item_id': item_id, 'total_matches': len(rows),
              'offset': offset, 'items': [], 'next_offset': None, 'response_budget_bytes': MAX_RESPONSE_BYTES,
              'pagination': 'Repeat section/query/item_id with next_offset; ordering can change if assets are registered. workspace_id freezes all current matches.'}
    if request.get('workspace_id') is not None:
        result['copy'] = _copy(store, request['workspace_id'], section, rows, {'query': query, 'item_id': item_id})
    for index, row in enumerate(rows[offset:offset + limit], offset):
        # Reserve room for a continuation offset and an explicit oversized-record notice.
        result['items'].append(row)
        if len(_encoded(result)) > MAX_RESPONSE_BYTES - 512:
            result['items'].pop()
            if result['items']: break
            result['items'].append({'id': row['id'], 'inline_omitted': True, 'record_bytes': len(_encoded(row)),
                                    'reason': 'record exceeds inline budget; request workspace_id for the complete metadata',
                                    'copy_request': {'section': section, 'item_id': row['id'], 'workspace_id': 'catalog_inspect'}})
        result['next_offset'] = index + 1 if index + 1 < len(rows) else None
    assert len(_encoded(result)) <= MAX_RESPONSE_BYTES
    return result
