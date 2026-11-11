"""Observational corpus statistics for accepted scene-derived items."""
from collections import Counter
from types import SimpleNamespace


def collection_diagnostics(public, authority, evidence, candidates, selected, target, scene_family):
    """Reuse Harness arithmetic without turning inherited defaults into gates."""
    from benchclaw.collection_review import collection_statistics, policy_violations
    from benchclaw.domain import CollectionPolicy

    frames = {frame['frame_id']: frame for frame in evidence['frames']}
    if len(frames) != len(evidence['frames']):
        raise ValueError('Duplicate source frame IDs')
    public_ids = [row['item_id'] for row in public]
    authority_ids = [row['item_id'] for row in authority]
    if (
        len(set(public_ids)) != len(public_ids)
        or len(set(authority_ids)) != len(authority_ids)
        or set(public_ids) != set(authority_ids)
    ):
        raise ValueError('Collection item/authority IDs must be unique and match')

    selected_ids = {row['item_id'] for row, _ in selected}
    if not set(public_ids) <= selected_ids:
        raise ValueError('Accepted item is absent from selected candidates')
    answers = {row['item_id']: row for row in authority}
    visible_rows = []
    answer_rows = []
    evidence_rows = []
    for item in public:
        contract = item['task_contract']
        source = contract['source_record']
        if source not in frames:
            raise ValueError('Collection item refers to an unknown source frame')
        original_objects = {obj['object_id'] for obj in frames[source]['objects']}
        if not set(contract['objects']) <= original_objects:
            raise ValueError('Collection item refers to an unknown source object')
        item_id = item['item_id']
        evidence_id = 'ev_' + item_id
        visible_rows.append(
            SimpleNamespace(
                item_id=item_id,
                prompt=item['question'],
                choices=item['options'],
                answer_type=item['answer_type'],
            )
        )
        answer_rows.append(
            SimpleNamespace(
                item_id=item_id,
                gold=answers[item_id]['answer'],
                template_id=item['template_id'],
                evidence_refs=[evidence_id],
            )
        )
        evidence_rows.append(
            SimpleNamespace(
                evidence_id=evidence_id,
                source_refs=[source],
                asset_refs=[frames[source]['image']],
                fields={'task_contract': contract},
            )
        )

    bundle = SimpleNamespace(
        visible=visible_rows,
        answers=answer_rows,
        evidence=evidence_rows,
    )
    stats = collection_statistics(bundle)
    policy = CollectionPolicy()
    reference = policy.model_dump(
        include={
            'min_items',
            'min_source_records',
            'max_majority_baseline',
            'baseline_min_items',
            'required_templates',
        }
    )
    findings = policy_violations(stats, policy)
    candidate_sources = {record.record_id for _, record in candidates}
    selected_sources = {record.record_id for _, record in selected}
    accepted_sources = set(stats['items_by_source'])
    available_sources = set(frames)
    if not (candidate_sources | selected_sources) <= available_sources:
        raise ValueError('Candidate source frame is absent from capture evidence')
    shortfall = max(0, target - len(public))
    if shortfall:
        findings.append(
            f'accepted item shortfall {shortfall} relative to requested target {target}'
        )
    if available_sources - accepted_sources:
        findings.append(
            'captured frames without accepted items: '
            + ','.join(sorted(available_sources - accepted_sources))
        )
    return {
        'schema': 'spatialforge.collection-diagnostics/v1',
        'implementation': 'benchclaw.collection_review.collection_statistics/policy_violations',
        'mode': 'record_only',
        'collection_acceptance': 'not_assessed',
        'reference_policy': reference,
        'reference_policy_source': 'inherited CollectionPolicy defaults; observational only',
        'statistics': stats,
        'findings': findings,
        'scope': {
            'scene_family': scene_family,
            'scene_families': 1,
            'source_record_unit': 'one captured camera frame; multiple frames do not establish cross-scene coverage',
            'captured_frames': len(frames),
            'captured_images': len({frame['image'] for frame in frames.values()}),
            'candidate_source_frames': sorted(candidate_sources),
            'selected_source_frames': sorted(selected_sources),
            'accepted_source_frames': sorted(accepted_sources),
            'unused_source_frames': sorted(available_sources - accepted_sources),
            'accepted_frame_coverage': len(accepted_sources) / len(frames) if frames else 0,
        },
        'selection': {
            'generated_candidates': len(candidates),
            'selected_candidates': len(selected),
            'filtered_by_item_review': len(selected) - len(public),
            'target_items': target,
            'shortfall': shortfall,
            'candidate_templates': dict(Counter(row['template_id'] for row, _ in candidates)),
            'selected_templates': dict(Counter(row['template_id'] for row, _ in selected)),
        },
        'human_approved': False,
        'benchmark_approved': False,
        'gt_modified': False,
        'limitations': [
            'Observations do not certify collection quality or enforce answer balancing.',
            'Majority values are in-sample constant-answer diagnostics, not no-image model evaluations.',
            'Repeated comparison evidence means the same source frame, relation family and object set; repeated wording alone is not a duplicate.',
            'One scene family cannot establish cross-scene generalization; no corpus-wide split or duplicate audit was performed.',
        ],
    }
