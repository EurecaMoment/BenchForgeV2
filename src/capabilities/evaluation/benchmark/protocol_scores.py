"""Offline protocol scoring: no model calls and no pooling incompatible metrics."""
import math
from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from storage.artifacts import read_jsonl as rows
from storage.artifacts import write_jsonl as jsonl
from storage.artifacts import write_json as write
from capabilities.dataset_authoring.answer_contracts import AnswerContractError
from capabilities.dataset_authoring.answer_contracts import scorer_for
from capabilities.dataset_authoring.answer_contracts import validate_answer
from capabilities.dataset_authoring.answer_contracts import validate_contract_declaration


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union > 0 else 0


def _match_detections(
    truth: Mapping[str, Any], prediction: Mapping[str, Any]
) -> dict[str, Any]:
    remaining = list(truth['detections'])
    matched = 0
    for detection in prediction['detections']:
        candidates = [
            (iou(detection['box'], target['box']), index)
            for index, target in enumerate(remaining)
            if target['class'] == detection['class']
        ]
        overlap, index = max(candidates, default=(0, -1))
        if overlap >= .5:
            remaining.pop(index)
            matched += 1
    return {
        'success': matched == len(prediction['detections']) == len(truth['detections']),
        'metric': 'detection_set',
        'matched': matched,
        'false_positive': len(prediction['detections']) - matched,
        'false_negative': len(remaining),
    }


def score(
    gold: Mapping[str, Any], prediction: Any, template: Mapping[str, Any]
) -> dict[str, Any]:
    """Score only through a registered, template-selected deterministic contract."""
    validate_contract_declaration(template)
    scorer = scorer_for(template['output_kind'])
    if gold.get('scorer_id') not in (None, scorer):
        raise ValueError(f"Scorer mismatch for {template['id']}: {gold['scorer_id']} != {scorer}")
    validate_answer(template, gold['answer'])
    validate_answer(template, prediction)
    truth = gold['answer']

    if scorer == 'numeric_tolerance':
        if prediction['unit'] != truth['unit']:
            return {'success': False, 'metric': scorer, 'format_error': True,
                    'format_error_detail': 'unit does not match the declared answer unit'}
        tolerance = gold.get('tolerance')
        if not isinstance(tolerance, dict):
            raise ValueError(f"Numeric template {template['id']} has no frozen tolerance object")
        absolute = tolerance.get('absolute')
        relative = tolerance.get('relative')
        if (not isinstance(absolute, (int, float)) or not math.isfinite(absolute) or absolute < 0 or
                not isinstance(relative, (int, float)) or not math.isfinite(relative) or relative < 0):
            raise ValueError(f"Numeric template {template['id']} has an invalid tolerance object")
        error = abs(prediction['value'] - truth['value'])
        threshold = max(absolute, relative * abs(truth['value']))
        return {'success': error <= threshold, 'metric': scorer,
                'absolute_error': error, 'unit': truth['unit']}

    if scorer == 'box_iou':
        overlap = iou(prediction['box'], truth['box'])
        return {'success': overlap >= .5, 'metric': scorer, 'iou': overlap}

    if scorer == 'detection_set':
        return _match_detections(truth, prediction)

    if scorer == 'choice_id':
        expected = truth['choice_id']
        actual = prediction['choice_id']
        if isinstance(expected, list):
            success = actual in expected if isinstance(actual, str) else set(actual) == set(expected)
        else:
            success = expected in actual if isinstance(actual, list) else actual == expected
        return {'success': success, 'metric': scorer}

    if scorer == 'ordered_groups':
        normalize = lambda groups: [sorted(group) for group in groups]
        success = normalize(prediction['groups']) == normalize(truth['groups'])
        return {'success': success, 'metric': scorer}

    if scorer == 'unordered_ids':
        success = set(prediction['ids']) == set(truth['ids'])
        return {'success': success, 'metric': scorer}

    field = {
        'exact_boolean': 'value',
        'exact_integer': 'value',
        'declared_label': 'label',
        'ordered_ids': 'sequence',
    }[scorer]
    return {'success': prediction[field] == truth[field], 'metric': scorer}


