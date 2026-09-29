import importlib.util
from pathlib import Path
import unittest
from pxr import Sdf,Usd,UsdGeom,UsdPhysics
from spatialforge.contracts import validate_program

spec=importlib.util.spec_from_file_location('object_shadows',Path(__file__).resolve().parents[1]/'desktop/object_shadows.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ObjectShadows(unittest.TestCase):
    def test_default_and_explicit_flags_preserve_hidden_mesh_and_splat_data(self):
        stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Object').GetPrim()
        mesh=UsdGeom.Cube.Define(stage,'/Object/Geometry');mesh.MakeInvisible();UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        splat=stage.DefinePrim('/Object/Gaussian','ParticleField3DGaussianSplat')
        splat.CreateAttribute('positions',Sdf.ValueTypeNames.Point3fArray).Set([(1,2,3)])
        splat.CreateAttribute('radiance:sphericalHarmonicsCoefficients',Sdf.ValueTypeNames.Float3Array).Set([(.1,.2,.3)])
        before={a.GetName():a.Get() for a in splat.GetAttributes()}
        mesh_before=stage.GetRootLayer().GetPrimAtPath('/Object/Geometry').GetInfo('specifier')
        receipt=module.apply_object_shadows(root)
        self.assertEqual(receipt,[{'prim_path':'/Object/Gaussian','casts_shadows':True,'source':'paired_gaussian_default'}])
        self.assertFalse(splat.GetAttribute('primvars:doNotCastShadows').Get())
        self.assertFalse(mesh.GetPrim().HasAttribute('primvars:doNotCastShadows'))
        self.assertEqual(len(module.apply_object_shadows(root,False)),2)
        self.assertTrue(splat.GetAttribute('primvars:doNotCastShadows').Get())
        self.assertTrue(mesh.GetPrim().GetAttribute('primvars:doNotCastShadows').Get())
        self.assertEqual(mesh.GetVisibilityAttr().Get(),'invisible')
        self.assertTrue(mesh.GetPrim().HasAPI(UsdPhysics.CollisionAPI))
        self.assertEqual(stage.GetRootLayer().GetPrimAtPath('/Object/Geometry').GetInfo('specifier'),mesh_before)
        for key,value in before.items():self.assertEqual(splat.GetAttribute(key).Get(),value)
        module.apply_object_shadows(root,True)
        self.assertFalse(splat.GetAttribute('primvars:doNotCastShadows').Get())

    def test_object_option_is_accepted_without_mutating_program(self):
        import copy
        p={'schema':'spatialforge.scene/v2','scene_id':'ShadowFixture','title':'Shadow fixture',
           'objects':[{'id':'box','label':'box','kind':'box','size':[1,1,1],'xy':[0,0],
                       'base_z':0,'support':'ground','color':[.5,.5,.5],'dynamic':False,'mass_kg':0,'cast_shadows':False}],
           'cameras':[{'position':[2,-3,2],'target':[0,0,.5]}],'assumptions':[]}
        before=copy.deepcopy(p);validate_program(p);self.assertEqual(p,before)
        p['objects'][0]['cast_shadows']='false'
        with self.assertRaisesRegex(ValueError,'cast_shadows must be boolean'):validate_program(p)


if __name__=='__main__':unittest.main()
