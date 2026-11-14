"""Native USD asset and material metadata shared by planning and capture."""

import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re

from service_access.runtime_config import environment_value


def load_native_assets():
    path = Path(environment_value('BENCHFORGE_NATIVE_CATALOG', Path(__file__).resolve().parents[1] / 'resources/native_assets.json'))
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


def load_native_materials():
    path=Path(environment_value('BENCHFORGE_NATIVE_MATERIAL_CATALOG',Path(__file__).resolve().parents[1] / 'resources/native_materials.json'))
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


from copy import deepcopy

ASSETS = {
    'mug': {'path': 'Mugs/SM_Mug_A2.usd', 'size': [.0924, .1272, .091], 'description': 'ceramic mug with handle'},
    'bin': {'path': 'KLT_Bin/small_KLT_visual_collision.usd', 'size': [.198, .297, .1464], 'description': 'open industrial container'},
}
ASSETS.update(load_native_assets())
NATIVE_MATERIALS = load_native_materials()

def normalize_native_asset_references(program):
    """Canonicalize the two spellings of a registered native asset, preserving input."""
    result=deepcopy(program)
    for obj in result.get('objects',[]):
        if obj.get('kind')=='mesh' and obj.get('asset_id') in ASSETS:
            transform=obj.get('mesh_transform')
            if transform:
                if any(transform.get('orientation_deg_xyz',[0,0,0])) or transform.get('scale_mode','uniform_fit')!='uniform_fit':
                    raise ValueError(f'object {obj["id"]}: native asset aliases only support zero Euler orientation with uniform_fit; use yaw_deg and native asset kind')
                native_size=ASSETS[obj['asset_id']]['size'];requested=list(obj['size'])
                scale=min(requested[i]/native_size[i] for i in range(3))
                obj['size']=[v*scale for v in native_size]
                obj['metadata']={**obj.get('metadata',{}),'native_alias_fit':{'requested_size':requested,'uniform_scale':scale}}
                obj.pop('mesh_transform')
            obj['kind']=obj.pop('asset_id')
    return result
