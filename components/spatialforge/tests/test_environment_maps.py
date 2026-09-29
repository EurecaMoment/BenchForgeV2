import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from pxr import Usd, UsdLux, UsdGeom
except ImportError:
    Usd=UsdLux=UsdGeom=None
from spatialforge.contracts import validate_program
from spatialforge.environment_catalog import ENVIRONMENTS, apply_environment_texture
from test_contracts import sample


class EnvironmentMaps(unittest.TestCase):
    def test_registered_sky_accepts_explicit_direction(self):
        program=sample()
        light={'id':'sky','kind':'environment','position':[0,0,0],'environment_id':'clear_day_sky','intensity':2}
        program['lights']=[light]
        validate_program(program)
        with patch.dict(light,{'direction':[.85,.3,-.4]}):validate_program(program)
        for change in ({'kind':'area'},{'environment_id':'../secret'},{'direction':[0,0,0]}):
            with patch.dict(light,change):
                with self.assertRaises(ValueError):validate_program(program)

    @unittest.skipIf(Usd is None,'USD Python is only available on the desktop environment')
    def test_usd_texture_and_stage_axis_are_authored_with_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/ENVIRONMENTS['clear_day_sky']['path']
            path.parent.mkdir(parents=True)
            path.write_bytes(b'fixture-only; no rendering claim')
            stage=Usd.Stage.CreateInMemory()
            UsdGeom.SetStageUpAxis(stage,'Z')
            light=UsdLux.DomeLight.Define(stage,'/Sky')
            evidence=apply_environment_texture(light,'clear_day_sky',tmp)
            self.assertEqual(light.GetTextureFileAttr().Get().path,path.as_posix())
            self.assertEqual(light.GetTextureFormatAttr().Get(),'latlong')
            self.assertEqual(light.GetPrim().GetAttribute('xformOp:rotateX:orientToStageUpAxis').Get(),90)
            self.assertEqual(evidence['environment_id'],'clear_day_sky')
            path.unlink()
            with self.assertRaises(ValueError):apply_environment_texture(light,'clear_day_sky',tmp)

    @unittest.skipIf(Usd is None,'USD Python is only available on the desktop environment')
    def test_direction_rotates_hdr_poles_after_stage_axis_conversion(self):
        from pxr import Gf
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/ENVIRONMENTS['clear_day_sky']['path']
            path.parent.mkdir(parents=True);path.write_bytes(b'fixture')
            for up in ('Y','Z'):
                stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageUpAxis(stage,up)
                light=UsdLux.DomeLight.Define(stage,'/Sky')
                direction=Gf.Vec3d(.85,.3,-.4).GetNormalized()
                receipt=apply_environment_texture(light,'clear_day_sky',tmp,list(direction))
                matrix=UsdGeom.Xformable(light).GetLocalTransformation()
                actual=matrix.TransformDir(Gf.Vec3d(0,-1,0)).GetNormalized()
                self.assertLess((actual-direction).GetLength(),1e-6)
                self.assertEqual(receipt['orientation'],'explicit_world_nadir')


if __name__=='__main__':unittest.main()
