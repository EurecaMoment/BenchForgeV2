"""Operator-managed native USD registry; production models select IDs only."""
import json
import os
from pathlib import Path, PurePosixPath
import re


def load_native_assets():
    path = Path(os.environ.get('SPATIALFORGE_NATIVE_CATALOG', Path(__file__).with_name('native_assets.json')))
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding='utf8'))
    for name, item in records.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', name):
            raise ValueError('invalid native asset ID')
        relative = PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts or ':' in item['path'] or '\\' in item['path']:
            raise ValueError('native asset path must be relative to registered root')
        if item.get('root') not in {'isaac', 'props'}:
            raise ValueError('unknown native asset root')
        if item.get('source_up_axis', 'Z') not in {'Y', 'Z'}:
            raise ValueError('invalid native asset up axis')
    return records
