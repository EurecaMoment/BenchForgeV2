import copy,unittest
from spatialforge.contracts import validate_program
from scene_runtime import material_for,part_material_for
from test_contracts import sample

class PartMaterials(unittest.TestCase):
    def make_program(self):
        p=sample()
        p['materials']=[{'id':'steel','name':'Steel','base_color':[.6,.6,.6],'metallic':1,'roughness':.2}]
        obj=p['objects'][0]
        obj.update(kind='composite',appearance={'texture_id':'bamboo_desktop','uv_scale_m':[.4,.4]},
            parts=[{'shape':'box','size':[1,1,.1],'offset':[0,0,0],'color':[.2,.3,.4]}])
        return p

    def test_legacy_inheritance_and_local_override_preserve_inputs(self):
        p=self.make_program();obj=p['objects'][0];part=obj['parts'][0]
        part['appearance']={'roughness':.15,'texture_tint':[.8,.6,.4]}
        before=copy.deepcopy(p);validate_program(p)
        actual=part_material_for(p,material_for(p,obj),part)
        self.assertEqual(actual['appearance'],{**obj['appearance'],**part['appearance']})
        self.assertEqual(actual['color'],part['color']);self.assertEqual(p,before)

    def test_explicit_metal_material_does_not_inherit_parent_wood(self):
        p=self.make_program();obj=p['objects'][0];part=obj['parts'][0]
        part.update(material_id='steel',appearance={'roughness':.08})
        for schema in ['spatialforge.scene/v1','spatialforge.scene/v2']:
            p['schema']=schema;validate_program(p)
        actual=part_material_for(p,material_for(p,obj),part)
        self.assertEqual(actual['appearance'],{'roughness':.08,'metallic':1})
        self.assertEqual(actual['color'],[.6,.6,.6])

    def test_unknown_part_material_reports_its_object_and_index(self):
        p=self.make_program();p['objects'][0]['parts'][0]['material_id']='absent'
        with self.assertRaisesRegex(ValueError,r'unknown_object.parts\[0\].*material_id'):
            validate_program(p)
