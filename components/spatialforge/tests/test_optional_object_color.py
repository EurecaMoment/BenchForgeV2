import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from scene_runtime import material_for
from spatialforge.contracts import validate_program


class OptionalObjectColorTests(unittest.TestCase):
    def test_asset_material_and_default_keep_existing_resolution(self):
        p={'schema':'spatialforge.scene/v2','scene_id':'optional_color','title':'Color resolution',
           'objects':[], 'cameras':[{'position':[3,3,3],'target':[0,0,0]}], 'assumptions':[],
           'materials':[{'id':'blue','name':'Blue paint','base_color':[.1,.2,.8]}]}
        for index,extra in enumerate(({'kind':'mesh','asset_id':'asset_fixture'},
                                      {'kind':'box','material_id':'blue'}, {'kind':'box'},
                                      {'kind':'box','color':[.8,.2,.1]})):
            p['objects'].append({'id':f'item_{index}','label':f'item {index}','size':[1,1,1],
                                 'xy':[index*2,0],'support':'ground','base_z':0,'dynamic':False,
                                 'mass_kg':0,**extra})
        original=copy.deepcopy(p)
        self.assertEqual(validate_program(p),original)
        self.assertEqual(p,original)
        self.assertNotIn('color',p['objects'][0])
        self.assertEqual(material_for(p,p['objects'][1])['color'],[.1,.2,.8])
        self.assertEqual(material_for(p,p['objects'][2])['color'],[.7,.7,.7])
        self.assertEqual(material_for(p,p['objects'][3])['color'],[.8,.2,.1])

    def test_explicit_invalid_color_remains_an_error(self):
        p={'schema':'spatialforge.scene/v1','scene_id':'invalid_color','title':'Explicit color',
           'objects':[{'id':'item','label':'item','kind':'box','size':[1,1,1],'color':[2,0,0],
                       'xy':[0,0],'support':'ground','base_z':0,'dynamic':False,'mass_kg':0}],
           'cameras':[{'position':[3,3,3],'target':[0,0,0]}], 'assumptions':[]}
        with self.assertRaisesRegex(ValueError,'color'):
            validate_program(p)


if __name__=='__main__':unittest.main()
