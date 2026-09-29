"""A durable diffusion design stage that finishes before task-authored geometry."""
import json
from .layout import default_layout, validate_layout, prepare_layout
from .generation import GenerationTools
from .progress import record_progress


def design_directory(store, layout):
    task_id = (layout or {}).get('design_task_id')
    if not task_id:
        return None
    validate_layout(layout)
    snapshot = store.snapshot(task_id.split('.')[0])
    task = next((t for t in snapshot['tasks'] if t['id'] == task_id), None)
    if not task or task['unit'].get('workflow') != 'layout':
        raise ValueError('design_task_id must identify a spatialforge_layout task')
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
              'reference': {'tool': 'spatialforge_evidence', 'task_id': task['id'], 'file': 'layout/reference.png'},
              'scene_layout': {'mode': 'reference', 'design_task_id': task['id']}, 'receipt': receipt,
              'next_action': 'inspect_reference_then_write_scene_program'}
    record_progress(directory, 'complete', role='design_reference_only')
    store.update(task['id'], state='SUCCEEDED', result=result, unit={**task['unit'], 'phase': 'complete'})
