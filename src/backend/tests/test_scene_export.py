import importlib.util
import tempfile
import unittest
from pathlib import Path
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdPhysics, UsdUtils

spec=importlib.util.spec_from_file_location('scene_export',Path(__file__).resolve().parents[1]/'desktop/scene_export.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class SceneExport(unittest.TestCase):
    def test_images_remain_resolvable_after_relocation_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);library=root/'library';library.mkdir()
            (library/'other').mkdir()
            expected=[b'first texture',b'second texture',b'hdr fixture']
            (library/'wood.JPG').write_bytes(expected[0])
            (library/'other/wood.JPG').write_bytes(expected[1])
            (library/'sky.hdr').write_bytes(expected[2])
            stage=Usd.Stage.CreateNew(str(library/'source.usda'))
            prim=stage.DefinePrim('/Material')
            texture=prim.CreateAttribute('texture',Sdf.ValueTypeNames.Asset)
            texture.Set(Sdf.AssetPath('./wood.JPG'))
            duplicate=prim.CreateAttribute('duplicate',Sdf.ValueTypeNames.Asset)
            duplicate.Set(Sdf.AssetPath(str(library/'wood.JPG')))
            array=prim.CreateAttribute('images',Sdf.ValueTypeNames.AssetArray)
            array.Set([Sdf.AssetPath('./wood.JPG'),Sdf.AssetPath('./other/wood.JPG')])
            animated=prim.CreateAttribute('sky',Sdf.ValueTypeNames.Asset)
            animated.Set(Sdf.AssetPath('./sky.hdr'),1)
            prim.CreateAttribute('module',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('./native.mdl'))
            prim.CreateAttribute('missing',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('./missing.png'))
            before=stage.GetRootLayer().ExportToString()
            output=root/'capture';output.mkdir()
            receipt=module.export_scene(stage,output)
            self.assertEqual(stage.GetRootLayer().ExportToString(),before)
            self.assertEqual(len(receipt['scene_resources']),3)
            self.assertCountEqual([Path(p) for p in receipt['scene_resources_unresolved']],[library/'missing.png',library/'native.mdl'])
            self.assertCountEqual([(output/r['file']).read_bytes() for r in receipt['scene_resources']],expected)
            relocated=root/'relocated';output.rename(relocated)
            library.rename(root/'unavailable-library')
            reopened=Usd.Stage.Open(str(relocated/'scene.usda'))
            first=reopened.GetAttributeAtPath('/Material.texture').Get()
            self.assertEqual(first.path,reopened.GetAttributeAtPath('/Material.duplicate').Get().path)
            values=[first,*reopened.GetAttributeAtPath('/Material.images').Get(),reopened.GetAttributeAtPath('/Material.sky').Get(1)]
            self.assertEqual([Path(v.resolvedPath).read_bytes() for v in values],[expected[0],*expected[:2],expected[2]])
            self.assertTrue(all(Path(v.resolvedPath).parent==relocated for v in values))
            self.assertEqual(Path(reopened.GetAttributeAtPath('/Material.module').Get().path),library/'native.mdl')
            self.assertEqual(Path(reopened.GetAttributeAtPath('/Material.missing').Get().path),library/'missing.png')

    def test_crate_entry_preserves_composition_and_authored_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            asset=Usd.Stage.CreateNew(str(root/'native.usda'))
            UsdGeom.Cube.Define(asset,'/Native');asset.GetRootLayer().Save()
            stage=Usd.Stage.CreateNew(str(root/'source.usda'))
            UsdGeom.SetStageUpAxis(stage,'Z');UsdGeom.SetStageMetersPerUnit(stage,1)
            world=UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(world.GetPrim())
            mesh=UsdGeom.Mesh.Define(stage,'/World/Part')
            mesh.CreatePointsAttr([(0,0,0),(1,0,0),(0,1,0)])
            mesh.CreateFaceVertexCountsAttr([3]);mesh.CreateFaceVertexIndicesAttr([0,1,2])
            mesh.CreateNormalsAttr([(0,0,1)]*3);mesh.SetNormalsInterpolation('faceVarying')
            uv=UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'faceVarying')
            uv.Set([(0,0),(1,0),(0,1)])
            mesh.AddTranslateOp().Set(Gf.Vec3d(.2,.3,.4),1)
            UsdPhysics.MassAPI.Apply(mesh.GetPrim()).CreateMassAttr(4)
            material=UsdShade.Material.Define(stage,'/World/Metal')
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
            prim=stage.DefinePrim('/World/Imported');prim.GetReferences().AddReference('./native.usda','/Native')
            receipt=module.export_scene(stage,root)
            (root/'native.usda').unlink()
            self.assertEqual(receipt['scene_format'],'usdc')
            self.assertEqual((root/'scene.usdc').read_bytes()[:8],b'PXR-USDC')
            reopened=Usd.Stage.Open(str(root/'scene.usda'))
            self.assertEqual(reopened.GetDefaultPrim().GetPath(),'/World')
            self.assertEqual(UsdGeom.GetStageUpAxis(reopened),'Z')
            self.assertEqual(UsdGeom.GetStageMetersPerUnit(reopened),1)
            self.assertEqual(reopened.GetPrimAtPath('/World/Imported').GetTypeName(),'Cube')
            for attr in mesh.GetPrim().GetAttributes():
                target=reopened.GetAttributeAtPath(attr.GetPath())
                self.assertEqual(target.Get(),attr.Get())
                for time in attr.GetTimeSamples():self.assertEqual(target.Get(time),attr.Get(time))
            self.assertEqual(reopened.GetRelationshipAtPath('/World/Part.material:binding').GetTargets(),[Sdf.Path('/World/Metal')])

    def test_referenced_material_and_mdl_resources_survive_library_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);library=root/'library';library.mkdir()
            (library/'wood.png').write_bytes(b'texture')
            (library/'Base.mdl').write_text('mdl 1.3; export float base() = 1.0;')
            (library/'Mat.mdl').write_text('mdl 1.3; using .::Base import *; export material mat(uniform texture_2d t = texture_2d("wood.png")) = material();')
            native=Usd.Stage.CreateNew(str(library/'native.usda'))
            prim=UsdGeom.Cube.Define(native,'/Object').GetPrim()
            prim.CreateAttribute('module',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('./Mat.mdl'))
            native.GetRootLayer().Save()
            stage=Usd.Stage.CreateInMemory()
            stage.DefinePrim('/Imported').GetReferences().AddReference(str(library/'native.usda'),'/Object')
            output=root/'capture';output.mkdir()
            receipt=module.export_scene(stage,output)
            library.rename(root/'unavailable-library')
            reopened=Usd.Stage.Open(str(output/'scene.usda'))
            self.assertEqual(reopened.GetPrimAtPath('/Imported').GetTypeName(),'Cube')
            layers,assets,unresolved=UsdUtils.ComputeAllDependencies(str(output/'scene.usda'))
            self.assertEqual(unresolved,[])
            self.assertTrue(all(Path(p).is_relative_to(output) for p in assets))
            paths={Path(r['source']).name:output/r['file'] for r in receipt['scene_resources']}
            text=paths['Mat.mdl'].read_text()
            self.assertIn('using .::'+paths['Base.mdl'].stem+' import *;',text)
            self.assertIn('texture_2d("'+paths['wood.png'].name+'")',text)
            self.assertEqual(paths['wood.png'].read_bytes(),b'texture')


if __name__=='__main__':unittest.main()
