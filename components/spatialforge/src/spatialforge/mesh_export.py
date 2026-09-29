"""Portable triangle data and optional PBR material transport.

``mesh.json`` keeps the original vertex-color fields for the lightweight
 desktop importer. When source UVs and material images exist it additionally
contains UVs, per-face material indices, scalar PBR factors, and copied texture
files. The original GLB is retained for provenance.
"""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import trimesh


def _float_factor(value, default):
    try:
        values = np.asarray(value, dtype=np.float64).reshape(-1)
        if not len(values) or not np.isfinite(values).all():
            return default
        if values.max() > 1.0:
            values = values / 255.0
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return default


def _image(value):
    if value is None:
        return None
    try:
        from PIL import Image
        if isinstance(value, Image.Image):
            return value
        array = np.asarray(value)
        if array.ndim in (2, 3):
            return Image.fromarray(array)
    except (TypeError, ValueError):
        return None
    return None


def _material_record(material, texture_dir, material_index):
    """Serialize a trimesh PBR/Simple material and copy image payloads."""
    if material is None:
        return {'name': f'material_{material_index}', 'base_color_factor': [1., 1., 1., 1.], 'metallic_factor': 0., 'roughness_factor': .55, 'double_sided': True, 'textures': {}}
    name = str(getattr(material, 'name', None) or f'material_{material_index}')
    source_type = type(material).__name__
    # OBJ/MTL uses SimpleMaterial.image, not PBRMaterial.baseColorTexture.
    # Trimesh preserves its diffuse image/factor and approximates Ns as roughness.
    if isinstance(material, trimesh.visual.material.SimpleMaterial):
        material = material.to_pbr()
    record = {
        'name': name,
        'source_material_type': source_type,
        'base_color_factor': _float_factor(getattr(material, 'baseColorFactor', None), [1., 1., 1., 1.]),
        'metallic_factor': float(getattr(material, 'metallicFactor', 0.) or 0.),
        'roughness_factor': float(getattr(material, 'roughnessFactor', .55) if getattr(material, 'roughnessFactor', None) is not None else .55),
        'double_sided': bool(getattr(material, 'doubleSided', True)),
        'textures': {},
    }
    slots = {'base_color': 'baseColorTexture', 'normal': 'normalTexture', 'metallic_roughness': 'metallicRoughnessTexture', 'occlusion': 'occlusionTexture', 'emissive': 'emissiveTexture'}
    for slot, attribute in slots.items():
        image = _image(getattr(material, attribute, None))
        if image is None:
            continue
        texture_dir.mkdir(parents=True, exist_ok=True)
        filename = f'texture_{material_index}_{slot}.png'
        image.convert('RGBA' if 'A' in image.getbands() else 'RGB').save(texture_dir / filename, format='PNG')
        record['textures'][slot] = (Path('textures') / filename).as_posix()
    if hasattr(material, 'emissiveFactor'):
        record['emissive_factor'] = _float_factor(getattr(material, 'emissiveFactor'), [0., 0., 0.])
    return record


