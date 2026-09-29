import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
import trimesh
from spatialforge.sam3d_texture_worker import camera_mesh_from_baked
from spatialforge import generation_stage
from spatialforge.mesh_export import export_mesh


class TextureBakingTests(unittest.TestCase):
    def test_baked_y_up_mesh_recovers_camera_pose_and_uv_material(self):
        local=trimesh.creation.box(extents=[.2,.4,.6])
        local.visual=trimesh.visual.TextureVisuals(uv=np.arange(len(local.vertices)*2).reshape(-1,2)/20,
            material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB',(16,16),(180,90,30))))
        z_to_y=np.eye(4);z_to_y[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
        baked=local.copy();baked.apply_transform(z_to_y)
        pose=trimesh.transformations.rotation_matrix(.7,[1,2,3]);pose[:3,:3]*=1.7;pose[:3,3]=[.3,-.4,2]
        result=camera_mesh_from_baked(baked,pose)
        expected=local.copy();expected.apply_transform(pose)
        np.testing.assert_allclose(result.vertices,expected.vertices,atol=1e-8)
        np.testing.assert_array_equal(result.faces,local.faces)
        np.testing.assert_array_equal(result.visual.uv,local.visual.uv)
        self.assertEqual(result.visual.material.baseColorTexture.tobytes(),local.visual.material.baseColorTexture.tobytes())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result.export(root/'baked.glb')
            record=export_mesh(root/'baked.glb',root/'mesh.json',source_frame='sam3d_camera')
            self.assertEqual(record['coordinate_frame'],'sam3d_camera')
            self.assertTrue(record['texcoords']);self.assertTrue(record['materials'][0]['textures'])
            np.testing.assert_allclose(record['bounds'],expected.bounds,atol=1e-6)

    def test_explicit_baking_reaches_worker_and_default_request_stays_legacy(self):
        class StopAtWorker(Exception):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);Image.new('RGB',(16,16)).save(root/'image.png');Image.new('L',(16,16),255).save(root/'mask.png')
            class Tools:
                config=SimpleNamespace(model=lambda name:{'path':str(root/'model')},data={'sources':{'sam3d':str(root/'source')}})
                def __init__(self,*args):pass
                def source_path(self,p):return Path(p)
                def execute(self,name,request,*args):
                    requests.append(request);raise StopAtWorker()
            class Store:
                def __init__(self):self.root=root
                def directory(self,*args):return root
            requests=[]
            for option in (None,False,True):
                spec={'source_image':str(root/'image.png'),'objects':[{'object_id':'instrument','source_mask':str(root/'mask.png'),'seed':13}]}
                if option is not None:spec['texture_baking']=option
                task={'id':'test','unit':{'revision':0,'intent':{'tool':'sam3d','parameters':spec}}}
                with patch.object(generation_stage,'GenerationTools',Tools),self.assertRaises(StopAtWorker):
                    generation_stage.execute_generation_stage(Store(),task,threading.Event())
            self.assertEqual(requests[0],requests[1]);self.assertNotIn('texture_baking',requests[0])
            self.assertTrue(requests[2].pop('texture_baking'));self.assertEqual(requests[0],requests[2])


if __name__=='__main__':unittest.main()
