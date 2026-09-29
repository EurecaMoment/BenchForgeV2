import tempfile
import unittest
from pathlib import Path
from pxr import Usd,UsdShade,UsdGeom,Sdf
from material_controls import apply_dielectric_controls
from imported_appearance import imported_texture_material
from native_appearance import apply_native_appearance
from scene_runtime import material_for
from spatialforge.contracts import validate_appearance


class DielectricControls(unittest.TestCase):
    def test_named_and_object_values_reach_imported_shader_without_losing_metal(self):
        p={'materials':[{'id':'glaze','ior':1.5,'specular':.9,'metallic':.15,'roughness':.2}]}
        appearance=material_for(p,{'material_id':'glaze','appearance':{'ior':2.,'specular':.5}})['appearance']
        validate_appearance(appearance)
        stage=Usd.Stage.CreateInMemory()
        with tempfile.TemporaryDirectory() as tmp:
            record={'base_color_factor':[.1,.3,.4,1],'metallic_factor':.8,'roughness_factor':.4}
            material,receipt=imported_texture_material(stage,'glaze',record,Path(tmp),appearance)
        shader=UsdShade.Shader(stage.GetPrimAtPath(str(material.GetPath())+'/Surface'))
        self.assertEqual(shader.GetInput('ior').Get(),2.)
        self.assertAlmostEqual(shader.GetInput('metallic').Get(),.15)
        self.assertAlmostEqual(shader.GetInput('roughness').Get(),.2)
        self.assertFalse(shader.GetInput('useSpecularWorkflow'))
        self.assertEqual({r['field'] for r in receipt['applied']},{'ior','specular','metallic','roughness'})

    def test_fresnel_controls_preserve_metallic_workflow(self):
        for params,expected in [({'ior':1.5},.04),({'specular':0},0.),({'specular':1},.08),({'ior':2.,'specular':.5},1/9)]:
            with self.subTest(params=params):
                stage=Usd.Stage.CreateInMemory();shader=UsdShade.Shader.Define(stage,'/Surface')
                shader.CreateIdAttr('UsdPreviewSurface')
                shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(1.)
                receipt=apply_dielectric_controls(shader,params)
                actual=shader.GetInput('ior').Get()
                self.assertAlmostEqual(((actual-1)/(actual+1))**2,expected,places=7)
                self.assertAlmostEqual(receipt['applied'][0]['dielectric_f0'],expected)
                self.assertEqual(shader.GetInput('metallic').Get(),1.)
                self.assertFalse(shader.GetInput('useSpecularWorkflow'))

    def test_absent_controls_do_not_author_or_replace_source_ior(self):
        stage=Usd.Stage.CreateInMemory();shader=UsdShade.Shader.Define(stage,'/Surface')
        self.assertEqual(apply_dielectric_controls(shader,{}),{'applied':[],'skipped':[]})
        self.assertFalse(shader.GetInput('ior'))
        shader.CreateInput('ior',Sdf.ValueTypeNames.Float).Set(1.8)
        apply_dielectric_controls(shader,{})
        self.assertAlmostEqual(shader.GetInput('ior').Get(),1.8)

    def test_native_ior_override_is_local_and_does_not_touch_shared_source(self):
        stage=Usd.Stage.CreateInMemory()
        source=UsdShade.Material.Define(stage,'/Shared')
        shader=UsdShade.Shader.Define(stage,'/Shared/Surface');shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('ior',Sdf.ValueTypeNames.Float).Set(1.8)
        shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(.2)
        source.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        root=UsdGeom.Xform.Define(stage,'/Object');mesh=UsdGeom.Cube.Define(stage,'/Object/Cube')
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(source)
        receipt=apply_native_appearance(stage,root.GetPrim(),{'ior':2.})[0]
        local=UsdShade.Shader(stage.GetPrimAtPath(receipt['override_material']+'/Surface'))
        self.assertEqual(local.GetInput('ior').Get(),2.)
        self.assertAlmostEqual(shader.GetInput('ior').Get(),1.8)
        self.assertAlmostEqual(local.GetInput('metallic').Get(),.2)

    def test_native_connected_ior_and_specular_workflow_remain_authored(self):
        for connected in (True,False):
            stage=Usd.Stage.CreateInMemory();shader=UsdShade.Shader.Define(stage,'/Surface')
            if connected:
                source=UsdShade.Shader.Define(stage,'/Texture')
                shader.CreateInput('ior',Sdf.ValueTypeNames.Float).ConnectToSource(source.ConnectableAPI(),'r')
            else:shader.CreateInput('useSpecularWorkflow',Sdf.ValueTypeNames.Int).Set(1)
            receipt=apply_dielectric_controls(shader,{'ior':2.})
            self.assertFalse(receipt['applied'])
            self.assertEqual(receipt['skipped'][0]['field'],'ior')
            if connected:self.assertTrue(shader.GetInput('ior').HasConnectedSource())
            else:self.assertFalse(shader.GetInput('ior'))


if __name__=='__main__':unittest.main()
