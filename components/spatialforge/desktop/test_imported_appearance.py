import copy
from pathlib import Path
import tempfile
import unittest
from pxr import Usd, UsdGeom, UsdShade
from imported_appearance import imported_texture_material, bind_imported_materials
from scene_runtime import material_for


class ImportedAppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'base.png').write_bytes(b'fixture path only; graph test does not decode')
        self.record = {'textures': {'base_color': 'base.png'}, 'base_color_factor': [.5, .75, .25, 1.],
                       'roughness_factor': .65, 'metallic_factor': .2}

    def test_overrides_reach_bound_shader_and_do_not_change_other_instances_or_source(self):
        stage = Usd.Stage.CreateInMemory()
        before = copy.deepcopy(self.record)
        base, receipt = imported_texture_material(stage, 'base', self.record, self.root, {})
        shiny, changed = imported_texture_material(stage, 'shiny', self.record, self.root, {'roughness': .08, 'metallic': 1.})
        for material, roughness, metallic in ((base, .65, .2), (shiny, .08, 1.)):
            shader = UsdShade.Shader(material.GetSurfaceOutput().GetConnectedSource()[0].GetPrim())
            self.assertAlmostEqual(shader.GetInput('roughness').Get(), roughness)
            self.assertAlmostEqual(shader.GetInput('metallic').Get(), metallic)
        self.assertEqual({a['origin'] for a in changed['applied']}, {'scene_appearance'})
        self.assertEqual({a['origin'] for a in receipt['applied']}, {'source_material'})
        self.assertEqual(self.record, before)

    def test_named_material_merges_before_applying_textured_subset(self):
        program = {'materials': [{'id': 'finish', 'roughness': .3, 'metallic': .8}]}
        obj = {'material_id': 'finish', 'appearance': {'roughness': .1}}
        effective = material_for(program, obj)['appearance']
        stage = Usd.Stage.CreateInMemory()
        material, _ = imported_texture_material(stage, 'object', self.record, self.root, effective)
        shader = UsdShade.Shader(stage.GetPrimAtPath(str(material.GetPath()) + '/Surface'))
        self.assertAlmostEqual(shader.GetInput('roughness').Get(), .1)
        self.assertAlmostEqual(shader.GetInput('metallic').Get(), .8)

    def test_source_tint_and_normal_decoding_preserve_uv_binding(self):
        self.record['textures']['normal'] = 'normal.png'
        (self.root / 'normal.png').write_bytes(b'graph test')
        self.record['base_color_factor'][3] = .4
        stage = Usd.Stage.CreateInMemory()
        material, receipt = imported_texture_material(stage, 'tinted', self.record, self.root, {})
        shader = UsdShade.Shader(stage.GetPrimAtPath(str(material.GetPath()) + '/Surface'))
        texture = UsdShade.Shader(shader.GetInput('diffuseColor').GetConnectedSource()[0].GetPrim())
        self.assertEqual(texture.GetInput('sourceColorSpace').Get(), 'sRGB')
        self.assertEqual(list(texture.GetInput('scale').Get()), [.5, .75, .25, 1.])
        self.assertEqual(texture.GetInput('file').Get().path, str(self.root / 'base.png'))
        reader = texture.GetInput('st').GetConnectedSource()[0]
        self.assertEqual(reader.GetInput('varname').Get(), 'st')
        self.assertEqual({x['field'] for x in receipt['skipped']}, {'base_color_alpha'})
        normal = UsdShade.Shader(shader.GetInput('normal').GetConnectedSource()[0].GetPrim())
        self.assertEqual(normal.GetInput('sourceColorSpace').Get(), 'raw')
        self.assertEqual(list(normal.GetInput('scale').Get()), [2., 2., 2., 1.])
        self.assertEqual(list(normal.GetInput('bias').Get()), [-1., -1., -1., 0.])
        self.assertFalse(shader.GetInput('opacity'))

    def test_packed_maps_keep_channel_semantics_and_override_factors(self):
        self.record['textures'] = {s: s+'.png' for s in ('metallic_roughness','occlusion','emissive')}
        for path in self.record['textures'].values(): (self.root/path).write_bytes(b'graph test')
        self.record['emissive_factor'] = [.2,.4,.6]
        stage = Usd.Stage.CreateInMemory()
        material, receipt = imported_texture_material(stage,'mapped',self.record,self.root,{'roughness':.3})
        shader = UsdShade.Shader(stage.GetPrimAtPath(str(material.GetPath())+'/Surface'))
        for field, channel in (('roughness','g'),('metallic','b'),('occlusion','r'),('emissiveColor','rgb')):
            connected = shader.GetInput(field).GetConnectedSource()
            self.assertEqual(connected[1],channel)
        roughness = shader.GetInput('roughness').GetConnectedSource()[0]
        self.assertAlmostEqual(roughness.GetInput('scale').Get()[1],.3)
        self.assertAlmostEqual(roughness.GetInput('scale').Get()[2],.2)
        emission = shader.GetInput('emissiveColor').GetConnectedSource()[0]
        self.assertEqual(emission.GetInput('sourceColorSpace').Get(),'sRGB')
        self.assertAlmostEqual(emission.GetInput('scale').Get()[2],.6)
        self.assertEqual(len(receipt['bound_textures']),3)

    def test_real_glb_material_subsets_without_uv_preserve_metal_and_rubber(self):
        import trimesh
        from spatialforge.mesh_export import export_mesh
        scene = trimesh.Scene()
        for index, (metal, rough) in enumerate(((1.,.18),(0.,.87))):
            part = trimesh.creation.box()
            part.apply_translation([index*2,0,0])
            part.visual = trimesh.visual.texture.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=[.4,.5,.6,1.],metallicFactor=metal,roughnessFactor=rough))
            scene.add_geometry(part)
        source = self.root/'parts.glb'
        source.write_bytes(scene.export(file_type='glb'))
        record = export_mesh(source,self.root/'mesh.json',source_frame='z_up')
        self.assertEqual(record['texcoords'],[])
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage,'/World/Objects/parts/Geometry')
        mesh.CreateFaceVertexCountsAttr([3]*len(record['faces']))
        receipt = bind_imported_materials(stage,mesh,record,self.root,'parts',{})
        self.assertEqual(UsdShade.MaterialBindingAPI(mesh).GetMaterialBindSubsetsFamilyType(), UsdGeom.Tokens.nonOverlapping)
        self.assertEqual(receipt['bound_materials'],2)
        self.assertEqual(receipt['bound_texture_materials'],0)
        self.assertEqual(receipt['texture_sampling'],'source_material_factors')
        values = []
        for i in range(2):
            subset = stage.GetPrimAtPath(str(mesh.GetPath())+'/MaterialSubset_'+str(i))
            material = UsdShade.MaterialBindingAPI(subset).ComputeBoundMaterial()[0]
            shader = UsdShade.Shader(material.GetSurfaceOutput().GetConnectedSource()[0].GetPrim())
            values.append((round(shader.GetInput('metallic').Get(),2),round(shader.GetInput('roughness').Get(),2)))
        self.assertEqual(set(values),{(1.,.18),(0.,.87)})

    def test_missing_or_external_texture_is_not_reported_as_bound(self):
        stage = Usd.Stage.CreateInMemory()
        for path in ('missing.png', '../base.png'):
            self.record['textures']['base_color'] = path
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'missing or outside'):
                imported_texture_material(stage, 'bad', self.record, self.root, {})
        self.assertFalse(stage.GetPrimAtPath('/World/Materials/bad'))


if __name__ == '__main__':
    unittest.main()
