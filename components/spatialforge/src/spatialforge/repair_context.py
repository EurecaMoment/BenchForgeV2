"""Bounded version and capture feedback; advice only, never scene edits or GT."""
from collections import Counter
import json
from pathlib import Path
import re

FIELDS = ('kind', 'asset_id', 'mesh_transform', 'size', 'xy', 'base_z', 'support',
          'yaw_deg', 'dynamic', 'mass_kg', 'physics', 'appearance', 'render_representation', 'cast_shadows', 'parts')
GUIDANCE = ('Repair evidence distinguishes current capture, previous capture, and design reference. '
            'Use attachment_index, not attachment position as a view_N name. Compare changes and outcomes '
            'before undoing a prior pose/support/action correction. A field reversal is not automatically wrong; '
            'decide from the caller requirement and actual images/state. Do not infer semantic up from zero Euler '
            'angles, or contact from a bounding envelope. Model review issues are fallible opinions, not GT. '
            'This context never locks poses, adds retries, or changes acceptance thresholds.')


def _read(folder, name):
    path = Path(folder) / name
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def _brief(value, limit=650):
    text = json.dumps(value, ensure_ascii=False)
    return value if len(text) <= limit else {'omitted_value': True, 'characters': len(text),
                                              'entries': len(value) if isinstance(value, (list, dict)) else None}


def scene_changes(before, after, older=None, max_changes=48):
    """Compare by stable object IDs; array reorder cannot mimic a changed pose."""
    left = {o['id']: o for o in before.get('objects', [])}
    right = {o['id']: o for o in after.get('objects', [])}
    ancestor = {o['id']: o for o in (older or {}).get('objects', [])}
    changes = []
    for oid in sorted(left.keys() | right.keys()):
        if oid not in left or oid not in right:
            changes.append({'object_id': oid, 'field': 'entity', 'change': 'added' if oid in right else 'removed'})
            continue
        for field in FIELDS:
            a, b = left[oid].get(field), right[oid].get(field)
            if a != b:
                row = {'object_id': oid, 'field': field, 'before': _brief(a), 'after': _brief(b)}
                if oid in ancestor and field in ancestor[oid] and ancestor[oid][field] == b:
                    row['returns_to_earlier_value'] = True
                changes.append(row)
    for field in ('interactions', 'cameras', 'lights', 'render_environment'):
        if before.get(field) != after.get(field):
            changes.append({'field': field, 'before': _brief(before.get(field), 1600), 'after': _brief(after.get(field), 1600)})
    # Reversals and pose/support edits remain visible when there are many changes.
    changes.sort(key=lambda r: (not r.get('returns_to_earlier_value', False), r['field'] not in ('mesh_transform', 'support', 'base_z'), r.get('object_id', '')))
    result = {'changes': changes[:max_changes], 'total_changes': len(changes),
            'omitted_changes': max(0, len(changes)-max_changes),
            'reversal_count': sum(bool(r.get('returns_to_earlier_value')) for r in changes),
            'authority': 'program diff, not correctness or contact judgment'}
    while len(json.dumps(result,ensure_ascii=False)) > 16000 and result['changes']:
        result['changes'].pop();result['omitted_changes'] += 1
    return result


def _review(folder):
    review = _read(folder, 'scene_review.json')
    result = {key: review[key] for key in ('passed', 'acceptable', 'visual_quality', 'semantic_fidelity', 'interaction_passed') if key in review}
    for key in ('issues', 'repair_suggestions'):
        values = review.get(key, [])
        result[key] = [str(value)[:300] for value in values[:8]]
        result[key+'_omitted'] = max(0,len(values)-8)
    return result


def _view_paths(folder, feedback, limit):
    paths = {p.stem: p for p in (Path(folder)/'capture').glob('view_*.png') if re.fullmatch(r'view_\d+', p.stem)}
    counts = Counter(re.findall(r'\bview_\d+\b', feedback))
    order = sorted(paths, key=lambda name: (-counts[name], int(name[5:])))
    return [paths[name] for name in order[:limit]], sorted(set(counts)-set(paths))


