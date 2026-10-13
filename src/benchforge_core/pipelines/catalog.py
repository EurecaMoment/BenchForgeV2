import json
import re
from functools import lru_cache
from pathlib import Path
from ..spatial_learning.registry import graph

ROOT = Path(__file__).parent


@lru_cache(maxsize=1)
def document():
    return json.loads((ROOT / 'task_templates.json').read_text(encoding='utf-8'))


def all_templates():
    return [{**template, 'task_name': task['name'], 'operation': task['operation'],
             'catalog_capability_links': task['catalog_capability_links'],
             'protocol': task['new_protocol']} for task in document()['tasks'] for template in task['templates']]


def pipeline_files():
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT / 'definitions').glob('*.json'))]


def capability_id(value):
    value = value.strip()
    if re.fullmatch(r'N\d{1,2}', value, re.I):
        value = 'N' + value[1:].zfill(2)
    nodes = graph()['nodes']
    match = next((n['id'] for n in nodes if value == n['id'] or value == n['name']), None)
    if not match:
        raise ValueError(f'Unknown capability: {value}; use pipeline_catalog section=capabilities')
    return match


def selected_templates(args):
    rows = all_templates()
    ids = args.get('template_ids', [])
    tasks = args.get('task_ids', [])
    caps = [capability_id(c) for c in args.get('capabilities', [])]
    if args.get('capability'):
        caps.append(capability_id(args['capability']))
    known = {r['id'] for r in rows}
    if set(ids) - known:
        raise ValueError('Unknown template IDs: ' + ', '.join(sorted(set(ids) - known)))
    if set(tasks) - {r['task_id'] for r in rows}:
        raise ValueError('Unknown task ID')
    if ids:
        rows = [r for r in rows if r['id'] in ids]
    if tasks:
        rows = [r for r in rows if r['task_id'] in tasks]
    if caps:
        rows = [r for r in rows if set(caps) & {c['id'] for c in r['catalog_capability_links']}]
    return rows


def relevance(row, query):
    text = (row.get('task_name', row.get('name', '')) + ' ' + row.get('title', '') + ' ' + row.get('description', '')).casefold()
    query = query.casefold()
    words = re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]+', query)
    tokens = [piece for word in words for piece in ([word] if len(word) < 3 or word.isascii() else [word, *[word[i:i+2] for i in range(len(word)-1)]])]
    return sum(3 if token == row.get('id', '').casefold() else 1 for token in set(tokens) if token in text or token in row.get('id', '').casefold())


def catalog(args, directory=None, config=None):
    from .adapters import supports
    section = args.get('section', 'pipelines')
    if section == 'protocol':
        return {'common_protocol': document()['common_protocol'], 'source_status': document()['meta']['evidence_status']}
    if section == 'capabilities':
        rows = [{**n, 'linked_tasks': [t['id'] for t in document()['tasks'] if n['id'] in [c['id'] for c in t['catalog_capability_links']]]} for n in graph()['nodes']]
    elif section == 'pipelines':
        rows = pipeline_files()
    elif section == 'tasks':
        rows = [{k: v for k, v in t.items() if k != 'templates'} | {'template_ids': [r['id'] for r in t['templates']]} for t in document()['tasks']]
    elif section == 'templates':
        rows = selected_templates(args)
        rows = [{**r, 'execution': supports(r['id'])} for r in rows]
    else:
        raise ValueError('section must be pipelines, capabilities, tasks, templates or protocol')
    if args.get('item_id'):
        rows = [r for r in rows if r['id'] == args['item_id']]
    if args.get('query'):
        rows = sorted([r for r in rows if relevance(r, args['query'])], key=lambda r: relevance(r, args['query']), reverse=True)
    offset, limit = args.get('offset', 0), args.get('limit', 12)
    return {'section': section, 'items': rows[offset:offset+limit], 'total': len(rows),
            'next_offset': offset+limit if offset+limit < len(rows) else None,
            'source': document()['meta']['version'],
            'capability_policy': 'Catalog links select candidates; task operation and measurement variant define measured scope.'}
