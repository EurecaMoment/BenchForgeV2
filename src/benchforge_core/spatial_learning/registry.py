"""The 27 source capabilities and executable, independently versioned templates."""
import json
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).parent


@lru_cache(maxsize=1)
def graph():
    return json.loads((ROOT / 'graph.json').read_text(encoding='utf8'))


@lru_cache(maxsize=1)
def _templates():
    return json.loads((ROOT / 'templates.json').read_text(encoding='utf8'))


def templates(capability=None):
    rows = _templates()
    return [row for row in rows if capability is None or capability in row['primary_capabilities']]


def catalog(args, directory=None, config=None):
    if args.get('section', 'graph') == 'graph':
        return graph()
    rows = templates(args.get('capability'))
    query = args.get('query', '').casefold()
    rows = [row for row in rows if query in json.dumps(row, ensure_ascii=False).casefold()]
    offset, limit = args.get('offset', 0), args.get('limit', 20)
    return {'templates': rows[offset:offset+limit], 'total': len(rows),
            'next_offset': offset+limit if offset+limit < len(rows) else None}
