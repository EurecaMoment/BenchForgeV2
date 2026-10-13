"""Agent-owned semantic decomposition, deterministic IDs and executable recipes."""
import re
from copy import deepcopy
from pathlib import Path
from ..runtime import write
from .catalog import all_templates, capability_id, selected_templates, pipeline_files, relevance
from .adapters import supports


def plan(args, directory, config=None):
    catalog = {t['id']: t for t in all_templates()}
    objective = args.get('objective', '')
    selectors = {k: args[k] for k in ('capability', 'capabilities', 'template_ids', 'task_ids') if args.get(k)}
    selections = deepcopy(args.get('selections', []))
    if not selectors and not selections:
        tids = re.findall(r'\b(?:C\d{2}|P\d{3})-T\d{2}\b', objective, re.I)
        tasks = re.findall(r'\b(?:C\d{2}|P\d{3})\b(?!-T)', objective, re.I)
        caps = re.findall(r'\bN\d{1,2}\b', objective, re.I)
        if tids:
            selectors['template_ids'] = [t.upper() for t in tids]
        elif tasks:
            selectors['task_ids'] = [t.upper() for t in tasks]
        elif caps:
            selectors['capabilities'] = [capability_id(c) for c in caps]
    recipe = args.get('pipeline_id')
    if not recipe:
        recipe = 'data.capability'
    definitions = {p['id']: p for p in pipeline_files()}
    if recipe not in definitions:
        raise ValueError(f'Unknown pipeline {recipe}')
    inputs = deepcopy(args.get('inputs', {}))
    inputs.update({k: args[k] for k in ('evidence', 'seed', 'split', 'service_config') if k in args})
    pipeline = deepcopy(definitions[recipe])
    if args.get('steps'):
        pipeline['steps'] = deepcopy(args['steps'])
    candidates = []
    if recipe == 'data.capability' and not args.get('steps'):
        if not selections and selectors:
            chosen = selected_templates(selectors)
            if not chosen:
                raise ValueError('No document templates match the explicit selection')
            ids = [t['id'] for t in chosen]
            selections = [{'template_ids': ids, 'count': args.get('target_items', max(30, len(ids))),
                           'reason': 'Explicit user capability/task/template selection; catalog links retained.'}]
        if not selections:
            candidates = sorted([t for t in catalog.values() if relevance(t, objective)], key=lambda t: relevance(t, objective), reverse=True)[:12]
            # The caller is the DSH semantic agent; lexical search only retrieves candidates.
            return {'state': 'needs_template_selection', 'objective': objective,
                    'candidates': [{'id': t['id'], 'task': t['task_name'], 'title': t['title'], 'conditions': t['effective_measurement_conditions'], 'execution': supports(t['id'])} for t in candidates],
                    'next': 'DSH interprets the objective, reads exact template contracts and calls pipeline_plan again with selections=[{template_ids,count,reason}]. Retrieval scores do not define capability or authorize a measurement substitute.'}
        for selection in selections:
            if not selection.get('reason'):
                raise ValueError('Record why each template set answers the user objective')
            for tid in selection['template_ids']:
                if tid not in catalog:
                    raise ValueError(f'Unknown template {tid}')
        inputs.update(selections=selections, split=inputs.get('split', 'train'), seed=inputs.get('seed', 20261013))
        pipeline['steps'][0]['arguments'] = {'selections': '$inputs.selections', 'evidence': '$inputs.evidence', 'seed': '$inputs.seed', 'split': '$inputs.split'}
    value = {'schema': 'spatialforge.pipeline/v1', 'version': 1, 'pipeline_id': recipe,
             'objective': objective, 'inputs': inputs, 'steps': pipeline['steps'], 'selections': selections,
             'template_contracts': [{k: catalog[tid][k] for k in ('id', 'task_id', 'task_name', 'protocol_id', 'parameters', 'effective_measurement_conditions', 'output_schema', 'catalog_capability_links')} | {'execution': supports(tid)} for tid in dict.fromkeys(tid for s in selections for tid in s['template_ids'])]}
    target = Path(directory)/'plan.json'
    write(target, value)
    unsupported = [t['id'] for t in value['template_contracts'] if not t['execution']['program_generator']]
    return {'state': 'planned', 'plan': str(target.resolve()), 'pipeline_id': recipe,
            'selections': selections, 'evidence_required_for': unsupported,
            'next': 'pipeline_run; when evidence is required, use exact template protocol with task code or existing collectors, then supply evidence. No legacy 3240-template substitution.'}
