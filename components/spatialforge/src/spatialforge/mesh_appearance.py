"""Describe transported appearance, without claiming rendered or calibrated PBR."""
import numpy as np


def inspect_mesh_appearance(mesh):
    materials = mesh.get('materials') or []
    slots = sorted({slot for material in materials for slot, path in material.get('textures', {}).items() if path})
    raw_uv = mesh.get('texcoords') or []
    state = 'missing'
    if raw_uv:
        try:
            uv = np.asarray(raw_uv, dtype=float)
            valid = uv.shape == (len(mesh.get('vertices', [])), 2) and bool(np.isfinite(uv).all())
            state = ('varying' if np.any(np.ptp(uv, axis=0) > 0) else 'constant') if valid else 'invalid'
        except (TypeError, ValueError):
            state = 'invalid'
    base_count = sum(bool(m.get('textures', {}).get('base_color')) for m in materials)
    visuals = (mesh.get('appearance') or {}).get('source_visuals') or []
    known_source = bool(visuals) and all('source_uv_present' in v for v in visuals)
    return {
        'uv_state': state,
        'uv_origin': ('source' if any(v['source_uv_present'] for v in visuals) else 'absent_in_source') if known_source else 'legacy_origin_unrecorded',
        'texture_slots': slots,
        'base_color_texture_materials': base_count,
        'desktop_sampling_candidate': ('base_color_uv' if slots == ['base_color'] else 'pbr_texture_uv') if slots and state in {'varying', 'constant'} else ('source_material_factors' if any(m.get('source_material_type') for m in materials) else 'vertex_color_fallback'),
        'transport_only_texture_slots': [],
        'textured_scalar_overrides': ['roughness', 'metallic'] if slots else [],
        'scope': 'transport inspection; actual file availability and material bindings are reported by capture; not PBR calibration',
    }
