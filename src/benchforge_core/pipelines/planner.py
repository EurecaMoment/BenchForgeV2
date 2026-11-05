"""Agent-owned semantic decomposition, deterministic IDs and executable recipes."""
import re
import json
from copy import deepcopy
from pathlib import Path
from ..runtime import write
from .catalog import all_templates, capability_id, selected_templates, pipeline_files, relevance
from .adapters import supports
from .assessment import validate_assessment
from .plan_versions import current,activate,verify_application
from .plan_input import resolve_request, FIELDS


def plan(args, directory, config=None):
    args, authoring_sources = resolve_request(args, Path(directory).parents[1])
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
    value = {'schema': 'spatialforge.pipeline/v1', 'version': 1, 'pipeline_id': recipe,
             'objective': objective, 'inputs': inputs, 'steps': pipeline['steps'], 'selections': selections,
             'template_contracts': [{k: catalog[tid][k] for k in ('id', 'task_id', 'task_name', 'protocol_id', 'parameters', 'effective_measurement_conditions', 'output_schema', 'catalog_capability_links')} | {'execution': supports(tid)} for tid in dict.fromkeys(tid for s in selections for tid in s['template_ids'])]}
    if args.get('assessment') is not None:
        try:
            value['assessment'] = validate_assessment(args['assessment'], selections, inputs)
        except ValueError as error:
            if not authoring_sources:
                draft = Path(directory) / 'plan-request-draft.json'
                write(draft, {key: value for key, value in args.items() if key in FIELDS})
                authoring_sources['request_path'] = str(draft.resolve())
            if not args.get('validate_only'):
                raise ValueError(str(error) + '\nSaved authoring sources: ' + json.dumps(authoring_sources)
                                 + '\nPatch the source file and resubmit its path.') from error
            return {'state': 'needs_plan_revision', 'issues': getattr(error, 'issues', [str(error)]),
                    'authoring_sources': authoring_sources,
                    'next': 'Edit only the listed fields in the existing source file. Validate again using the same path; do not regenerate the whole document.'}
    elif args.get('validate_only'):
        return {'state': 'needs_plan_revision', 'issues': ['Provide assessment_path or assessment for validation']}
    if authoring_sources:
        value['authoring_sources'] = authoring_sources
    session = args.get('_dsh_context', {}).get('session_id')
    workspace=Path(directory).parents[1]
    active=current(workspace,session) if session else None
    edit=args.get('_plan_edit')
    application_resolution=None
    if not edit:
        application_resolution=verify_application(active,args)
        if active and active['pending']:
            edit_plan=json.loads(Path(active['plan']).read_text(encoding='utf-8'))
            value['edit_revision']=deepcopy(edit_plan.get('edit_revision',{}))
            if application_resolution is not None:
                value['edit_revision']['markdown_resolution']=deepcopy(application_resolution)
                value['markdown_resolution']=deepcopy(application_resolution)
    if edit:value['edit_revision']=deepcopy(edit)
    markdown=args.get('_user_markdown',args.get('user_markdown'))
    if markdown is not None and (not isinstance(markdown,str) or not markdown.strip() or len(markdown)>512_000):
        raise ValueError('user_markdown must be a non-empty document no larger than 512 KB')
    if args.get('validate_only'):
        return {'state': 'validated', 'authoring_sources': authoring_sources,
                'target_items': value['assessment']['dataset']['target_items'],
                'next': 'Submit the same file path with validate_only=false to save the plan and open S1 review.'}
    if markdown is not None:
        value['user_markdown']=markdown
        markdown_path=Path(directory)/'assessment-plan.md'
        markdown_path.write_text(markdown,encoding='utf-8',newline='')
        value['user_markdown_path']=str(markdown_path.resolve())
        if edit:
            value['edit_revision']['markdown_path']=str(markdown_path.resolve())
    if args.get('applies_edit'):value['applies_edit']=args['applies_edit']
    target = Path(directory)/'plan.json'
    write(target, value)
    if session and (active or edit):
        activate(workspace,session,str(target.resolve()),expected=edit['base_plan'] if edit else active['plan'],
                 pending=bool(edit),changes=edit['changes'] if edit else ())
    review = None
    # A saved edit still needs executable application. Its final applied plan
    # owns S1; opening a draft window here would make the user wait twice.
    if session and not edit:
        from ..stage_review import gate
        review = gate(Path(directory).parents[1], session, 'S1', str(target.resolve()), str(target.resolve()))
    unsupported = [t['id'] for t in value['template_contracts'] if not t['execution']['program_generator']]
    return {'state': 'planned', 'plan': str(target.resolve()), 'pipeline_id': recipe,
            'stage_review': review,
            'assessment_status': 'structured' if value.get('assessment') else 'legacy_summary',
            'selections': selections, 'evidence_required_for': unsupported,
            'next': ('Apply the saved user edit with pipeline_plan(applies_edit=plan) before pipeline_run. S1 review opens after the executable application is validated.'
                     if edit else 'pipeline_run; when evidence is required, use exact template protocol with task code or existing collectors, then supply evidence. No legacy 3240-template substitution.')}
