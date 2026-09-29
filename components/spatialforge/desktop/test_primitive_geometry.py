import math
import unittest

import numpy as np
from pxr import Usd, UsdGeom, UsdPhysics

from primitive_geometry import define_textured_primitive, primitive_mesh_with_uv


class CurvedTextures(unittest.TestCase):
    def test_closed_outward_geometry_bounds_and_smooth_normals(self):
        size = [1.4, .8, 1.2]
        for kind in ('sphere', 'cylinder'):
            with self.subTest(kind=kind):
                data = primitive_mesh_with_uv(kind, size, [.2, .3])
                p = np.asarray(data['points'])
                normals = np.asarray(data['normals'])
                np.testing.assert_allclose(p.max(axis=0)-p.min(axis=0), size)
                np.testing.assert_allclose(np.linalg.norm(normals,axis=1), 1.)
                self.assertEqual(len(data['st']), len(data['face_vertex_indices']))
                edges = {}
                offset = 0
                for count in data['face_vertex_counts']:
                    ids = data['face_vertex_indices'][offset:offset+count]
                    face = p[ids]
                    outward = np.cross(face[1]-face[0],face[2]-face[0])
                    self.assertGreater(np.dot(outward, face.mean(axis=0)), 1e-8)
                    self.assertTrue(np.all(normals[offset:offset+count] @ outward > 0))
                    for a,b in zip(ids,ids[1:]+ids[:1]):
                        edges[(a,b)] = edges.get((a,b),0)+1
                    offset += count
                self.assertTrue(all(n == 1 and edges.get((b,a)) == 1 for (a,b),n in edges.items()))

    def test_metric_uv_repeat_scale_seams_and_hard_caps(self):
        for kind in ('sphere','cylinder'):
            a = primitive_mesh_with_uv(kind,[1,1,2],[.25,.5])
            b = primitive_mesh_with_uv(kind,[1,1,2],[.5,1])
            self.assertEqual(a['points'],b['points'])
            np.testing.assert_allclose(np.array(a['st'])/2, b['st'])
            # U follows a full circle with one seam, not a jump across its last face.
            self.assertAlmostEqual(max(uv[0] for uv in a['st']), math.pi/.25, delta=.003)
            offset=0
            for n in a['face_vertex_counts']:
                us=[uv[0] for uv in a['st'][offset:offset+n]]
                if kind=='sphere' or n==4:
                    self.assertLess(max(us)-min(us),.14)
                offset+=n
        # First cylinder side, bottom cap, top cap. Cap normals are not averaged into the side.
        c=primitive_mesh_with_uv('cylinder',[1,1,2],[.25,.5])
        self.assertEqual(c['normals'][4:7],[(0,0,-1)]*3)
        self.assertEqual(c['normals'][7:10],[(0,0,1)]*3)
        self.assertEqual(max(uv[1] for uv in c['st'][:4]),4.)

    def test_usd_authors_face_uvs_smooth_normals_and_per_part_colliders(self):
        stage=Usd.Stage.CreateInMemory()
        for kind in ('box','cylinder','sphere'):
            mesh=define_textured_primitive(stage,'/'+kind,kind,[1,1,1],[1,1,1],[.2,.2],(.1,0,0))
            st=UsdGeom.PrimvarsAPI(mesh).GetPrimvar('st')
            self.assertEqual(st.GetInterpolation(),'faceVarying')
            self.assertEqual(len(st.Get()),len(mesh.GetFaceVertexIndicesAttr().Get()))
            self.assertEqual(mesh.GetNormalsInterpolation(),'uniform' if kind=='box' else 'faceVarying')
            self.assertEqual(UsdPhysics.MeshCollisionAPI(mesh).GetApproximationAttr().Get(),'convexHull')
            self.assertTrue(mesh.GetPrim().GetCustomDataByKey('spatialforge_uv_mapping'))


if __name__=='__main__':unittest.main()
