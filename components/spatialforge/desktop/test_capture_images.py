import unittest
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from capture_images import read_rgb_bounded, instance_region, object_visibility


class CaptureReadinessTests(unittest.TestCase):
    def test_instance_paths_keep_case_and_include_only_actual_descendants(self):
        instance={'data':np.array([[2,2,3,3],[4,4,5,0]],dtype=np.uint32),
                  'info':{'idToLabels':{'0':'BACKGROUND','2':'/World/Objects/Cup','3':'/World/Objects/cup',
                                        '4':'/World/Objects/Cup/Geometry','5':'/World/Objects/CupExtra'}}}
        upper=object_visibility(instance,'Cup','/World/Objects/Cup',(2,4))
        lower=object_visibility(instance,'cup','/World/Objects/cup',(2,4))
        self.assertEqual(upper['visible_pixels'],4);self.assertEqual(upper['bbox_xyxy'],[0,0,2,2])
        self.assertEqual(lower['visible_pixels'],2);self.assertEqual(lower['bbox_xyxy'],[2,0,4,1])
        packed={**instance,'data':instance['data'].view(np.uint8)}
        np.testing.assert_array_equal(instance_region(instance,'/World/Objects/Cup',(2,4)),instance_region(packed,'/World/Objects/Cup',(2,4)))

    def run_capture(self,frames):
        pending=iter(frames);steps=[];rejected=[]
        rgb,receipt=read_rgb_bounded(lambda:next(pending),lambda:steps.append(1),(4,6),lambda *args:rejected.append(args))
        return rgb,receipt,steps,rejected

    def test_blank_first_buffer_recovers_at_same_camera_with_bounded_render_steps(self):
        good=np.full((4,6,4),100,dtype=np.uint8)
        rgb,r,steps,rejected=self.run_capture([np.zeros_like(good),good])
        self.assertTrue(r['valid_rgb']);self.assertEqual(len(r['attempts']),2)
        self.assertEqual(len(steps),10);self.assertEqual(len(rejected),1)
        self.assertEqual(rgb.shape,(4,6,3));self.assertFalse(r['simulation_advanced'])
        self.assertEqual(r['attempts'][0]['reason'],'all_zero_rgb')

    def test_persistent_black_stops_without_claiming_recovery(self):
        rgb,r,steps,rejected=self.run_capture([np.zeros((4,6,3))]*3)
        self.assertFalse(r['valid_rgb']);self.assertEqual(len(steps),15)
        self.assertEqual(len(rejected),1);self.assertEqual(rgb.max(),0)

    def test_empty_host_buffer_is_retained_as_diagnostic_and_retried(self):
        rgb,r,steps,rejected=self.run_capture([np.array([]),np.full((4,6,3),80)])
        self.assertTrue(r['valid_rgb']);self.assertIsNone(rejected[0][0])
        self.assertEqual(r['attempts'][0]['reason'],'invalid_rgb_shape')

    def test_reinitialization_runs_once_only_after_recording_first_failure(self):
        events=[]
        rgb,r=read_rgb_bounded(lambda:np.zeros((4,6,3)),lambda:None,(4,6),
            lambda *args:events.append('retained'),reinitialize=lambda:events.append('reinitialize'))
        self.assertEqual(events,['retained','reinitialize'])
        self.assertTrue(r['render_reinitialized']);self.assertFalse(r['valid_rgb'])
        self.assertFalse(r['final_camera_changed'])

    def test_warm_product_samples_fresh_pixels_with_one_render(self):
        pixels=np.zeros((4,6,3),dtype=np.uint8);steps=[]
        def render():
            steps.append(1);pixels[:]=len(steps)*40
        for expected in [40,80]:
            rgb,receipt=read_rgb_bounded(lambda:pixels,render,(4,6),lambda *args:None,render_steps=1)
            self.assertEqual(int(rgb[0,0,0]),expected)
            self.assertEqual(receipt['render_steps_per_attempt'],1)
        self.assertEqual(len(steps),2)


if __name__=='__main__':unittest.main()
