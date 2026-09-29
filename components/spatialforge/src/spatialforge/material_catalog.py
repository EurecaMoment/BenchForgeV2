"""Operator-managed texture registry. Scene proposals select IDs, never paths."""
import json
import math
import os
from pathlib import Path, PurePosixPath
import re


def load_native_materials():
    path=Path(os.environ.get('SPATIALFORGE_NATIVE_MATERIAL_CATALOG',Path(__file__).with_name('native_materials.json')))
    if not path.exists():return {}
    records=json.loads(path.read_text(encoding='utf8'))
    if not isinstance(records,dict):raise ValueError('invalid native material catalog')
    for name,item in records.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',name):raise ValueError('invalid native texture ID')
        if item.get('root')!='isaac':raise ValueError('unknown native material root')
        textures=item.get('textures',{})
        if not isinstance(textures,dict) or 'base_color' not in textures or set(textures)-{'base_color','normal'}:
            raise ValueError('invalid native material texture slots')
        for value in textures.values():
            if not isinstance(value,str):raise ValueError('invalid native material path')
            relative=PurePosixPath(value)
            if relative.is_absolute() or '..' in relative.parts or ':' in value or '\\' in value:
                raise ValueError('native material path must be relative to registered root')
        for key in ('roughness','metallic'):
            value=item.get(key,0)
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
                raise ValueError('invalid native material '+key)
    return records
