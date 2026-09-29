"""Layer gloss overrides over native USD shading without replacing its graph."""
from pxr import Usd, UsdGeom, UsdShade, Sdf
from material_controls import apply_dielectric_controls


def apply_native_appearance(stage, root, appearance):
    requested = {k:appearance[k] for k in ('roughness','metallic','specular','ior','native_opacity_multiplier') if k in appearance}
    if not requested:return []
    bindings = {}
    for prim in Usd.PrimRange(root):
        if not (prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.Subset)):continue
        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if material:bindings.setdefault(str(material.GetPath()), []).append(prim)
    receipts = []
    for index, (source, prims) in enumerate(bindings.items()):
        local_path = str(root.GetPath())+'/GlossOverrides/Material_'+str(index)
        material = UsdShade.Material.Define(stage, local_path)
        material.GetPrim().GetReferences().AddInternalReference(source)
        applied = []; skipped = []
        for prim in Usd.PrimRange(material.GetPrim()):
            if not prim.IsA(UsdShade.Shader):continue
            shader = UsdShade.Shader(prim)
            sid = shader.GetIdAttr().Get()
            mdl = shader.GetSourceAsset('mdl')
            omnipbr = bool(mdl and mdl.path.replace('\\','/').rsplit('/',1)[-1] == 'OmniPBR.mdl'
                           and shader.GetSourceAssetSubIdentifier('mdl') == 'OmniPBR')
            if sid == 'UsdPreviewSurface':
                dielectric=apply_dielectric_controls(shader,requested)
                applied.extend(dielectric['applied']);skipped.extend(dielectric['skipped'])
            for field, value in requested.items():
                if field == 'ior' or (field == 'specular' and not omnipbr):continue
                if field == 'native_opacity_multiplier':
                    if not shader.GetSourceAsset('mdl') or not shader.GetInput('Opacity_Multiply'):continue
                    name = 'Opacity_Multiply'; meaning = 'native_alpha_multiplier_not_calibrated_transmittance'
                elif sid == 'UsdPreviewSurface':name = field; meaning = 'scalar'
                elif omnipbr:
                    # MDL defaults need not have authored USD inputs.
                    name = {'roughness':'reflection_roughness_constant','metallic':'metallic_constant',
                            'specular':'specular_level'}[field]
                    meaning = 'native_scalar' if field == 'specular' else 'native_constant_with_existing_texture_blend'
                elif field == 'roughness' and shader.GetInput('RoughnessMultiplier'):
                    name = 'RoughnessMultiplier'; meaning = 'native_texture_multiplier'
                elif field == 'roughness' and shader.GetInput('reflection_roughness'):
                    name = 'reflection_roughness'; meaning = 'native_scalar'
                elif field == 'metallic' and shader.GetInput('metallic_constant'):
                    name = 'metallic_constant'; meaning = 'native_scalar'
                else:continue
                inp = shader.GetInput(name)
                if inp and inp.GetTypeName() not in (Sdf.ValueTypeNames.Float,Sdf.ValueTypeNames.Double):
                    skipped.append({'field':field,'reason':'native input is not scalar; original preserved','shader':str(prim.GetPath())})
                    continue
                if inp and inp.HasConnectedSource():
                    skipped.append({'field':field,'reason':'connected input preserved','shader':str(prim.GetPath())})
                    continue
                if not inp:inp = shader.CreateInput(name,Sdf.ValueTypeNames.Float)
                inp.Set(float(value))
                applied.append({'field':field,'input':name,'value':value,'meaning':meaning,'shader':str(prim.GetPath())})
        for field in requested:
            if not any(v['field']==field for v in applied+skipped):
                skipped.append({'field':field,'reason':'unsupported native shader parameter; original preserved'})
        if applied:
            for prim in prims:UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
        receipts.append({'source_material':source,'override_material':local_path if applied else None,
                         'applied':applied,'skipped':skipped,'textures_and_shader_graph':'preserved',
                         'scope':'per_object_stage_layer','calibration':'appearance prior only'})
    if 'native_opacity_multiplier' in requested and not any(a['field']=='native_opacity_multiplier' for r in receipts for a in r['applied']):
        raise ValueError('registered native opacity multiplier unavailable or connected; no material accepted the requested control')
    return receipts
