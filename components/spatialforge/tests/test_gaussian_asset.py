import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh
from pxr import Usd, UsdGeom, UsdPhysics

from spatialforge.gaussian_asset import register_gaussian, render_representation
from spatialforge.mesh_export import export_mesh
from spatialforge.mesh_geometry import transform_mesh_geometry


class GaussianAssetTests(unittest.TestCase):
    def test_source_pose_y_up_and_scene_normalization_keep_mesh_and_splats_aligned(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'desktop'))
        from gaussian_visual import define_gaussian_visual
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            local=trimesh.creation.box(extents=[.2,.4,.8])
            pose=trimesh.transformations.rotation_matrix(.65,[1,2,3])
            pose[:3,:3]*=1.7;pose[:3,3]=[.3,-.4,2.2]
            source=local.copy();source.apply_transform(pose);source.export(root/'source.glb')
            mesh=export_mesh(root/'source.glb',root/'mesh.json',source_frame='y_up')
            count=len(local.vertices)
            np.savez(root/'source.npz',positions=local.vertices.astype('float32'),
                     scales=np.ones((count,3),dtype='float32')*.01,
                     orientations=np.tile([1,0,0,0],(count,1)).astype('float32'),
                     opacities=np.ones((count,1),dtype='float32')*.8,
                     features=np.arange(count*3,dtype='float32').reshape(count,1,3)/100,
                     local_to_source=pose)
            record=register_gaussian(root/'source.npz',root/'gaussian.npz','y_up')
            points,norm=transform_mesh_geometry(mesh['vertices'],[1.2,.8,1.6],'z_up',{'orientation_deg_xyz':[17,32,-40]})
            stage=Usd.Stage.CreateInMemory();UsdGeom.Xform.Define(stage,'/Object')
            receipt=define_gaussian_visual(stage,'/Object',root/'gaussian.npz',record,norm)
            prim=stage.GetPrimAtPath(receipt['prim_path'])
            transform=np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim)).T
            splats=np.asarray(prim.GetAttribute('positions').Get())
            result=splats@transform[:3,:3].T+transform[:3,3]
            np.testing.assert_allclose(result,points,atol=2e-7)
            self.assertFalse(prim.HasAPI(UsdPhysics.CollisionAPI))
            with np.load(root/'source.npz') as raw:
                np.testing.assert_array_equal(prim.GetAttribute('scales').Get(),raw['scales'])
                np.testing.assert_array_equal(prim.GetAttribute('radiance:sphericalHarmonicsCoefficients').Get(),raw['features'][:,0,:])

    def test_hybrid_default_and_explicit_mesh_choice(self):
        self.assertEqual(render_representation({}, {'gaussian':{'file':'gaussian.npz'}}),'gaussian')
        self.assertEqual(render_representation({}, {}),'mesh')
        self.assertEqual(render_representation({'render_representation':'mesh'}, {'gaussian':{'file':'gaussian.npz'}}),'mesh')
        with self.assertRaisesRegex(ValueError,'no Gaussian payload'):
            render_representation({'render_representation':'gaussian'}, {})


if __name__=='__main__':unittest.main()
