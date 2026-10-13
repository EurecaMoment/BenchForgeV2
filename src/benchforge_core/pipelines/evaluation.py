"""Offline protocol scoring: no model calls and no pooling incompatible metrics."""
import math
from collections import defaultdict
from pathlib import Path
from ..runtime import read, rows, jsonl, write


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union > 0 else 0


def score(gold, prediction):
    truth = gold['answer']
    if gold.get('template_id', '').startswith(('C71-', 'C77-', 'C78-', 'C79-', 'C80-', 'C81-', 'C82-', 'C83-', 'P005-', 'P006-')):
        raise ValueError('This path/interactive protocol needs its own constraint or episode scorer; exact answer matching is insufficient')
    if isinstance(truth, dict) and 'value' in truth:
        if not isinstance(prediction, dict) or prediction.get('unit') != truth['unit'] or type(prediction.get('value')) not in (int, float) or not math.isfinite(prediction['value']):
            return {'success': False, 'metric': 'numeric', 'format_error': True}
        error = abs(prediction['value']-truth['value'])
        tolerance = gold['tolerance']
        return {'success': error <= max(tolerance['absolute'], tolerance['relative']*abs(truth['value'])), 'metric': 'numeric', 'absolute_error': error, 'unit': truth['unit']}
    if isinstance(truth, dict) and 'groups' in truth:
        normalize = lambda groups: [sorted(group) for group in groups]
        return {'success': isinstance(prediction, dict) and normalize(prediction.get('groups', [])) == normalize(truth['groups']), 'metric': 'ordered_groups'}
    if isinstance(truth, dict) and 'box' in truth:
        box = prediction.get('box') if isinstance(prediction, dict) else None
        if not isinstance(box, list) or len(box) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            return {'success': False, 'metric': 'box_iou', 'format_error': True}
        overlap = iou(box, truth['box'])
        return {'success': overlap >= .5, 'metric': 'box_iou', 'iou': overlap}
    if isinstance(truth, dict) and 'detections' in truth:
        predicted = prediction.get('detections') if isinstance(prediction, dict) else None
        if not isinstance(predicted, list):
            return {'success': False, 'metric': 'detection_set', 'format_error': True}
        remaining = list(truth['detections'])
        matched = 0
        for detection in predicted:
            try:
                candidates = [(iou(detection['box'], t['box']), i) for i, t in enumerate(remaining) if t['class'] == detection['class']]
                overlap, index = max(candidates, default=(0, -1))
            except (KeyError, IndexError, TypeError):
                return {'success': False, 'metric': 'detection_set', 'format_error': True}
            if overlap >= .5:
                remaining.pop(index)
                matched += 1
        return {'success': matched == len(predicted) == len(truth['detections']), 'metric': 'detection_set', 'matched': matched, 'false_positive': len(predicted)-matched, 'false_negative': len(remaining)}
    return {'success': prediction == truth, 'metric': 'exact_protocol_output'}


def evaluate(args, directory, config=None):
    dataset = Path(args['dataset'])
    predictions = {r['item_id']: r['answer'] for r in rows(args['predictions'])}
    outcomes, grouped = [], defaultdict(list)
    for gold in rows(dataset/'authority.jsonl'):
        value = score(gold, predictions[gold['item_id']]) if gold['item_id'] in predictions else {'success': False, 'metric': 'missing', 'missing': True}
        row = {'item_id': gold['item_id'], 'template_id': gold['template_id'], **value}
        outcomes.append(row)
        grouped[gold['template_id']].append(row)
    report = {'per_template': {tid: {'count': len(values), 'success_rate': sum(v['success'] for v in values)/len(values), 'missing': sum(v.get('missing', False) for v in values)} for tid, values in grouped.items()},
              'model_api_calls': 0, 'scope': 'exact document measurement variants; no aggregate 27-capability claim'}
    jsonl(Path(directory)/'scores.jsonl', outcomes)
    write(Path(directory)/'report.json', report)
    return {'report': str(Path(directory)/'report.json'), **report}
