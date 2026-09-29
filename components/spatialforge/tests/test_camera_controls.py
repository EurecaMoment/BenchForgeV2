import copy
from pathlib import Path
import sys
import unittest

import numpy as np
from pxr import Usd, UsdGeom

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from camera_controls import camera_matrix, apply_camera_optics, camera_evidence
from spatialforge.contracts import validate_program
from test_contracts import sample


class CameraControlsTests(unittest.TestCase):
    def test_authored_optics_roll_and_default_reset(self):
        stage=Usd.Stage.CreateInMemory();camera=UsdGeom.Camera.Define(stage,'/Camera')
        base={'position':[0,0,1.5],'target':[0,1,1.5]}
        roll={**base,'up':[1,0,0],'focal_length_mm':32,'horizontal_aperture_mm':27}
        p=sample();p['cameras']=[base,roll];before=copy.deepcopy(p)
        self.assertEqual(validate_program(p),before)
        for spec,focal,aperture in [(roll,32,27),(base,24,36)]:
            apply_camera_optics(camera,spec)
            receipt=camera_evidence(camera,spec,camera_matrix(spec))
            self.assertEqual(receipt['focal_length_mm'],focal)
            self.assertEqual(receipt['horizontal_aperture_mm'],aperture)
        m=np.asarray(camera_matrix(roll))
        np.testing.assert_allclose(m[1,:3],[1,0,0],atol=1e-12)
        np.testing.assert_allclose(-m[2,:3],[0,1,0],atol=1e-12)

    def test_invalid_projection_and_parallel_up_fail_at_submission(self):
        for fields in ({'focal_length_mm':0},{'horizontal_aperture_mm':float('nan')},
                       {'up':[0,0,0]},{'up':[0,2,0]}):
            p=sample();p['cameras']=[{'position':[0,0,1],'target':[0,1,1],**fields}]
            with self.assertRaisesRegex(ValueError,'camera'):
                validate_program(p)


if __name__=='__main__':unittest.main()
