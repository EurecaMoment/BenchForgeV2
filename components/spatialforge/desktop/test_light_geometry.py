import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from spatialforge.contracts import validate_program
from pxr import Usd,UsdLux
from scene_runtime import light_specs
from light_geometry import apply_light_geometry


class LightGeometryTests(unittest.TestCase):
    def test_scene_sun_and_directional_angles_reach_usd_and_receipts(self):
        stage=Usd.Stage.CreateInMemory()
        for kind in ('sun','directional'):
            for angle in (None,0,.53,12):
                light_spec={'id':'Emitter','kind':kind,'intensity':800}
                if angle is not None:light_spec['angle']=angle
                program={'schema':'spatialforge.scene/v2','scene_id':'AngleTest','title':'Light angle test','assumptions':[],
                    'objects':[{'id':'floor','kind':'box','label':'floor','size':[4,4,.1],'xy':[0,0],
                                'base_z':0,'yaw_deg':0,'color':[.5,.5,.5],'dynamic':False,'mass_kg':0,'support':'ground'}],
                    'lights':[light_spec],'cameras':[{'id':'View','position':[1,-3,2],'target':[0,0,0]}]}
                normalized=light_specs(validate_program(program))[0]
                light=UsdLux.DistantLight.Define(stage,'/Emitter');light.CreateIntensityAttr(800)
                receipt=apply_light_geometry(light,normalized)
                self.assertAlmostEqual(receipt['angle_degrees'],.53 if angle is None else angle)
                self.assertEqual(receipt['intensity'],800)

    def test_unsized_point_and_spot_are_not_one_meter_emitters(self):
        stage=Usd.Stage.CreateInMemory()
        for kind in ('point','spot'):
            spec=light_specs({'lights':[{'id':kind,'kind':kind,'position':[0,0,1],'intensity':80}]})[0]
            light=UsdLux.SphereLight.Define(stage,'/'+kind);light.CreateIntensityAttr(80)
            self.assertEqual(light.GetRadiusAttr().Get(),.5)
            receipt=apply_light_geometry(light,spec)
            self.assertEqual(light.GetRadiusAttr().Get(),0)
            self.assertTrue(light.GetTreatAsPointAttr().Get())
            self.assertEqual(receipt['intensity'],80)

    def test_explicit_sphere_and_area_dimensions_are_preserved(self):
        stage=Usd.Stage.CreateInMemory()
        light=UsdLux.SphereLight.Define(stage,'/sphere');light.CreateIntensityAttr(70)
        receipt=apply_light_geometry(light,{'id':'sphere','kind':'sphere','size':[.2,.2]})
        self.assertAlmostEqual(receipt['radius_m'],.1)
        self.assertFalse(receipt['treat_as_point'])
        area=UsdLux.RectLight.Define(stage,'/area');area.CreateIntensityAttr(600)
        receipt=apply_light_geometry(area,{'id':'area','kind':'rect','size':[2,3]})
        self.assertEqual([receipt['width_m'],receipt['height_m']],[2,3])


if __name__=='__main__':unittest.main()
