import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatialforge.generation import GenerationTools
from spatialforge.geometry_preview import mesh_fit_preview, preview_scene_geometry


class CameraMetadataTests(unittest.TestCase):
    def test_registration_catalog_and_preview_retain_source_convention_without_pose_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tools=GenerationTools(root)
            source=root/'item.glb';source.write_bytes(b'conversion fixture')
            conversion=root/'mesh_data.json'
            mesh={'vertices':[[0,0,0],[1,1,1]],'faces':[[0,1,1]],'colors':[[1,1,1]]*2,
                  'bounds':[[0,0,0],[1,1,1]],'coordinate_frame':'sam3d_camera','watertight':False,
                  'appearance':{'encoding':'vertex_color'},'materials':[]}
            conversion.write_text(json.dumps(mesh))
            convention='opencv_right_down_forward_v1'
            camera={'intrinsics_normalized':[[.8,0,.5],[0,1.2,.5],[0,0,1]],'image_size':[1200,800],
                    'authority':'predicted, not GT','gt_source':False}
            manifest=source.with_suffix('.complete.json')
            manifest.write_text(json.dumps({'asset':{'camera_coordinates':convention}}))
            for declared,frame in ((True,'sam3d_camera'),(False,'sam3d_camera'),(True,'z_up')):
                if declared:manifest.write_text(json.dumps({'asset':{'camera_coordinates':convention,'source_camera':camera}}))
                elif manifest.exists():manifest.unlink()
                work=root/f'case_{declared}_{frame}';work.mkdir()
                with patch.object(tools,'_convert',return_value=(conversion,source)):
                    result=tools._publish({'label':'fixture'},work,source,frame,{'tools':['mesh_import']},'imported')
                asset_id=result['asset_id']
                registered=json.loads((tools.assets/asset_id/'mesh.json').read_text())
                self.assertEqual(registered['vertices'],mesh['vertices'])
                geometry=tools.catalog({asset_id})[0]['geometry']
                fit=mesh_fit_preview(registered,[1,1,1])
                obj={'id':'item','kind':'mesh','asset_id':asset_id,'size':[1,1,1],
                     'xy':[0,0],'base_z':0,'support':'ground','dynamic':False}
                full=preview_scene_geometry({'scene_id':'fixture','objects':[obj]},tools.assets)['objects'][0]['mesh_fit']
                for record in (registered,result['geometry'],geometry,fit,full):
                    if declared and frame=='sam3d_camera':
                        self.assertEqual(record['camera_coordinates'],convention)
                        self.assertEqual(record['source_camera'],camera)
                    else:
                        self.assertNotIn('camera_coordinates',record)
                        self.assertNotIn('source_camera',record)
                self.assertEqual(fit['orientation_deg_xyz'],[0,0,0])


if __name__=='__main__':unittest.main()
