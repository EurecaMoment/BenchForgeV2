"""Read and query the benchmark measurement catalog."""
import json
import re
from functools import lru_cache
from pathlib import Path
from capabilities.task_catalog.spatial import graph

ROOT = Path(__file__).with_name('resources')


@lru_cache(maxsize=1)
def document():
    return json.loads((ROOT / 'benchmark_templates.json').read_text(encoding='utf-8'))


def all_templates():
    return [{**template, 'task_name': task['name'], 'operation': task['operation'],
             'catalog_capability_links': task['catalog_capability_links'],
             'protocol': task['new_protocol']} for task in document()['tasks'] for template in task['templates']]


def overview():
    return json.loads((ROOT / 'capabilities.json').read_text(encoding='utf-8'))


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


def page(rows, args):
    if args.get('item_id'):
        rows = [row for row in rows if row['id'] == args['item_id']]
    if query := args.get('query'):
        matches = [(relevance(row, query), row) for row in rows]
        matches = sorted(matches, key=lambda match: match[0], reverse=True)
        rows = [row for score, row in matches if score]
    offset, limit = args.get('offset', 0), args.get('limit', 12)
    end = offset + limit
    return {
        'items': rows[offset:end],
        'total': len(rows),
        'next_offset': end if end < len(rows) else None,
    }


def catalog(args):
    section = args.get('section', 'templates')
    if section == 'protocol':
        return {'common_protocol': document()['common_protocol'],
                'source_status': document()['meta']['evidence_status']}
    if section == 'capabilities':
        rows = [
            {**node, 'linked_tasks': [
                task['id'] for task in document()['tasks']
                if any(link['id'] == node['id'] for link in task['catalog_capability_links'])
            ]}
            for node in graph()['nodes']
        ]
    elif section == 'tasks':
        rows = [
            {key: value for key, value in task.items() if key != 'templates'}
            | {'template_ids': [row['id'] for row in task['templates']]}
            for task in document()['tasks']
        ]
    elif section == 'templates':
        from capabilities.dataset_authoring.adapters import supports
        rows = [{**row, 'execution': supports(row['id'])} for row in selected_templates(args)]
    else:
        raise ValueError('section must be capabilities, tasks, templates or protocol')
    return {'section': section, **page(rows, args), 'source': document()['meta']['version']}