def _index_records(
    records: Iterable[Mapping[str, Any]], *, kind: str, required_fields: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Reject malformed or repeated IDs before any score is calculated."""
    indexed = {}
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f'{kind} row {position} must be an object')
        item_id = record.get('item_id')
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f'{kind} row {position} requires a nonempty item_id')
        missing = set(required_fields) - record.keys()
        if missing:
            raise ValueError(f'{kind} {item_id} is missing fields: {sorted(missing)}')
        if item_id in indexed:
            raise ValueError(f'Duplicate {kind.lower()} item_id: {item_id}')
        indexed[item_id] = record
    return indexed


def evaluate(
    args: Mapping[str, Any], directory: str | Path, config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Validate a prediction submission and write deterministic per-item scores."""
    dataset = Path(args['dataset'])
    authority = _index_records(
        rows(dataset / 'authority.jsonl'),
        kind='Authority',
        required_fields=(
            'answer', 'template_id', 'protocol_id', 'output_kind', 'output_schema', 'scorer_id'
        ),
    )
    if not authority:
        raise ValueError('Authority dataset must contain at least one item')
    predictions = _index_records(
        rows(args['predictions']), kind='Prediction', required_fields=('answer',)
    )
    unknown = predictions.keys() - authority.keys()
    if unknown:
        sample = ', '.join(sorted(unknown)[:10])
        raise ValueError(f'Unknown prediction item_id ({len(unknown)}): {sample}')
    from capabilities.task_catalog.benchmark import all_templates
    templates = {template['id']: template for template in all_templates()}
    contracts = {}
    for item_id, gold in authority.items():
        template = templates.get(gold['template_id'])
        if template is None:
            raise ValueError(f"Unknown template_id in authority: {gold['template_id']}")
        if gold['protocol_id'] != template['protocol_id']:
            raise ValueError(f"Protocol mismatch for authority item {item_id}")
        if gold['output_kind'] != template['output_kind']:
            raise ValueError(f"output_kind mismatch for authority item {item_id}")
        if gold['output_schema'] != template['output_schema']:
            raise ValueError(f"output_schema mismatch for authority item {item_id}")
        contract = validate_contract_declaration(template)
        if gold['scorer_id'] != contract['scorer']:
            raise ValueError(f"Scorer mismatch for authority item {item_id}")
        validate_answer(template, gold['answer'])
        contracts[item_id] = template
    outcomes, grouped = [], defaultdict(list)
    for gold in authority.values():
        prediction = predictions.get(gold['item_id'])
        if prediction is None:
            value = {'success': False, 'metric': 'missing', 'missing': True}
        else:
            try:
                value = score(gold, prediction['answer'], contracts[gold['item_id']])
            except AnswerContractError as exc:
                value = {'success': False, 'metric': contracts[gold['item_id']]['output_kind'],
                         'format_error': True, 'format_error_detail': str(exc)}
        row = {'item_id': gold['item_id'], 'template_id': gold['template_id'], **value}
        outcomes.append(row)
        grouped[gold['template_id']].append(row)
    report = {'per_template': {tid: {'count': len(values), 'success_rate': sum(v['success'] for v in values)/len(values), 'missing': sum(v.get('missing', False) for v in values)} for tid, values in grouped.items()},
              'model_api_calls': 0, 'scope': 'exact document measurement variants; no aggregate 27-capability claim',
              'submission': {'validated': True, 'expected_items': len(authority),
                             'submitted_items': len(predictions),
                             'missing_items': len(authority.keys() - predictions.keys()),
                             'format_errors': sum(row.get('format_error', False) for row in outcomes),
                             'missing_policy': 'score_as_failure'}}
    jsonl(Path(directory)/'scores.jsonl', outcomes)
    write(Path(directory)/'report.json', report)
    return {'report': str(Path(directory)/'report.json'), **report}
