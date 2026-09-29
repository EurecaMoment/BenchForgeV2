"""Transported mesh materials, authored as object-local USD PreviewSurface graphs."""
from pathlib import Path
import numpy as np
from pxr import Gf, Sdf, UsdGeom, UsdShade, Vt
from material_controls import apply_dielectric_controls


def imported_texture_material(stage, name, record, root, appearance, vertex_colors=False):
    """Keep source maps; explicit gloss controls replace factors, retaining maps.

    glTF metallic-roughness uses G/B channels. Normal RGB decodes to [-1, 1].
    Opacity and glTF material extensions are not converted.
    """
    root = Path(root).resolve()
    paths = {slot: (root / path).resolve() for slot, path in record.get('textures', {}).items()}
    for path in paths.values():
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('imported texture is missing or outside asset root: ' + str(path))
    material = UsdShade.Material.Define(stage, '/World/Materials/' + name)
    shader = UsdShade.Shader.Define(stage, str(material.GetPath()) + '/Surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    applied, bound = [], []
    values = {}
    for field, default in (('roughness', .55), ('metallic', 0.)):
        source = float(record.get(field + '_factor', default))
        value = float(appearance.get(field, source))
        values[field] = value
        shader.CreateInput(field, Sdf.ValueTypeNames.Float).Set(value)
        applied.append({'field': field, 'source_value': source, 'value': value,
                        'origin': 'scene_appearance' if field in appearance else 'source_material',
                        'meaning': 'texture multiplier' if 'metallic_roughness' in paths else 'scalar',
                        'shader': str(shader.GetPath())})
    dielectric=apply_dielectric_controls(shader,appearance)
    applied.extend(dielectric['applied'])
    if paths:
        reader = UsdShade.Shader.Define(stage, str(material.GetPath()) + '/UVReader')
        reader.CreateIdAttr('UsdPrimvarReader_float2')
        reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')

    def texture(slot, color_space, scale=(1., 1., 1., 1.), bias=(0., 0., 0., 0.)):
        node = UsdShade.Shader.Define(stage, str(material.GetPath()) + '/' + slot)
        node.CreateIdAttr('UsdUVTexture')
        node.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(paths[slot])))
        node.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
        node.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set(color_space)
        node.CreateInput('wrapS', Sdf.ValueTypeNames.Token).Set('repeat')
        node.CreateInput('wrapT', Sdf.ValueTypeNames.Token).Set('repeat')
        node.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*scale))
        node.CreateInput('bias', Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*bias))
        bound.append({'slot': slot, 'path': str(paths[slot]), 'source_color_space': color_space})
        return node.ConnectableAPI()

    factor = list(record.get('base_color_factor', [1., 1., 1., 1.]))
    if 'base_color' in paths:
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(
            texture('base_color', 'sRGB', (*factor[:3], 1.)), 'rgb')
        base_binding = 'base_color_uv'
    elif vertex_colors:
        reader_color = UsdShade.Shader.Define(stage, str(material.GetPath()) + '/Color')
        reader_color.CreateIdAttr('UsdPrimvarReader_float3')
        reader_color.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('displayColor')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(reader_color.ConnectableAPI(), 'result')
        base_binding = 'vertex_color'
    else:
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*factor[:3]))
        base_binding = 'source_factor'
    if 'metallic_roughness' in paths:
        mr = texture('metallic_roughness', 'raw', (1., values['roughness'], values['metallic'], 1.))
        shader.GetInput('roughness').ConnectToSource(mr, 'g')
        shader.GetInput('metallic').ConnectToSource(mr, 'b')
    if 'normal' in paths:
        shader.CreateInput('normal', Sdf.ValueTypeNames.Normal3f).ConnectToSource(
            texture('normal', 'raw', (2., 2., 2., 1.), (-1., -1., -1., 0.)), 'rgb')
    if 'occlusion' in paths:
        shader.CreateInput('occlusion', Sdf.ValueTypeNames.Float).ConnectToSource(texture('occlusion', 'raw'), 'r')
    emission = record.get('emissive_factor') or [0., 0., 0.]
    if 'emissive' in paths:
        shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(
            texture('emissive', 'sRGB', (*emission[:3], 1.)), 'rgb')
    elif any(emission):
        shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emission[:3]))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    skipped = []
    if len(factor) > 3 and factor[3] != 1.:
        skipped.append({'field': 'base_color_alpha', 'reason': 'imported opacity is unsupported; remains opaque'})
    return material, {'material': str(material.GetPath()), 'applied': applied, 'skipped': skipped,
                      'bound_textures': bound,
                      'base_color': {'factor_rgb': factor[:3], 'factor_space': 'linear', 'binding': base_binding},
                      'calibration': 'unmeasured synthetic material prior'}


def bind_imported_materials(stage, mesh, record, root, name, appearance):
    """Bind every source material subset, including factors without an image/UV."""
    faces = np.asarray(record['faces'], dtype=np.int64)
    if record.get('texcoords'):
        uv = np.asarray(record['texcoords'], dtype=np.float32)[faces].reshape((-1, 2))
        st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.Float2Array, UsdGeom.Tokens.faceVarying)
        st.Set(Vt.Vec2fArray.FromNumpy(uv))
    indices = np.asarray(record.get('material_index', []))
    receipts = []
    for mi, source in enumerate(record.get('materials', [])):
        face_ids = np.flatnonzero(indices == mi).astype(np.int32)
        if not len(face_ids):
            continue
        subset = UsdShade.MaterialBindingAPI(mesh).CreateMaterialBindSubset(
            'MaterialSubset_' + str(mi), Vt.IntArray.FromNumpy(face_ids), UsdGeom.Tokens.face)
        material, receipt = imported_texture_material(stage, name + '_pbr_' + str(mi), source, root, appearance,
                                                       vertex_colors=not source.get('source_material_type'))
        UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(material)
        receipts.append({'material_index': mi, **receipt})
    slots = sorted({item['slot'] for receipt in receipts for item in receipt['bound_textures']})
    return {'bound_materials': len(receipts),
            'bound_texture_materials': sum(bool(item['bound_textures']) for item in receipts),
            'bound_texture_slots': slots,
            'texture_sampling': 'pbr_texture_uv' if slots else ('source_material_factors' if any(
                item['base_color']['binding'] == 'source_factor' for item in receipts) else 'vertex_color_fallback'),
            'appearance_overrides': receipts}
