"""Instantiate exact document templates from program worlds or recorded evidence."""
import json
import re
import shutil
import sqlite3
import zipfile
from collections import Counter
from contextlib import closing
from pathlib import Path
from ..runtime import read, write, rows, jsonl, select
from .catalog import all_templates, document
from .adapters import BUILTINS, generate


def counts_for(selections):
    counts = Counter()
    for selection in selections:
        ids, count = selection['template_ids'], selection['count']
        if not ids or type(count) is not int or count < len(ids):
            raise ValueError('Each selection count must cover its explicitly selected templates at least once')
        for i, tid in enumerate(ids):
            counts[tid] += count//len(ids) + (i < count % len(ids))
    return counts


def bind_record(template, row, base):
    source = row['provenance']
    if source['kind'] not in ('program', 'simulation', 'official'):
        raise ValueError('Template GT must come from program, simulation or official evidence')
    path = Path(source['path'])
    if not path.is_absolute():
        path = base/path
    raw = read(path)
    answer = select(raw, row['answer_selector'])
    # Source stores actual checks and the instantiated protocol version, not model votes.
    admission = select(raw, row['admission_selector'])
    if admission.get('protocol_id') != template['protocol_id'] or admission.get('template_id') != template['id']:
        raise ValueError('Evidence admission must bind this exact protocol and template')
    required = ('information_sufficient', 'oracle_executed', 'media_consistent', 'no_answer_leakage')
    if not all(admission.get(key) is True for key in required):
        raise ValueError('Source evidence did not pass template admission checks')
    if template['protocol']['interaction_required'] and not admission.get('episode_executed'):
        raise ValueError('Interactive template needs a real recorded episode, not a static action answer')
    if template['protocol']['history_access_required'] and not row.get('history_access_mode'):
        raise ValueError('History template needs a frozen history access mode')
    media = [Path(p) if Path(p).is_absolute() else base/p for p in row.get('media', [])]
    return {'parameters': row['parameters'], 'media': media, 'source': raw, 'oracle': answer,
            'provided_information': row['provided_information'], 'oracle_version': row['oracle_version'],
            'reference_frame': row['reference_frame'], 'source_provenance': {**source, 'path': str(path.resolve()), 'answer_selector': row['answer_selector'], 'admission_selector': row['admission_selector']},
            'history_access_mode': row.get('history_access_mode'), 'admission': admission}


