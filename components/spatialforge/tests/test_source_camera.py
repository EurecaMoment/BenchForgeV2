import unittest
import numpy as np
import torch
from spatialforge.source_camera import record_source_camera, source_camera_metadata


class SourceCameraTests(unittest.TestCase):
    def test_normalized_camera_matches_pixel_projection(self):
        k=[[.8,0,.5],[0,1.2,.5],[0,0,1]]
        record=source_camera_metadata(k,[1200,800])
        point=np.array([.2,.1,2])
        uv=np.asarray(record['intrinsics_pixels'])@point;uv=uv[:2]/uv[2]
        np.testing.assert_allclose(uv,[696,448],atol=1e-12)
        self.assertAlmostEqual(record['horizontal_fov_deg'],64.010766416,places=7)
        self.assertFalse(record['gt_source'])

    def test_recorder_keeps_output_identity_and_clears_missing_metadata(self):
        image=torch.zeros(3,40,60)
        result={'intrinsics':torch.tensor([[.8,0,.5],[0,1.2,.5],[0,0,1]]),
                'points':torch.randn(40,60,3)}
        points=result['points'].clone();calls=[];record={}
        def model(value):
            calls.append(value)
            return result
        observed=record_source_camera(model,record)
        self.assertIs(observed(image),result)
        self.assertIs(calls[0],image)
        self.assertEqual(len(calls),1)
        self.assertEqual(record['image_size'],[60,40])
        self.assertTrue(torch.equal(points,result['points']))
        del result['intrinsics']
        self.assertIs(observed(image),result)
        self.assertEqual(record,{})


if __name__=='__main__':unittest.main()