def export_mesh(source, output, glb_output=None, source_frame='sam3d_camera'):
    source, output = Path(source), Path(output)
    scene = trimesh.load(source, force='scene', process=False)
    if not isinstance(scene, trimesh.Scene):
        scene = trimesh.Scene(scene)
    texture_dir = output.parent / 'textures'
    vertices, faces, colors, uvs, face_materials, visuals, materials = [], [], [], [], [], [], []
    normals, normal_sources = [], []
    offset = 0
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        original = scene.geometry[name]
        if not isinstance(original, trimesh.Trimesh) or not len(original.faces):
            continue
        # Reading vertex_normals computes smooth normals when absent. Read the
        # loader-populated cache instead so a flat source stays flat.
        authored_normals = original._cache.cache.get('vertex_normals')
        mesh = original.copy()
        mesh.apply_transform(transform)
        if authored_normals is not None:
            from .mesh_geometry import transform_mesh_normals
            transformed_normals = transform_mesh_normals(authored_normals, transform)
            normals.append(transformed_normals[np.asarray(mesh.faces)].reshape((-1, 3)))
            normal_sources.append({'geometry': name, 'origin': 'source_vertex_normals'})
        else:
            normals.append(np.repeat(mesh.face_normals, 3, axis=0))
            normal_sources.append({'geometry': name, 'origin': 'geometric_face_normals'})
        if not np.isfinite(mesh.vertices).all():
            raise ValueError('mesh contains nonfinite vertices')
        source_visual = mesh.visual
        raw_uv = getattr(source_visual, 'uv', None)
        uv = np.asarray(raw_uv, dtype=np.float64) if raw_uv is not None else np.zeros((len(mesh.vertices), 2), dtype=np.float64)
        source_uv_present = raw_uv is not None and uv.shape == (len(mesh.vertices), 2) and np.isfinite(uv).all()
        if not source_uv_present:
            uv = np.zeros((len(mesh.vertices), 2), dtype=np.float64)
        material_index = len(materials)
        materials.append(_material_record(getattr(source_visual, 'material', None), texture_dir, material_index))
        materials[-1]['source_uv_present'] = bool(source_uv_present)
        if materials[-1]['textures'] and not source_uv_present:
            raise ValueError(f'geometry {name!r} has texture images but no valid source UVs; refusing fabricated texture coordinates')
        visual = source_visual.to_color() if source_visual.kind == 'texture' else source_visual
        color = np.asarray(visual.vertex_colors)
        if len(color) != len(mesh.vertices):
            color = np.tile([180, 180, 180, 255], (len(mesh.vertices), 1))
        vertices.append(np.asarray(mesh.vertices)); faces.append(np.asarray(mesh.faces) + offset)
        colors.append(color[:, :3] / 255.); uvs.append(uv)
        face_materials.append(np.full(len(mesh.faces), material_index, dtype=np.int32))
        offset += len(mesh.vertices)
        visuals.append({'geometry': name, 'source_encoding': source_visual.kind or 'unassigned', 'material_name': materials[-1]['name'], 'source_uv_present': bool(source_uv_present)})
    if not faces:
        raise ValueError('source contains no triangle mesh')
    vertex_data, face_data = np.concatenate(vertices), np.concatenate(faces)
    normal_data = np.concatenate(normals)
    color_data, uv_data, material_data = np.concatenate(colors), np.concatenate(uvs), np.concatenate(face_materials)
    if source_frame == 'y_up':
        vertex_data = vertex_data[:, [0, 2, 1]] * [1, -1, 1]
        normal_data = normal_data[:, [0, 2, 1]] * [1, -1, 1]
    elif source_frame not in {'z_up', 'sam3d_camera'}:
        raise ValueError('unsupported source coordinate frame')
    merged = trimesh.Trimesh(vertices=vertex_data, faces=face_data, process=False)
    has_textures = any(bool(item['textures']) for item in materials)
    record = {
        'schema': 'spatialforge.mesh/v1', 'vertices': vertex_data.round(7).tolist(), 'faces': face_data.tolist(),
        'normals': normal_data.round(7).tolist() if any(n['origin'] == 'source_vertex_normals' for n in normal_sources) else [],
        'normals_interpolation': 'faceVarying', 'normal_sources': normal_sources,
        'colors': color_data.round(5).tolist(), 'texcoords': uv_data.round(7).tolist() if any(v['source_uv_present'] for v in visuals) else [], 'material_index': material_data.tolist(),
        'materials': materials, 'bounds': merged.bounds.tolist(),
        'coordinate_frame': 'sam3d_camera' if source_frame == 'sam3d_camera' else 'z_up',
        'source_coordinate_frame': source_frame, 'watertight': bool(merged.is_watertight),
        'appearance': {'encoding': 'pbr_materials' if has_textures else ('texture_sampled_vertex_color' if any(v['source_encoding'] == 'texture' for v in visuals) else 'vertex_color'), 'source_visuals': visuals},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.part')
    temporary.write_text(json.dumps(record, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temporary.replace(output)
    if glb_output:
        glb_output = Path(glb_output); glb_output.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() == '.glb': shutil.copy2(source, glb_output)
        else: glb_output.write_bytes(scene.export(file_type='glb'))
    return record


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--source', required=True); parser.add_argument('--output', required=True); parser.add_argument('--glb-output'); parser.add_argument('--source-frame', choices=['sam3d_camera', 'y_up', 'z_up'], default='sam3d_camera')
    args = parser.parse_args(); result = export_mesh(args.source, args.output, args.glb_output, args.source_frame)
    print(json.dumps({'status': 'ok', 'vertices': len(result['vertices']), 'triangles': len(result['faces']), 'materials': len(result['materials']), 'coordinate_frame': result['coordinate_frame']}))


if __name__ == '__main__': main()
