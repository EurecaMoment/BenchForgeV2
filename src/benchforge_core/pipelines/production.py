"""Instantiate exact document templates from program worlds or recorded evidence."""
import json
import os
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
from .question_writing import builtin_spec, contract, question_text, validate_spec
from .scene_policy import load_policy, check_source, check_evidence

PARTITIONS = ('train', 'dev', 'test', 'sealed')
PRIVATE_ASSET_FIELDS = {'answer', 'answers', 'oracle', 'oracle_detail', 'ground_truth', 'gold',
                        'authority', 'private', 'objects_gt', 'object_gt', 'point_world',
                        'settled_center_m', 'size_xyz_m', 'world_transform'}


def public_asset_references(value):
    """References consumed by the existing published RGB-D calibration reader."""
    references = []
    schema = value.get('schema') if isinstance(value, dict) else None
    if schema == 'public-camera-scale/v1':
        if value.get('local_axes_asset'):
            references.append(value['local_axes_asset'])
        frames = value.get('frames', [])
    elif schema == 'public-camera-sensor/v1':
        frames = [value]
    else:
        return references
    for frame in frames:
        if frame.get('sensor_asset'):
            references.append(frame['sensor_asset'])
        if frame.get('depth'):
            references.extend(frame['depth'][key] for key in ('asset', 'valid_mask'))
        references.extend(frame.get('object_masks', {}).values())
    return references


def validate_public_assets(files, private_source=None, cache=None):
    """Validate the explicit whitelist only; never discover additional files."""
    approved = set(files)
    private_source = Path(private_source).resolve() if private_source else None
    versions = {}
    for file in files:
        if not file.is_file() or not file.stat().st_size:
            raise ValueError('Missing or empty declared public asset: ' + str(file))
        stat = file.stat()
        version = (str(file), stat.st_size, stat.st_mtime_ns)
        versions[file] = version
        if (file == private_source or file.suffix.lower() in ('.usd', '.usda', '.usdc') or
            'authority' in {part.casefold() for part in file.parts} or
            file.name.casefold() in ('authority.jsonl', 'gold.jsonl', 'sft.jsonl')):
            raise ValueError('Private source/authority/native scene cannot be a public asset')
        if file.suffix.lower() != '.json':
            continue
        if stat.st_size > 2 * 1024 * 1024:
            raise ValueError('Public asset JSON exceeds the supported size')
        def no_private_fields(node):
            if isinstance(node, dict):
                if PRIVATE_ASSET_FIELDS & {str(key).casefold() for key in node}:
                    raise ValueError('Public asset contains private answer or object-truth fields')
                for child in node.values():
                    no_private_fields(child)
            elif isinstance(node, list):
                for child in node:
                    no_private_fields(child)

        references = cache.get(version) if cache is not None else None
        if references is None:
            value = read(file)
            no_private_fields(value)
            references = public_asset_references(value)
            if cache is not None:
                cache[version] = references
        for reference in references:
            if not isinstance(reference, str) or not reference:
                raise ValueError('Public calibration has an invalid attachment reference')
            path = Path(reference)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Public calibration attachments must stay relative to their bundle')
            target = (file.parent / path).resolve()
            target.relative_to(file.parent)
            if target not in approved:
                raise ValueError('Public calibration attachment is absent from the declared asset closure: ' + reference)
    return versions


def copy_public_assets(sample, root, roots, copied, checked=None):
    files = list(dict.fromkeys(Path(file).resolve() for file in sample.get('assets', [])))
    if not files:
        return []
    versions = validate_public_assets(files, sample.get('source_provenance', {}).get('path'), checked)
    source_root = Path(os.path.commonpath([str(file.parent) for file in files]))
    if source_root not in roots:
        roots[source_root] = root / 'assets' / ('source_' + str(len(roots)))
    references = []
    for source in files:
        target = roots[source_root] / source.relative_to(source_root)
        version = versions[source]
        if target in copied:
            if copied[target] != version:
                raise ValueError('Public asset changed during production; regenerate its evidence')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied[target] = version
        references.append(target.relative_to(root).as_posix())
    return references


def packaged_public_assets(questions, root):
    assets = set()
    checked = {}
    asset_root = (root / 'assets').resolve()
    for row in questions:
        files = []
        for reference in row.get('assets', []):
            if not isinstance(reference, str) or Path(reference).is_absolute() or not reference.startswith('assets/'):
                raise ValueError('Only declared relative public assets can enter the public bundle')
            file = (root / reference).resolve()
            file.relative_to(asset_root)
            files.append(file)
        validate_public_assets(files, cache=checked)
        assets.update(files)
    return sorted(assets)


def partition_counts(items):
    counts = Counter()
    for item in items:
        split = item.get('split')
        if split not in PARTITIONS:
            raise ValueError('Each item split must be train, dev, test or sealed')
        counts[split] += 1
    return {split: counts[split] for split in PARTITIONS if counts[split]}


