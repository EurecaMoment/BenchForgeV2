"""Bounded process-local cache of geometry derived only from public sensors.

No oracle verdict, answer, native source or point cloud is stored. Input files
are identified by the caller's resolved public path/size/mtime versions. Card
and local-axis JSON are still parsed for every reconstruction; their effective
numbers, rather than question-specific filenames, participate in the key.
"""
from collections import OrderedDict
import sys
from threading import RLock
from typing import NamedTuple


def freeze_public_value(value):
    if isinstance(value, dict):
        return tuple(sorted((key, freeze_public_value(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(freeze_public_value(item) for item in value)
    return value


def public_geometry_key(card, frames, local_axes, label, asset_version):
    """Use every effective reconstruction input and the actual reference sensor."""
    reference = frames[0] if frames else {}
    reference_key = (
        asset_version(reference['sensor_asset']) if reference.get('sensor_asset') else None,
        freeze_public_value({name: card.get(name) for name in (
            'schema', 'reference', 'reference_frame', 'reference_camera',
            'camera_convention', 'pixel_convention')}),
        freeze_public_value({name: reference.get(name) for name in (
            'K', 'T_reference_camera_optical', 'pose_translation_unit', 'pixel_center_offset_px')}),
    )
    contributing = []
    for frame in frames:
        mask = frame.get('object_masks', {}).get(label)
        depth = frame.get('depth')
        if not mask or not depth:
            continue
        contributing.append((
            asset_version(mask), asset_version(depth['asset']), asset_version(depth['valid_mask']),
            float(depth['unit_scale_to_m']), freeze_public_value(frame['K']),
            freeze_public_value(frame['T_reference_camera_optical']),
            freeze_public_value(frame.get('pixel_center_offset_px')),
            frame.get('pose_translation_unit'),
            freeze_public_value({name: value for name, value in depth.items()
                                 if name not in {'asset', 'valid_mask', 'unit_scale_to_m'}}),
        ))
    return ('public-surface-extremes/v1', label, reference_key,
            tuple(contributing), freeze_public_value(local_axes))


class GeometryResult(NamedTuple):
    center: tuple
    size: tuple
    basis: str
    point_count: int


def freeze_geometry(geometry, point_count):
    return GeometryResult(tuple(float(value) for value in geometry['center']),
                          tuple(float(value) for value in geometry['size']),
                          geometry['basis'], int(point_count))


class PublicGeometryCache:
    """LRU of immutable results, bounded by entries and conservative Python size."""
    def __init__(self, max_entries=128, max_bytes=2*1024*1024):
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.values = OrderedDict()
        self.bytes = self.hits = self.misses = 0
        self.lock = RLock()

    @staticmethod
    def _weight(value):
        return sys.getsizeof(value) + (sum(PublicGeometryCache._weight(part) for part in value)
                                      if isinstance(value, tuple) else 0)

    def load(self, key, loader):
        with self.lock:
            if key in self.values:
                self.hits += 1
                self.values.move_to_end(key)
                return self.values[key][0]
            self.misses += 1
        result = loader()
        weight = self._weight(key) + self._weight(result)
        if weight > self.max_bytes:
            return result
        with self.lock:
            if key in self.values:
                return self.values[key][0]
            self.values[key] = (result, weight)
            self.bytes += weight
            while len(self.values) > self.max_entries or self.bytes > self.max_bytes:
                _, (_, removed) = self.values.popitem(last=False)
                self.bytes -= removed
        return result

    def stats(self):
        with self.lock:
            return {'entries': len(self.values), 'bytes': self.bytes,
                    'hits': self.hits, 'misses': self.misses,
                    'max_entries': self.max_entries, 'max_bytes': self.max_bytes,
                    'byte_accounting': 'conservative Python key and immutable result sizes'}


PUBLIC_GEOMETRY_RESULTS = PublicGeometryCache()
