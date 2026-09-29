import copy
import unittest

from spatialforge.contracts import validate_program
from spatialforge.geometry_preview import preview_scene_geometry


def scene():
    return {'schema':'spatialforge.scene/v1','scene_id':'room','title':'Room scale layout',
            'objects':[{'id':'floor','label':'floor','kind':'box','size':[14,14,.1],
                        'color':[.4,.4,.4],'xy':[0,-3],'support':'ground','base_z':-.1,
                        'yaw_deg':0,'dynamic':False,'mass_kg':0}],
            'cameras':[{'id':'overview','position':[0,-11.5,2.6],'target':[0,-3,.35]}],
            'assumptions':[]}


class SchemaParity(unittest.TestCase):
    def test_room_coordinates_and_floor_are_preserved_in_both_schemas(self):
        for version in ('v1','v2'):
            p=scene();p['schema']='spatialforge.scene/'+version
            prop=copy.deepcopy(p['objects'][0])
            prop.update(id='prop',size=[.005,.008,.005],xy=[6,-8],base_z=4.1,mass_kg=250,yaw_deg=450)
            p['objects'].append(prop)
            composite=copy.deepcopy(prop)
            composite.update(id='counter',kind='composite',size=[12,2,2],xy=[0,0],base_z=0,
                parts=[{'shape':'box','size':[5,.1,.1],'offset':[3,0,0],'color':[.4,.4,.4]}])
            p['objects'].append(composite)
            before=copy.deepcopy(p)
            with self.subTest(version=version):
                self.assertEqual(validate_program(p),before)
                self.assertEqual(p,before)

    def test_execution_budget_does_not_depend_on_schema_version(self):
        for version in ('v1','v2'):
            p=scene();p['schema']='spatialforge.scene/'+version
            p['objects']=[{**p['objects'][0],'id':f'obj{i}'} for i in range(101)]
            p['cameras']=[{**p['cameras'][0],'id':f'cam{i}'} for i in range(17)]
            with self.subTest(version=version):validate_program(p)

    def test_invalid_geometry_names_the_object_or_camera_field(self):
        for field,value in (('size',[0,1,1]),('xy',[float('nan'),0]),('base_z',float('inf'))):
            p=scene();p['objects'][0][field]=value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'object floor.'+field):validate_program(p)
        p=scene();p['cameras'][0]['position']=[0,2000,1]
        with self.assertRaisesRegex(ValueError,r'camera overview.position.*\[-1000, 1000\]'):
            validate_program(p)

    def test_lower_shelf_advice_matches_both_schema_contracts(self):
        p=scene()
        p['objects']=[{**p['objects'][0],'id':'shelf','kind':'composite','size':[2,1,2],'base_z':0,
            'parts':[{'shape':'box','size':[2,1,.1],'offset':[0,0,z],'color':[.4,.4,.4]} for z in (-.95,.95)]},
            {**p['objects'][0],'id':'prop','size':[.2,.2,.2],'support':'shelf','base_z':-1.9}]
        for version in ('v1','v2'):
            p['schema']='spatialforge.scene/'+version
            with self.subTest(version=version):
                validate_program(p)
                options=preview_scene_geometry(p)['objects'][1]['support_face_options']
                lower=min(options,key=lambda f:f['top_z_m'])
                self.assertAlmostEqual(lower['base_z_for_contact'],-1.9)
                self.assertTrue(lower['base_z_allowed_by_schema'])
                self.assertTrue(lower['geometry_base_z_allowed_by_schema'])


if __name__=='__main__':unittest.main()
