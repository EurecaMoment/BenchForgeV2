from copy import deepcopy
import unittest
from spatialforge.contracts import validate_program
from test_contracts import sample


class TextureTintContract(unittest.TestCase):
    def test_named_tint_and_negative_asset_feedback_survive_validation(self):
        p=sample();p['schema']='spatialforge.scene/v2'
        p['materials']=[{'id':'wood','name':'Stained wood','appearance':{'texture_id':'wood_laminate','texture_tint':[.4,.25,.12]}}]
        p['objects'][0].update(material_id='wood',appearance={'texture_tint':[.5,.3,.15]},
            asset_quality={'semantic_review':'needs_improvement','repair_prompt':'Inspect source mask','3d_validated':False})
        before=deepcopy(p);validate_program(p)
        self.assertEqual(p,before)
        del p['materials'][0]['appearance']['texture_id']
        with self.assertRaisesRegex(ValueError,'texture_tint needs'):validate_program(p)

    def test_tint_values_use_existing_rgb_contract(self):
        p=sample();p['schema']='spatialforge.scene/v2'
        for value in ([1,1,1],[0,.25,1]):
            p['objects'][0]['appearance']={'texture_id':'wood_laminate','texture_tint':value};validate_program(p)
        for value in ([1,1],[1,-.1,1],[1,1,float('nan')]):
            p['objects'][0]['appearance']['texture_tint']=value
            with self.assertRaises(ValueError):validate_program(p)

if __name__=='__main__':unittest.main()