def counts_for(selections):
    counts = Counter()
    for selection in selections:
        ids, count = selection['template_ids'], selection['count']
        if not ids or type(count) is not int or count < len(ids):
            raise ValueError('Each selection count must cover its explicitly selected templates at least once')
        for i, tid in enumerate(ids):
            counts[tid] += count//len(ids) + (i < count % len(ids))
    return counts


def _require_production_evidence(value):
    # Old records may omit these flags. An explicit preparation/smoke marker
    # must be checked before binding discards record metadata or selects GT.
    if isinstance(value, dict) and (value.get('non_production') is True or value.get('production_eligible') is False):
        raise ValueError('Non-production evidence cannot enter a production pipeline; provide accepted production evidence')


def bind_record(template, row, base):
    _require_production_evidence(row)
    source = row['provenance']
    if source['kind'] not in ('program', 'simulation', 'official'):
        raise ValueError('Template GT must come from program, simulation or official evidence')
    path = Path(source['path'])
    if not path.is_absolute():
        path = base/path
    raw = read(path)
    _require_production_evidence(raw)
    answer = select(raw, row['answer_selector'])
    # Source stores actual checks and the instantiated protocol version, not model votes.
    admission = select(raw, row['admission_selector'])
    _require_production_evidence(admission)
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
    if not isinstance(row.get('assets', []), list) or any(not isinstance(p, str) or not p for p in row.get('assets', [])):
        raise ValueError('Evidence assets must be an explicit list of public file paths')
    assets = [Path(p) if Path(p).is_absolute() else base/p for p in row.get('assets', [])]
    return {'parameters': row['parameters'], 'media': media, 'assets': assets, 'source': raw, 'oracle': answer,
            'provided_information': row['provided_information'], 'oracle_version': row['oracle_version'],
            'reference_frame': row['reference_frame'], 'source_provenance': {**source, 'path': str(path.resolve()), 'answer_selector': row['answer_selector'], 'admission_selector': row['admission_selector']},
            'history_access_mode': row.get('history_access_mode'), 'admission': admission,
            'question_spec': row.get('question_spec')}


