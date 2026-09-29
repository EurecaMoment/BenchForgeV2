import copy
import itertools
import math
import unittest

from spatialforge.contracts import validate_program
from spatialforge.geometry_preview import preview_scene_geometry
from spatialforge.part_geometry import part_bounds
from test_contracts import sample


def part(shape='box', size=(.04,.4,.8), rotation=(0,90,0)):
    return dict(shape=shape,size=list(size),rotation_deg_xyz=list(rotation),
                offset=[0,0,0],color=[.4,.3,.2])


class PartRotationTests(unittest.TestCase):
    def test_contract_uses_rotated_envelope_without_rewriting_program(self):
        for schema in ('spatialforge.scene/v1','spatialforge.scene/v2'):
            p=sample();p['schema']=schema
            obj=p['objects'][0]
            obj.update(kind='composite',size=[.4,.05,.05],parts=[part('cylinder',(.05,.05,.4))])
            original=copy.deepcopy(p)
            validate_program(p)
            self.assertEqual(p,original)
            row=preview_scene_geometry(p)['objects'][0]
            for got,want in zip(row['composite_geometry']['size_m'],[.4,.05,.05]):
                self.assertAlmostEqual(got,want)
            obj['parts'][0]['rotation_deg_xyz']=[0,0,0]
            validate_program(p)
            row=preview_scene_geometry(p)['objects'][0]
            self.assertAlmostEqual(row['composite_geometry']['size_m'][2],.4)
            self.assertAlmostEqual(row['whole_object_top_z_m'],.05)
            del obj['parts'][0]['shape']
            with self.assertRaisesRegex(ValueError,'invalid part shape'):validate_program(p)

    def test_rotated_faces_and_child_contact_use_actual_horizontal_surface(self):
        p=sample();obj=p['objects'][0]
        obj.update(kind='composite',size=[.8,.4,.04],xy=[1,2],base_z=.6,yaw_deg=30,
                   parts=[part()])
        child=copy.deepcopy(sample()['objects'][0])
        child.update(id='child',size=[.1,.1,.1],xy=[1,2],support=obj['id'])
        p['objects'].append(child)
        validate_program(p)
        row=preview_scene_geometry(p)['objects'][0]
        face=row['box_top_faces'][0]
        self.assertAlmostEqual(face['top_z_m'],.64)
        # Cross-check vertices of the actual top face with an independent USD transform.
        from pxr import Gf,Usd,UsdGeom
        stage=Usd.Stage.CreateInMemory();prim=UsdGeom.Xform.Define(stage,'/Part')
        prim.AddTranslateOp().Set(Gf.Vec3d(1,2,.62))
        prim.AddRotateZOp().Set(30);prim.AddRotateXYZOp().Set(Gf.Vec3f(0,90,0))
        matrix=prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        corners=[matrix.Transform(Gf.Vec3d(-.02,y,z)) for y,z in itertools.product((-.2,.2),(-.4,.4))]
        for corner in corners:
            self.assertAlmostEqual(corner[2],.64)
            self.assertTrue(any(math.dist(corner[:2],xy)<1e-6 for xy in face['world_corners_xy']))
        self.assertTrue(preview_scene_geometry(p)['objects'][1]['support_face_options'][0]['footprint_within_face'])
        obj.update(size=[1,1,1]);obj['parts'][0]['rotation_deg_xyz']=[12,34,56]
        self.assertEqual(preview_scene_geometry(p)['objects'][0]['box_top_faces'],[])

    def test_analytic_bounds_match_independent_usd_rotations(self):
        from pxr import Gf,Usd,UsdGeom
        for shape in ('box','cylinder','sphere'):
            p=part(shape,(.2,.4,.8),(23,41,67));p['offset']=[.1,-.2,.3]
            stage=Usd.Stage.CreateInMemory();prim=UsdGeom.Xform.Define(stage,'/Part')
            prim.AddTranslateOp().Set(Gf.Vec3d(*p['offset']))
            prim.AddRotateXYZOp().Set(Gf.Vec3f(*p['rotation_deg_xyz']))
            matrix=prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            if shape=='box':points=itertools.product((-.1,.1),(-.2,.2),(-.4,.4))
            elif shape=='cylinder':
                points=((.1*math.cos(t),.2*math.sin(t),z) for t in (i*math.tau/720 for i in range(720)) for z in (-.4,.4))
            else:
                points=((.1*math.cos(t)*math.cos(f),.2*math.sin(t)*math.cos(f),.4*math.sin(f))
                        for t in (i*math.tau/360 for i in range(360)) for f in (math.pi*(j/180-.5) for j in range(181)))
            world=[matrix.Transform(Gf.Vec3d(*v)) for v in points]
            low,high=part_bounds(p)
            for axis in range(3):
                self.assertAlmostEqual(low[axis],min(v[axis] for v in world),delta=3e-5)
                self.assertAlmostEqual(high[axis],max(v[axis] for v in world),delta=3e-5)

    def test_textured_rotation_preserves_uvs_normals_and_collision(self):
        from pxr import Gf,Usd,UsdGeom,UsdPhysics
        from primitive_geometry import define_textured_primitive
        stage=Usd.Stage.CreateInMemory()
        for shape in ('box','cylinder','sphere'):
            p=part(shape,(.2,.4,.8),(23,41,67));p['offset']=[.1,-.2,.3]
            old=define_textured_primitive(stage,'/old_'+shape,shape,p['size'],p['color'],[.2,.3])
            new=define_textured_primitive(stage,'/new_'+shape,shape,p['size'],p['color'],[.2,.3],p['offset'],p['rotation_deg_xyz'])
            for attr in ('points','normals','primvars:st','faceVertexIndices'):
                self.assertEqual(old.GetPrim().GetAttribute(attr).Get(),new.GetPrim().GetAttribute(attr).Get())
            self.assertTrue(new.GetPrim().HasAPI(UsdPhysics.CollisionAPI))
            self.assertEqual(UsdPhysics.MeshCollisionAPI(new).GetApproximationAttr().Get(),'convexHull')
            matrix=new.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            actual=[matrix.Transform(Gf.Vec3d(v)) for v in new.GetPointsAttr().Get()]
            low,high=part_bounds(p)
            for axis in range(3):
                self.assertAlmostEqual(min(v[axis] for v in actual),low[axis],delta=.001)
                self.assertAlmostEqual(max(v[axis] for v in actual),high[axis],delta=.001)


if __name__=='__main__':unittest.main()
