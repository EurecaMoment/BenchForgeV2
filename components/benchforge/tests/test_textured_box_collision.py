import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from pxr import Gf,Usd,UsdGeom,UsdPhysics,UsdShade
from primitive_geometry import define_textured_primitive


class TexturedBoxCollision(unittest.TestCase):
    def test_texture_keeps_one_analytic_collider_with_same_transform_and_material(self):
        stage=Usd.Stage.CreateInMemory()
        root=UsdGeom.Xform.Define(stage,'/World/Box')
        material=UsdShade.Material.Define(stage,'/World/Physics')
        UsdPhysics.MaterialAPI.Apply(material.GetPrim()).CreateDynamicFrictionAttr(.5)
        UsdShade.MaterialBindingAPI.Apply(root.GetPrim()).Bind(material,UsdShade.Tokens.strongerThanDescendants,'physics')
        mesh=define_textured_primitive(stage,'/World/Box/Visual','box',[1.3,1.1,.04],[.4,.3,.2],[1.3,.65],
                                       offset=[.1,.2,.3],rotation_deg_xyz=[0,0,30])
        reference=UsdGeom.Cube.Define(stage,'/World/Reference');reference.CreateSizeAttr(1.)
        reference.AddTranslateOp().Set(Gf.Vec3d(.1,.2,.3));reference.AddRotateXYZOp().Set(Gf.Vec3f(0,0,30))
        reference.AddScaleOp().Set(Gf.Vec3f(1.3,1.1,.04))
        collisions=[p for p in Usd.PrimRange(root.GetPrim()) if p.HasAPI(UsdPhysics.CollisionAPI)]
        self.assertEqual(len(collisions),1);self.assertTrue(collisions[0].IsA(UsdGeom.Cube))
        self.assertFalse(mesh.GetPrim().HasAPI(UsdPhysics.CollisionAPI))
        self.assertEqual(UsdGeom.Imageable(collisions[0]).ComputeVisibility(),'invisible')
        self.assertEqual(UsdShade.MaterialBindingAPI(collisions[0]).ComputeBoundMaterial('physics')[0].GetPath(),material.GetPath())
        cache=UsdGeom.XformCache()
        a=cache.GetLocalToWorldTransform(collisions[0]);b=cache.GetLocalToWorldTransform(reference.GetPrim())
        for i in range(4):
            for j in range(4):self.assertAlmostEqual(a[i][j],b[i][j])

if __name__=='__main__':unittest.main()
