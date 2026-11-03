"""One model-facing assessment template and deterministic design checks."""
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path


def assessment_template():
    return json.loads(Path(__file__).with_name('assessment_template.json').read_text(encoding='utf-8'))


def validate_assessment(value, selections, inputs):
    if not isinstance(value, dict) or value.get('schema') != 'spatialforge.assessment/v1':
        raise ValueError('assessment.schema must be spatialforge.assessment/v1')
    outline = assessment_template()['assessment']

    def check(actual, expected, path):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise ValueError(f'{path} must be an object')
            for key, child in expected.items():
                if key not in actual:
                    raise ValueError(f'Missing {path}.{key}; fill the assessment template')
                check(actual[key], child, f'{path}.{key}')
        elif isinstance(expected, list):
            if not isinstance(actual, list) or (expected and not actual):
                raise ValueError(f'{path} must be a filled array')
            for index, child in enumerate(actual):
                if expected:
                    check(child, expected[0], f'{path}[{index}]')
        elif expected == '':
            if not isinstance(actual, str) or not actual.strip() or actual.strip().lower() in ('todo', 'tbd', '待填写'):
                raise ValueError(f'{path} needs concrete text')

    # An empty selection_path is valid when no scene catalog is attached.
    outline['scenes'].pop('selection_path')
    check(value, outline, 'assessment')
    expected_counts = Counter()
    for row in selections:
        ids, count = row['template_ids'], row['count']
        if not ids or type(count) is not int or count < len(ids):
            raise ValueError('Each selection count must cover its templates at least once')
        for index, tid in enumerate(ids):
            expected_counts[tid] += count // len(ids) + (index < count % len(ids))
    coverage = Counter()
    objectives = {row['id'] for row in value['objectives']}
    for row in value['coverage']:
        if row['objective_id'] not in objectives:
            raise ValueError('coverage.objective_id must reference a declared objective')
        if type(row['count']) is not int or row['count'] <= 0:
            raise ValueError('coverage.count must be a positive integer')
        coverage[row['template_id']] += row['count']
    if coverage != expected_counts:
        raise ValueError('assessment.coverage counts must match pipeline selections per template')
    target = value['dataset']['target_items']
    if type(target) is not int or target != sum(coverage.values()):
        raise ValueError('assessment.dataset.target_items must equal the allocated item count')
    if 'target_items' in inputs and inputs['target_items'] != target:
        raise ValueError('assessment target_items conflicts with pipeline inputs')
    if 'seed' in inputs and inputs['seed'] != value['dataset']['seed']:
        raise ValueError('assessment dataset.seed conflicts with pipeline inputs')
    scenes = value['scenes']
    if type(scenes['allow_new_scenes']) is not bool:
        raise ValueError('scenes.allow_new_scenes must be a boolean')
    if not scenes['allow_new_scenes'] and not scenes['selected_scenes']:
        raise ValueError('A reuse-only assessment must reference selected scenes')
    if scenes['target_scene_count'] is not None and (type(scenes['target_scene_count']) is not int or scenes['target_scene_count'] <= 0):
        raise ValueError('scenes.target_scene_count must be a positive integer or null')
    if type(value['dataset']['seed']) is not int:
        raise ValueError('dataset.seed must be an integer')
    selection = inputs.get('scene_selection')
    if selection:
        allowed = selection.get('selected_scenes', selection.get('sources', []))
        allowed_ids = {(row.get('task_id', row.get('id')), row.get('revision')) for row in allowed}
        chosen_ids = {(row.get('task_id', row.get('id')), row.get('revision')) for row in scenes['selected_scenes']}
        if scenes['allow_new_scenes'] != selection.get('allow_new_scenes') or not chosen_ids <= allowed_ids:
            raise ValueError('assessment.scenes must honor the saved scene selection and revisions')
        if scenes.get('selection_path') != selection.get('selection_path'):
            raise ValueError('assessment.scenes.selection_path must match the saved selection')
    if {row['template_id'] for row in value['scoring']['metrics']} != set(coverage):
        raise ValueError('scoring.metrics must cover exactly the selected templates')
    stages = {'S1', 'S2', 'S3', 'S4', 'S5'}
    if {row['stage'] for row in value['execution']} != stages:
        raise ValueError('assessment.execution must cover S1 through S5')
    if {row['stage'] for row in value['delivery']['artifacts']} != stages:
        raise ValueError('assessment.delivery must declare viewable artifacts for all five stages')
    return deepcopy(value)