def bound_repair_context(context):
    """Apply the budget after all attachments are assembled; keep omission counts."""
    execution = context.get('current_execution', {})
    rows = execution.get('entities', [])
    while len(json.dumps(context,ensure_ascii=False)) > 24000 and rows:
        rows.pop();execution['omitted_entities'] = execution.get('omitted_entities',0)+1
    delta = context.get('changes_into_current', {})
    while len(json.dumps(context,ensure_ascii=False)) > 24000 and delta.get('changes'):
        delta['changes'].pop();delta['omitted_changes'] = delta.get('omitted_changes',0)+1
    if len(json.dumps(context,ensure_ascii=False)) > 24000:
        raise ValueError('repair context metadata exceeds 24000 characters after detail omission')
    return context


def build_repair_context(current, previous=None):
    """Read two specific revision folders, at most 6 current + 2 prior images."""
    current = Path(current)
    program = _read(current, 'program.json')
    evidence = _read(current, 'capture/evidence.json')
    review = _read(current, 'scene_review.json')
    feedback = json.dumps({key: review.get(key) for key in ('issues', 'repair_suggestions')}, ensure_ascii=False)
    images, missing = _view_paths(current, feedback, 6)
    context = {'schema': 'spatialforge.repair-context/v1', 'authority': 'program diff and simulator receipts; model opinions separate; not GT',
               'source_revision': current.name, 'current_review_opinion': _review(current),
               'missing_review_views': missing, 'attachment_manifest': []}
    if previous is not None:
        previous = Path(previous)
        context['previous_revision'] = previous.name
        context['previous_review_opinion'] = _review(previous)
        context['changes_into_current'] = scene_changes(_read(previous, 'program.json'), program)
        prior_images, _ = _view_paths(previous, feedback, 2)
    else:
        prior_images = []
    for role, paths in (('current_capture', images), ('previous_capture', prior_images)):
        for path in paths:
            context['attachment_manifest'].append({'attachment_index': len(context['attachment_manifest'])+1,
                'role': role, 'revision': path.parent.parent.name, 'view': path.stem, 'path': str(path)})
    current_order = {o['id']: i for i, o in enumerate(program.get('objects', []))}
    entities = evidence.get('entities', {})
    changed = {c.get('object_id') for c in context.get('changes_into_current', {}).get('changes', [])}
    ids = sorted(entities, key=lambda oid: (oid not in feedback, oid not in changed, current_order.get(oid, 10000)))
    dependencies = {d.get('entity_id'): d for d in evidence.get('asset_dependencies', [])}
    rows = []
    for oid in ids:
        entity = entities[oid]
        row = {'object_id': oid, 'source_program_path': f'/objects/{current_order[oid]}' if oid in current_order else None,
               'state': {k: entity[k] for k in ('kind','support','initial_center','current_center','final_center','orientation_wxyz','world_aabb','geometry_parts','shadow_settings','render_representation','appearance_scope') if k in entity}}
        dependency = dependencies.get(oid, {})
        row['asset'] = {k: _brief(dependency[k], 1000) for k in ('asset_id','actual_size_m','orientation_deg_xyz','orientation_source','texture_sampling','appearance_overrides','render_representation','appearance','appearance_scope') if k in dependency}
        if dependency.get('gaussian'):
            row['asset']['gaussian'] = {k: dependency['gaussian'][k] for k in
                ('representation','appearance','physics','prim_path','collision_prim_path','collision_visibility') if k in dependency['gaussian']}
        rows.append(row)
    context['current_execution'] = {'origin': evidence.get('origin'),
        'render_settings': _read(current, 'capture/report.json').get('render_settings', {}), 'entities': rows,
        'total_entities': len(entities), 'omitted_entities': max(0,len(entities)-len(rows)),
        'interaction': [{'id':r.get('id'), **{k:r[k] for k in ('object_id','success','status','checks','translation_m','peak_vertical_displacement_m','final_speed_m_s','before_image','after_image') if k in r}} for r in evidence.get('interaction',{}).get('action_results',[])[:4]]}
    # Bound serialized feedback, with explicit omission counts. Full source files
    # stay available through evidence; no vertex arrays or authority bundle read.
    return bound_repair_context(context), images+prior_images
