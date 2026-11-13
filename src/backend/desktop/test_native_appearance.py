import unittest
from pathlib import Path
from pxr import Usd, UsdGeom, UsdShade, Sdf
from native_appearance import apply_native_appearance


class NativeAppearanceTests(unittest.TestCase):
    @unittest.skipUnless(Path('D:/fangzhenqi/isaacsim_assets_4.5/Assets/Isaac/4.5/Isaac/Props/KLT_Bin/small_KLT_visual_collision.usd').is_file(),'installed desktop bin needed')
    def test_omnipbr_defaults_can_be_overridden_without_replacing_native_texture(self):
        asset='D:/fangzhenqi/isaacsim_assets_4.5/Assets/Isaac/4.5/Isaac/Props/KLT_Bin/small_KLT_visual_collision.usd'
        stage=Usd.Stage.CreateInMemory()
        root=UsdGeom.Xform.Define(stage,'/Bin');root.GetPrim().GetReferences().AddReference(asset)
        other=UsdGeom.Xform.Define(stage,'/Other');other.GetPrim().GetReferences().AddReference(asset)
        receipts=apply_native_appearance(stage,root.GetPrim(),{'roughness':.15,'metallic':.7,'specular':.3,'ior':1.8})
        self.assertEqual(len(receipts),3)
        for receipt in receipts:
            self.assertEqual({r['field'] for r in receipt['applied']},{'roughness','metallic','specular'})
            self.assertEqual([r['field'] for r in receipt['skipped']],['ior'])
            local=UsdShade.Shader(stage.GetPrimAtPath(receipt['override_material']+'/Shader'))
            source=UsdShade.Shader(stage.GetPrimAtPath(receipt['source_material']+'/Shader'))
            untouched=UsdShade.Shader(stage.GetPrimAtPath(receipt['source_material'].replace('/Bin/','/Other/')+'/Shader'))
            for name,value in [('reflection_roughness_constant',.15),('metallic_constant',.7),('specular_level',.3)]:
                self.assertAlmostEqual(local.GetInput(name).Get(),value)
                self.assertFalse(source.GetInput(name))
                self.assertFalse(untouched.GetInput(name))
            self.assertEqual(local.GetInput('diffuse_texture').Get(),source.GetInput('diffuse_texture').Get())
            self.assertTrue(Path(local.GetInput('diffuse_texture').Get().resolvedPath).is_file())
            self.assertEqual(local.GetSourceAsset('mdl'),source.GetSourceAsset('mdl'))

    def test_omnipbr_connected_input_keeps_graph_and_texture_blend(self):
        stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Object')
        mesh=UsdGeom.Cube.Define(stage,'/Object/Geometry');material=UsdShade.Material.Define(stage,'/Original')
        shader=UsdShade.Shader.Define(stage,'/Original/Shader')
        shader.SetSourceAsset(Sdf.AssetPath('OmniPBR.mdl'),'mdl');shader.SetSourceAssetSubIdentifier('OmniPBR','mdl')
        texture=UsdShade.Shader.Define(stage,'/Original/Texture');texture.CreateOutput('r',Sdf.ValueTypeNames.Float)
        shader.CreateInput('reflection_roughness_constant',Sdf.ValueTypeNames.Float).ConnectToSource(texture.ConnectableAPI(),'r')
        shader.CreateInput('reflection_roughness_texture_influence',Sdf.ValueTypeNames.Float).Set(.75)
        material.CreateSurfaceOutput('mdl').ConnectToSource(shader.ConnectableAPI(),'out')
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
        result=apply_native_appearance(stage,root.GetPrim(),{'roughness':.1,'metallic':.6})[0]
        self.assertEqual([r['field'] for r in result['applied']],['metallic'])
        self.assertEqual([r['field'] for r in result['skipped']],['roughness'])
        local=UsdShade.Shader(stage.GetPrimAtPath(result['override_material']+'/Shader'))
        self.assertTrue(local.GetInput('reflection_roughness_constant').HasConnectedSource())
        self.assertEqual(local.GetInput('reflection_roughness_texture_influence').Get(),.75)

    def test_shared_textured_material_is_preserved_and_override_is_object_local(self):
        stage=Usd.Stage.CreateInMemory()
        material=UsdShade.Material.Define(stage,'/Shared/Material')
        shader=UsdShade.Shader.Define(stage,'/Shared/Material/Surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.8)
        tex=UsdShade.Shader.Define(stage,'/Shared/Material/Texture')
        tex.CreateIdAttr('UsdUVTexture');tex.CreateInput('file',Sdf.ValueTypeNames.Asset).Set('wood.png')
        shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).ConnectToSource(tex.ConnectableAPI(),'rgb')
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        roots=[]
        for name in ['A','B']:
            root=UsdGeom.Xform.Define(stage,'/'+name);roots.append(root)
            cube=UsdGeom.Cube.Define(stage,'/'+name+'/Geometry')
            UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(material)
        result=apply_native_appearance(stage,roots[0].GetPrim(),{'roughness':.35})
        self.assertEqual(len(result),1)
        a,_=UsdShade.MaterialBindingAPI(stage.GetPrimAtPath('/A/Geometry')).ComputeBoundMaterial()
        b,_=UsdShade.MaterialBindingAPI(stage.GetPrimAtPath('/B/Geometry')).ComputeBoundMaterial()
        self.assertEqual(str(b.GetPath()),'/Shared/Material')
        self.assertAlmostEqual(shader.GetInput('roughness').Get(),.8)
        local=UsdShade.Shader(stage.GetPrimAtPath(str(a.GetPath())+'/Surface'))
        self.assertAlmostEqual(local.GetInput('roughness').Get(),.35)
        source=local.GetInput('diffuseColor').GetConnectedSource()[0]
        self.assertEqual(str(source.GetPath()),str(a.GetPath())+'/Texture')
        self.assertEqual(source.GetInput('file').Get().path,'wood.png')

    def test_native_mdl_texture_multiplier_keeps_other_channels_and_reports_skips(self):
        stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Object')
        mesh=UsdGeom.Cube.Define(stage,'/Object/Geometry')
        material=UsdShade.Material.Define(stage,'/Original')
        shader=UsdShade.Shader.Define(stage,'/Original/MDL')
        shader.CreateInput('RoughnessMultiplier',Sdf.ValueTypeNames.Float).Set(1)
        shader.CreateInput('BaseColor',Sdf.ValueTypeNames.Asset).Set('native_color.png')
        material.CreateSurfaceOutput('mdl').ConnectToSource(shader.ConnectableAPI(),'out')
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
        report=apply_native_appearance(stage,root.GetPrim(),{'roughness':.4,'metallic':0})[0]
        self.assertEqual(report['applied'][0]['meaning'],'native_texture_multiplier')
        self.assertEqual(report['skipped'][0]['field'],'metallic')
        local=UsdShade.Shader(stage.GetPrimAtPath(report['override_material']+'/MDL'))
        self.assertEqual(local.GetInput('BaseColor').Get().path,'native_color.png')
        self.assertEqual(shader.GetInput('RoughnessMultiplier').Get(),1)

    def test_native_opacity_rejects_connected_wrong_type_and_non_mdl_inputs(self):
        for mode in ('connected','vector','non_mdl','missing'):
            with self.subTest(mode=mode):
                stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Object')
                mesh=UsdGeom.Cube.Define(stage,'/Object/Geometry')
                material=UsdShade.Material.Define(stage,'/Original')
                shader=UsdShade.Shader.Define(stage,'/Original/MDL')
                if mode!='non_mdl':shader.SetSourceAsset(Sdf.AssetPath('native.mdl'),'mdl')
                if mode!='missing':
                    inp=shader.CreateInput('Opacity_Multiply',Sdf.ValueTypeNames.Float3 if mode=='vector' else Sdf.ValueTypeNames.Float)
                    if mode=='connected':
                        source=UsdShade.Shader.Define(stage,'/Original/Texture')
                        source.CreateOutput('alpha',Sdf.ValueTypeNames.Float)
                        inp.ConnectToSource(source.ConnectableAPI(),'alpha')
                material.CreateSurfaceOutput('mdl').ConnectToSource(shader.ConnectableAPI(),'out')
                UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
                with self.assertRaisesRegex(ValueError,'no material accepted'):
                    apply_native_appearance(stage,root.GetPrim(),{'native_opacity_multiplier':.2})
                bound,_=UsdShade.MaterialBindingAPI(mesh.GetPrim()).ComputeBoundMaterial()
                self.assertEqual(bound.GetPath(),material.GetPath())

    @unittest.skipUnless(Path('D:/fangzhenqi/isaacsim_assets_4.5/Assets/Isaac/4.5/Isaac/Environments/Office/Props/SM_Window_3m_A.usd').is_file(),'installed desktop native window needed')
    def test_installed_window_opacity_changes_only_local_glass_keeps_source_frame_and_texture(self):
        asset='D:/fangzhenqi/isaacsim_assets_4.5/Assets/Isaac/4.5/Isaac/Environments/Office/Props/SM_Window_3m_A.usd'
        stage=Usd.Stage.CreateInMemory()
        roots=[]
        for name in ('Default','Modified'):
            root=UsdGeom.Xform.Define(stage,'/'+name)
            root.GetPrim().GetReferences().AddReference(asset);roots.append(root.GetPrim())
        source_layers={layer.identifier:layer.ExportToString() for layer in stage.GetUsedLayers() if layer!=stage.GetRootLayer()}
        before_geometry=[(str(p.GetPath()),p.GetAttribute('points').Get()) for p in Usd.PrimRange(roots[1]) if p.IsA(UsdGeom.Mesh)]
        receipts=apply_native_appearance(stage,roots[1],{'native_opacity_multiplier':.2})
        glass=[r for r in receipts if r['applied']]
        self.assertEqual(len(glass),1)
        applied=glass[0]['applied'];self.assertEqual(len(applied),1)
        self.assertEqual(applied[0]['input'],'Opacity_Multiply')
        self.assertIn('not_calibrated_transmittance',applied[0]['meaning'])
        local=UsdShade.Shader(stage.GetPrimAtPath(applied[0]['shader']))
        self.assertAlmostEqual(local.GetInput('Opacity_Multiply').Get(),.2)
        original=UsdShade.Shader(stage.GetPrimAtPath(glass[0]['source_material']+'/MI_DoorEntrance_glass'))
        self.assertEqual(original.GetInput('Opacity_Multiply').Get(),1.)
        self.assertEqual(local.GetInput('BaseColor').Get(),original.GetInput('BaseColor').Get())
        self.assertTrue(any(r['override_material'] is None and 'MI_Window_glass' not in r['source_material'] for r in receipts))
        self.assertEqual(source_layers,{layer.identifier:layer.ExportToString() for layer in stage.GetUsedLayers() if layer!=stage.GetRootLayer()})
        self.assertEqual(before_geometry,[(str(p.GetPath()),p.GetAttribute('points').Get()) for p in Usd.PrimRange(roots[1]) if p.IsA(UsdGeom.Mesh)])
        other=UsdShade.Shader(stage.GetPrimAtPath('/Default/Looks/MI_Window_glass/MI_DoorEntrance_glass'))
        self.assertEqual(other.GetInput('Opacity_Multiply').Get(),1.)

if __name__=='__main__':unittest.main()
