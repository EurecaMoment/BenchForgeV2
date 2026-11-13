"""Collect stage receipts for one composed pipeline review owner."""

from pathlib import Path

from ..artifact_io import read_json as read
from ..stage_review import STAGES
from . import canonical_identifier
from .artifact_graph import binding_roots

def stage_of(step):
    if step.get('review_stage') in ('S1','S2','S3','S4','S5'):
        return step['review_stage']
    return {'benchforge.start':'S2','benchforge.capture':'S2','benchforge.observe':'S2',
            'benchforge.refine':'S2','benchforge.extend':'S2','benchforge.asset':'S2','benchforge.evidence':'S3',
            'templates.produce':'S4','data.package':'S5'}.get(canonical_identifier(step['uses']))

def review_scope(plan, run_root, plan_path):
    """One review owner for the leaf artifacts of a composed production run."""
    members = {stage: [] for stage in STAGES[1:]}
    recipes = None

    def expand(steps, root, prefix=''):
        nonlocal recipes
        consumed = set()
        for step in steps:
            for source in binding_roots(step.get('arguments', {})):
                consumed.add(source)
        for step in steps:
            step_root = root/'steps'/step['id']
            label = prefix+step['id']
            if step['uses'] == 'pipeline':
                nested_root = step_root/'nested-run'
                saved = nested_root/'plan.json'
                if saved.exists():
                    nested_steps = read(saved)['steps']
                else:
                    if recipes is None:
                        from .catalog import pipeline_files
                        recipes = {recipe['id']: recipe for recipe in pipeline_files()}
                    nested_steps = recipes[step['pipeline_id']]['steps']
                expand(nested_steps, nested_root, label+'/')
            else:
                stage = stage_of(step)
                if stage in members:
                    members[stage].append({'step': step['id'], 'label': label, 'uses': canonical_identifier(step['uses']),
                        'run': str(root.resolve()), 'result_path': str((step_root/'result.json').resolve()),
                        'terminal': step['id'] not in consumed})

    expand(plan['steps'], run_root)
    return {'run': str(run_root.resolve()), 'plan': str(plan_path), 'members': members, 'continued_stages': []}

def completed_stage(scope, stage):
    """Receipts are retained, but a review needs every planned stage artifact."""
    members = scope['members'][stage]
    if not members:
        return None
    states = {}
    # The last planned artifact is usually unfinished; check it first so large
    # scene batches do not reread every completed scene on each submission.
    for member in reversed(members):
        root = member['run']
        if root not in states:
            path = Path(root)/'state.json'
            states[root] = read(path).get('steps', {}) if path.exists() else {}
        prior = states[root].get(member['step'])
        if not prior or prior['state'] != 'completed':
            return None
    outputs = []
    for member in members:
        result_path = Path(member['result_path'])
        if not result_path.is_file():
            return None
        result = read(result_path)
        if member['terminal'] and result.get('state') in ('RUNNING', 'READY'):
            return None
        outputs.append({'step': member['label'], 'uses': member['uses'],
                        'result_path': member['result_path'], 'result': result})
    return outputs