def produce(args, directory, config=None):
    templates = {r['id']: r for r in all_templates()}
    counts = counts_for(args['selections'])
    if set(counts)-set(templates):
        raise ValueError('Unknown template IDs; choose exact IDs from pipeline_catalog')
    root = Path(directory)/'dataset'
    root.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(args['evidence']).resolve() if args.get('evidence') else None
    records = rows(evidence_path) if evidence_path else []
    public, authority, rejected = [], [], []
    usage = Counter()
    seed = args.get('seed', 20261013)
    split = args.get('split', 'train')
    if split not in ('train', 'dev', 'test', 'sealed'):
        raise ValueError('split must be train, dev, test or sealed')
    for tid, count in counts.items():
        template = templates[tid]
        candidates = [r for r in records if r['template_id'] == tid]
        using_source = bool(candidates) or tid not in BUILTINS
        if using_source and len(candidates) < count:
            rejected.append({'template_id': tid, 'reason': 'source_record_shortfall', 'requested': count, 'available': len(candidates)})
        if not candidates and tid not in BUILTINS:
            rejected.append({'template_id': tid, 'reason': 'task_specific_evidence_required', 'requested': count,
                             'next': 'Use task code / official source / existing Isaac queue; write evidence JSONL with exact parameters, media and source selectors.'})
            continue
        attempts = 0
        limit = min(count, len(candidates)) if using_source else count
        while usage[tid] < limit:
            attempts += 1
            if attempts > count*20:
                rejected.append({'template_id': tid, 'reason': 'admission_attempt_budget_exhausted'})
                break
            item_id = f'item_{len(public):08}'
            media_dir = root/'media'/item_id
            if using_source:
                row = candidates[usage[tid]]
                sample = bind_record(template, row, evidence_path.parent)
                group = row['scene_group_id']
                item_split = row.get('split', split)
                if item_split != split:
                    raise ValueError('Evidence split is immutable; select records from the requested partition')
            else:
                world_seed = seed+attempts-1
                sample = generate(tid, world_seed, media_dir)
                if sample is None:
                    continue
                # All variants derived from the same task world stay in one partition.
                group = f'program-v1:{template["task_id"]}:{world_seed}'
                item_split = split
            missing = {p['name'] for p in template['parameters']}-set(sample['parameters'])
            if missing:
                raise ValueError(f'{tid} parameters missing: {sorted(missing)}')
            question = template['prompt_template'].format_map({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v) for k, v in sample['parameters'].items()})
            if re.search(r'\{[A-Za-z_][\w]*\}', question):
                raise ValueError('Unbound template parameter')
            # Workspace ledger prevents train/test reassignment across resumed or separate plans.
            ledger = Path(args['_workspace'])/'pipeline-groups.sqlite'
            with closing(sqlite3.connect(ledger)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS groups (id TEXT PRIMARY KEY, split TEXT)')
                old = db.execute('SELECT split FROM groups WHERE id=?', (group,)).fetchone()
                if old and old[0] != item_split:
                    raise ValueError(f'Scene group {group} already belongs to {old[0]}; derivatives cannot cross splits')
                db.execute('INSERT OR IGNORE INTO groups VALUES (?,?)', (group, item_split))
            media = []
            media_dir.mkdir(parents=True, exist_ok=True)
            for index, source_media in enumerate(sample['media']):
                if not source_media.is_file():
                    raise ValueError(f'Missing media: {source_media}')
                target = media_dir/f'observation_{index}{source_media.suffix}'
                if source_media.resolve() != target.resolve():
                    shutil.copy2(source_media, target)
                media.append(target.relative_to(root).as_posix())
            private_source = root/'authority'/'sources'/f'{item_id}.json'
            write(private_source, sample['source'])
            public.append({'item_id': item_id, 'task_id': template['task_id'], 'template_id': tid,
                           'protocol_id': template['protocol_id'], 'protocol_version': template['protocol']['version'],
                           'measurement_variant': template['measurement_variant'], 'primary_operation': template['operation'],
                           'catalog_capability_links': template['catalog_capability_links'],
                           'provided_information': sample['provided_information'], 'scene_group_id': group,
                           'split': item_split, 'question': question, 'media': media,
                           'output_schema': template['output_schema'], 'reference_frame': sample['reference_frame'],
                           'history_access_mode': sample.get('history_access_mode')})
            authority.append({'item_id': item_id, 'template_id': tid, 'answer': sample['oracle'],
                              'oracle_version': sample['oracle_version'], 'source': private_source.relative_to(root).as_posix(),
                              'source_provenance': sample.get('source_provenance', {'kind': 'program', 'generator': 'pipeline-program-v1', 'seed': seed+attempts-1}),
                              'measurement_conditions': template['effective_measurement_conditions'],
                              'scoring_contract': template['effective_scoring'], 'admission': sample.get('admission', {'template_id': tid, 'protocol_id': template['protocol_id'], 'information_sufficient': True, 'oracle_executed': True, 'media_consistent': True, 'no_answer_leakage': True}),
                              'validation_scope': 'source_declared_admission' if using_source else 'controlled_program_world',
                              'tolerance': args.get('tolerance', {'absolute': .02, 'relative': .05, 'status': 'frozen_for_this_generated_dataset; not official-source thresholds'})})
            usage[tid] += 1
    jsonl(root/'questions.jsonl', public)
    jsonl(root/'authority.jsonl', authority)
    truth = {r['item_id']: r['answer'] for r in authority}
    jsonl(root/'sft.jsonl', [{'item_id': r['item_id'], 'messages': [{'role': 'user', 'content': r['question']}, {'role': 'assistant', 'content': json.dumps(truth[r['item_id']], ensure_ascii=False)}], 'images': r['media']} for r in public if r['split'] == 'train'])
    write(root/'protocols.json', {'common': document()['common_protocol'], 'templates': [templates[t] for t in counts]})
    report = {'requested': sum(counts.values()), 'accepted': len(public), 'shortfall': sum(counts.values())-len(public),
              'per_template': dict(usage), 'requested_per_template': dict(counts), 'split': split,
              'scene_groups': len({r['scene_group_id'] for r in public}), 'rejections': rejected,
              'source': document()['meta']['version'], 'benchmark_approved': False,
              'capability_scope': 'document task operations and measurement variants; links are not validated mastery',
              'state': 'completed' if len(public) == sum(counts.values()) else 'needs_evidence'}
    if report['shortfall']:
        specification = root/'production_spec.json'
        write(specification, {'templates': [templates[tid] | {'missing_items': counts[tid]-usage[tid]} for tid in counts if counts[tid] > usage[tid]],
                             'common_protocol': document()['common_protocol'],
                             'evidence_record': {'template_id': 'exact imported template ID', 'parameters': 'all prompt parameters; answers and hidden state excluded', 'media': 'public observation paths', 'provided_information': 'explicit public information list', 'provenance': {'kind': 'program|simulation|official', 'path': 'source JSON path'}, 'answer_selector': 'JSON Pointer into source oracle result', 'admission_selector': 'JSON Pointer into source admission record', 'oracle_version': 'implemented oracle version', 'reference_frame': 'explicit axes/units', 'scene_group_id': 'underlying scene/history/trajectory group, not just per-question seed', 'split': split},
                             'required_admission_fields': ['template_id', 'protocol_id', 'information_sufficient', 'oracle_executed', 'media_consistent', 'no_answer_leakage'],
                             'interactive_addition': 'episode_executed=true with recorded real action/observation/terminal trace; history tasks freeze history_access_mode',
                             'next': 'DSH writes task-specific generator/oracle in task workspace, uses existing capture/evidence interfaces when simulation is required, then resumes with evidence JSONL.'})
        report['production_spec'] = str(specification.resolve())
    write(root/'quality_report.json', report)
    return {'dataset': str(root.resolve()), 'report': str((root/'quality_report.json').resolve()), **report}


def package(args, directory, config=None):
    root = Path(args['dataset']).resolve()
    report = read(root/'quality_report.json')
    if report['shortfall']:
        raise ValueError('Dataset has a template shortfall; supply missing evidence before publishing')
    media = sorted({root/media for row in rows(root/'questions.jsonl') for media in row['media']})
    public_files = [root/'questions.jsonl', *media]
    private_files = [root/'authority.jsonl', root/'protocols.json', root/'quality_report.json', *[p for p in (root/'authority').rglob('*') if p.is_file()]]
    bundles = {}
    for kind, files in [('public', public_files), ('authority', private_files)]:
        target = Path(directory)/f'{kind}_bundle.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.relative_to(root))
        bundles[kind+'_bundle'] = str(target.resolve())
    if report['split'] == 'train':
        target = Path(directory)/'training_bundle.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in [root/'sft.jsonl', *public_files[1:]]:
                archive.write(file, file.relative_to(root))
        bundles['training_bundle'] = str(target.resolve())
    return {**bundles, 'dataset': str(root), 'accepted': report['accepted'], 'quality_report': str(root/'quality_report.json')}
