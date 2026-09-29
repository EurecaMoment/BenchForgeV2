"""Real file transport and transform regressions for authored shading normals."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import trimesh
from spatialforge.mesh_export import export_mesh
from spatialforge.mesh_geometry import transform_mesh_geometry, transform_mesh_normals


class MeshNormalsTests(unittest.TestCase):
    def test_obj_corner_normals_survive_instance_scale_and_y_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'corners.obj'
            # These are artist-authored directions, not inferred from geometry.
            source.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
                              'vn 0 0 1\nvn 0 -1 0\nf 1//1 2//1 3//1\nf 1//2 4//2 2//2\n')
            loaded=trimesh.load(source,force='scene',process=False)
            matrix=np.eye(4);matrix[:3,:3]=[[-2,.4,0],[0,3,0],[0,0,.5]]
            matrix[:3,3]=[8,4,2]
            name=next(iter(loaded.geometry))
            scene=trimesh.Scene()
            scene.add_geometry(loaded.geometry[name],transform=matrix)
            glb=root/'source.glb';glb.write_bytes(scene.export(file_type='glb',include_normals=True))
            actual_source=trimesh.load(glb,force='scene',process=False)
            node=actual_source.graph.nodes_geometry[0]
            transform,geom=actual_source.graph[node]
            original=actual_source.geometry[geom]
            normal=original.vertex_normals@np.linalg.inv(transform[:3,:3])
            normal/=np.linalg.norm(normal,axis=1,keepdims=True)
            face_order=np.fliplr(original.faces)  # mirrored node flips winding
            expected=normal[face_order].reshape((-1,3))[:,[0,2,1]]*[1,-1,1]
            record=export_mesh(glb,root/'mesh.json',source_frame='y_up')
            np.testing.assert_allclose(record['normals'],expected,atol=1e-6)
            self.assertEqual(record['normals_interpolation'],'faceVarying')
            self.assertEqual(record['normal_sources'][0]['origin'],'source_vertex_normals')

    def test_mixed_smooth_and_flat_source_keeps_each_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            sphere=trimesh.creation.icosphere(subdivisions=1)
            sphere.vertex_normals=sphere.vertices/np.linalg.norm(sphere.vertices,axis=1,keepdims=True)
            box=trimesh.creation.box();box.apply_translation([4,0,0])
            scene=trimesh.Scene();scene.add_geometry(sphere,node_name='smooth');scene.add_geometry(box,node_name='flat')
            source=root/'mixed.glb';source.write_bytes(scene.export(file_type='glb'))
            record=export_mesh(source,root/'mesh.json',source_frame='z_up')
            self.assertEqual({r['origin'] for r in record['normal_sources']},{'source_vertex_normals','geometric_face_normals'})
            normals=np.array(record['normals']).reshape((-1,3,3))
            points=np.array(record['vertices'])[record['faces']]
            flat=points.mean(axis=1)[:,0]>2
            self.assertTrue(np.allclose(normals[flat,0],normals[flat,1]))
            self.assertFalse(np.allclose(normals[~flat,0],normals[~flat,1]))
            self.assertEqual(len(record['normals']),len(record['faces'])*3)

    def test_absent_normals_keep_old_flat_policy_and_rotations_preserve_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'flat.ply'
            trimesh.creation.box().export(source)
            record=export_mesh(source,root/'mesh.json',source_frame='z_up')
            self.assertEqual(record['normals'],[])
        vertices=np.array([[-1,-2,-3],[1,2,3]])
        _,receipt=transform_mesh_geometry(vertices,[2,3,4],'sam3d_camera',{'orientation_deg_xyz':[35,20,80]})
        transform=np.array(receipt['T_local_from_source'])
        n=np.array([[1.,0,0]])
        actual=transform_mesh_normals(n,transform)
        tangent=np.array([0.,1,0])@transform[:3,:3].T
        self.assertAlmostEqual(float(actual[0]@tangent),0.)
        self.assertAlmostEqual(float(np.linalg.norm(actual)),1.)


if __name__=='__main__':unittest.main()
