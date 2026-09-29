import copy
import unittest
import numpy as np
from scene_runtime import select_interaction_camera
from capture_images import object_visibility


class InteractionCameraTests(unittest.TestCase):
    def test_action_uses_target_view_and_preserves_explicit_choice(self):
        cameras=[{'id':'room','position':[0,-2,1],'target':[0,2,1]},
                 {'id':'tool','position':[0,-2,1],'target':[-3,0,1]}]
        original=copy.deepcopy(cameras)
        self.assertEqual(select_interaction_camera(cameras,{},[-3,0,1])['id'],'tool')
        self.assertEqual(select_interaction_camera(cameras,{'camera_id':'room'},[-3,0,1])['id'],'room')
        self.assertEqual(cameras,original)
        cameras[0].pop('id')
        self.assertEqual(select_interaction_camera(cameras,{'camera_id':'tool'},[-3,0,1])['id'],'tool')

    def test_visibility_uses_instance_path_and_reports_absence(self):
        masks=np.array([[0,3,3],[2,3,0]],dtype=np.uint32)
        labels={'0':'BACKGROUND','2':'/World/Objects/shelf','3':'/World/Objects/toolbox'}
        for data in (masks,masks.view(np.uint8).reshape(2,3,4)):
            instance={'data':data,'info':{'idToLabels':labels}}
            self.assertEqual(object_visibility(instance,'toolbox','/World/Objects/toolbox',(2,3)),
                             {'object_id':'toolbox','visible_pixels':3,'bbox_xyxy':[1,0,3,2]})
            self.assertEqual(object_visibility(instance,'bin','/World/Objects/bin',(2,3))['visible_pixels'],0)


if __name__=='__main__':unittest.main()
