import unittest
import numpy as np
import trimesh
from spatialforge.sam3d_texture_worker import opencv_camera_output
from spatialforge.mesh_geometry import transform_mesh_geometry


class CameraCoordinates(unittest.TestCase):
    def test_official_camera_axes_survive_world_conversion_and_keep_pair_aligned(self):
        # Official PyTorch3D camera: positive X is image-left, Y is image-up.
        points=np.array([[0.,0.,2.],[.4,0.,2.],[0.,.8,2.],[0.,0.,2.3]])
        mesh=trimesh.Trimesh(vertices=points,faces=[[0,1,2],[0,2,3]],process=False)
        mesh.visual.vertex_colors=np.array([[255,0,0,255],[0,255,0,255],[0,0,255,255],[255,255,0,255]])
        pose=np.eye(4);pose[:3,3]=[.2,-.3,1.]
        local=(points-pose[:3,3])
        converted,paired_pose=opencv_camera_output(mesh,pose)
        paired=(np.c_[local,np.ones(len(local))]@paired_pose.T)[:,:3]
        np.testing.assert_allclose(converted.vertices,paired)
        np.testing.assert_array_equal(converted.faces,mesh.faces)
        np.testing.assert_array_equal(converted.visual.vertex_colors,mesh.visual.vertex_colors)
        world,receipt=transform_mesh_geometry(converted.vertices,[2,2,2],'sam3d_camera')
        self.assertGreater(world[2,2],world[0,2],'image up must remain world up')
        self.assertLess(world[1,0],world[0,0],'image left must remain world left')
        self.assertGreater(world[3,1],world[0,1],'camera forward must enter the scene')
        self.assertGreater(np.linalg.det(paired_pose[:3,:3]),0,'proper rotation, not a reflection')
        np.testing.assert_array_equal(mesh.vertices,points)
        np.testing.assert_array_equal(pose[:3,3],[.2,-.3,1.])


if __name__=='__main__':unittest.main()