def produce(args, directory, config=None):
    preserve = args.get('preserve_source_splits', False)
    if type(preserve) is not bool:
        raise ValueError('preserve_source_splits must be an explicit boolean')
    templates = {r['id']: r for r in all_templates()}
    counts = counts_for(args['selections'])
    if set(counts)-set(templates):
        raise ValueError('Unknown template IDs; choose exact IDs from pipeline_catalog')
    root = Path(directory)/'dataset'
    root.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(args['evidence']).resolve() if args.get('evidence') else None
    records = rows(evidence_path) if evidence_path else []
    service_config = args.get('_service_config') or args.get('service_config')
    policy = load_policy(args['_workspace'], service_config)
    if evidence_path:check_source(policy,source_path=evidence_path)
    for record in records:
        _require_production_evidence(record)
        source = record.get('provenance', {})
        check_source(policy, task_id=source.get('task_id'), run_id=source.get('run_id'),
                     scene_group=record.get('scene_group_id'), source_path=source.get('path'))
        check_evidence(args['_workspace'], record, evidence_path, service_config)
    public, authority, rejected = [], [], []
    asset_roots, asset_copies, asset_checks = {}, {}, {}
    usage = Counter()
    seed = args.get('seed', 20261013)
    split = args.get('split', 'train')
    if split not in PARTITIONS:
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
                group = row['scene_group_id']
                if preserve and 'split' not in row:
                    raise ValueError('preserve_source_splits requires an explicit split on each evidence record')
                item_split = row.get('split', split)
                if item_split not in PARTITIONS:
                    raise ValueError('Each evidence split must be train, dev, test or sealed')
                if not preserve and item_split != split:
                    raise ValueError('Evidence split is immutable; select records from the requested partition')
                sample = bind_record(template, row, evidence_path.parent)
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
            spec = sample.get('question_spec') if using_source else builtin_spec(template, sample)
            presentation = validate_spec(spec, sample['parameters'], len(sample['media']))
            question = question_text(presentation)
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
            assets = copy_public_assets(sample, root, asset_roots, asset_copies, asset_checks)
            public.append({'item_id': item_id, 'task_id': template['task_id'], 'template_id': tid,
                           'protocol_id': template['protocol_id'], 'protocol_version': template['protocol']['version'],
                           'measurement_variant': template['measurement_variant'], 'primary_operation': template['operation'],
                           'catalog_capability_links': template['catalog_capability_links'],
                           'provided_information': sample['provided_information'], 'scene_group_id': group,
                           'split': item_split, 'question': question, 'question_presentation': presentation, 'media': media, 'assets': assets,
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
    jsonl(root/'sft.jsonl', [{'item_id': r['item_id'], 'messages': [{'role': 'user', 'content': r['question']}, {'role': 'assistant', 'content': json.dumps(truth[r['item_id']], ensure_ascii=False)}], 'images': r['media'], 'assets': r.get('assets', [])} for r in public if r['split'] == 'train'])
    write(root/'protocols.json', {'common': document()['common_protocol'], 'templates': [templates[t] for t in counts]})
    partitions = partition_counts(public)
    dataset_split = 'mixed' if len(partitions) > 1 else next(iter(partitions), split)
    report = {'requested': sum(counts.values()), 'accepted': len(public), 'shortfall': sum(counts.values())-len(public),
              'per_template': dict(usage), 'requested_per_template': dict(counts), 'split': dataset_split,
              'requested_split': split, 'preserve_source_splits': preserve,
              'per_partition': partitions,
              'per_template_partitions': {tid: partition_counts([row for row in public if row['template_id'] == tid]) for tid in counts},
              'sft_split': 'train', 'sft_items': partitions.get('train', 0),
              'public_asset_count': len(asset_copies),
              'training_bundle_eligible': dataset_split == 'train' and len(public) == sum(counts.values()) and bool(public),
              'scene_groups': len({r['scene_group_id'] for r in public}), 'rejections': rejected,
              'source': document()['meta']['version'], 'benchmark_approved': False,
              'capability_scope': 'document task operations and measurement variants; links are not validated mastery',
              'state': 'completed' if len(public) == sum(counts.values()) else 'needs_evidence'}
    if report['shortfall']:
        specification = root/'production_spec.json'
        write(specification, {'templates': [templates[tid] | {'missing_items': counts[tid]-usage[tid]} for tid in counts if counts[tid] > usage[tid]],
                             'common_protocol': document()['common_protocol'], 'question_authoring': contract(),
                             'evidence_record': {'template_id': 'exact imported template ID', 'parameters': 'all prompt parameters; answers and hidden state excluded', 'media': 'public observation paths', 'provided_information': 'explicit public information list', 'provenance': {'kind': 'program|simulation|official', 'path': 'source JSON path'}, 'answer_selector': 'JSON Pointer into source oracle result', 'admission_selector': 'JSON Pointer into source admission record', 'oracle_version': 'implemented oracle version', 'reference_frame': 'explicit axes/units', 'scene_group_id': 'underlying scene/history/trajectory group, not just per-question seed', 'split': 'explicit immutable source partition: train/dev/test/sealed' if preserve else split},
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
    questions = rows(root/'questions.jsonl')
    partitions = partition_counts(questions)
    dataset_split = 'mixed' if len(partitions) > 1 else next(iter(partitions), report['split'])
    if len(partitions) > 1 and report.get('preserve_source_splits') is not True:
        raise ValueError('Mixed evidence requires explicit preserve_source_splits in production')
    if report['split'] != dataset_split or report.get('per_partition', partitions) != partitions:
        raise ValueError('Dataset partition report does not match its actual item splits')
    if report['accepted'] != len(questions):
        raise ValueError('Dataset report count does not match its actual items')
    train_ids = {row['item_id'] for row in questions if row['split'] == 'train'}
    sft_path = root/'sft.jsonl'
    sft = rows(sft_path) if sft_path.is_file() else []
    if any(row.get('item_id') not in train_ids for row in sft):
        raise ValueError('SFT export contains an item outside the train partition')
    training_allowed = set(partitions) == {'train'}
    if not training_allowed and (Path(directory)/'training_bundle.zip').exists():
        raise ValueError('Use a new package directory; an old training bundle cannot accompany a non-training dataset')
    media = sorted({root/media for row in questions for media in row['media']})
    assets = packaged_public_assets(questions, root)
    public_files = [root/'questions.jsonl', *media, *assets]
    private_files = [root/'authority.jsonl', root/'protocols.json', root/'quality_report.json', *[p for p in (root/'authority').rglob('*') if p.is_file()]]
    bundles = {}
    for kind, files in [('public', public_files), ('authority', private_files)]:
        target = Path(directory)/f'{kind}_bundle.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.relative_to(root))
        bundles[kind+'_bundle'] = str(target.resolve())
    if training_allowed:
        target = Path(directory)/'training_bundle.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in [root/'sft.jsonl', *public_files[1:]]:
                archive.write(file, file.relative_to(root))
        bundles['training_bundle'] = str(target.resolve())
    return {**bundles, 'dataset': str(root), 'accepted': report['accepted'],
            'split': dataset_split, 'per_partition': partitions,
            'public_asset_count': len(assets),
            'sft_split': 'train', 'sft_items': len(sft), 'training_bundle_eligible': training_allowed,
            'quality_report': str(root/'quality_report.json')}
