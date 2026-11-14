"""Observational corpus statistics for accepted scene-derived items."""
from collections import Counter
from collections import defaultdict
import json

from capabilities.dataset_authoring.scene_capture.spatial_tasks import comparison_family


def _template_statistics(groups):
    result = {}
    for template, rows in groups.items():
        labels = Counter(json.dumps(gold, ensure_ascii=False, sort_keys=True) for gold, _, _ in rows)
        semantics = Counter(json.dumps(answer, ensure_ascii=False, sort_keys=True) for _, answer, _ in rows)
        discrete = all(kind in {'single_choice', 'interval', 'text'} for _, _, kind in rows)
        result[template] = {
            'count': len(rows),
            'answer_histogram': dict(labels),
            'semantic_answer_histogram': dict(semantics),
            'majority_constant_baseline': max(max(labels.values()), max(semantics.values())) / len(rows) if discrete else None,
            'baseline_kind': (
                'in_sample_constant_answer_diagnostic_not_model_no_image_evaluation' if discrete
                else 'not_estimated_for_structured_answers'
            ),
        }
    return result


def collection_diagnostics(public, authority, evidence, candidates, selected, target, scene_family):
    """Measure coverage, repeated comparisons, and answer shortcuts for review."""
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
    templates = defaultdict(list)
    source_counts = Counter()
    source_images = set()
    prompts = Counter()
    comparisons = Counter()
    for item in public:
        contract = item['task_contract']
        source = contract['source_record']
        if source not in frames:
            raise ValueError('Collection item refers to an unknown source frame')
        original_objects = {obj['object_id'] for obj in frames[source]['objects']}
        if not set(contract['objects']) <= original_objects:
            raise ValueError('Collection item refers to an unknown source object')
        gold = answers[item['item_id']]['answer']
        choices = item['options']
        semantics = choices.get(gold, gold) if isinstance(gold, str) and isinstance(choices, dict) else gold
        template = item['template_id']
        templates[template].append((gold, semantics, item['answer_type']))
        source_counts[source] += 1
        source_images.add(frames[source]['image'])
        prompts[item['question']] += 1
        comparisons[(source, comparison_family(template), tuple(sorted(contract['objects'])))] += 1

    stats = {
        'items': len(public),
        'source_records': len(source_counts),
        'source_images': len(source_images),
        'items_by_source': dict(source_counts),
        'templates': _template_statistics(templates),
        'duplicate_evidence_groups': sum(n - 1 for n in comparisons.values() if n > 1),
        'repeated_prompt_groups': sum(n > 1 for n in prompts.values()),
        'note': 'Repeated wording may be valid when images differ. Gold answers are private.',
    }
    reference = {
        'min_items': 1,
        'min_source_records': 1,
        'max_majority_baseline': 0.75,
        'baseline_min_items': 4,
        'required_templates': [],
    }
    findings = []
    if stats['items'] < reference['min_items']:
        findings.append(f"item coverage {stats['items']} < {reference['min_items']}")
    if stats['source_records'] < reference['min_source_records']:
        findings.append(f"source coverage {stats['source_records']} < {reference['min_source_records']}")
    threshold = reference['max_majority_baseline']
    for template, values in stats['templates'].items():
        baseline = values['majority_constant_baseline']
        if values['count'] >= reference['baseline_min_items'] and baseline is not None and baseline > threshold:
            findings.append(f'{template} constant-answer baseline {baseline:.3f} > {threshold:.3f}')
    if stats['duplicate_evidence_groups']:
        findings.append('repeated source/object comparison evidence')
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
        'schema': 'benchforge.collection-diagnostics/v1',
        'implementation': 'benchforge_backend.product_diagnostics.collection_diagnostics',
        'mode': 'record_only',
        'collection_acceptance': 'not_assessed',
        'reference_policy': reference,
        'reference_policy_source': 'benchforge.collection-diagnostics/v1 observational thresholds',
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
