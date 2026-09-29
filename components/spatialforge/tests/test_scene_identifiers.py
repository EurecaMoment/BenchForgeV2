import copy
import unittest
from pxr import Sdf
from spatialforge.contracts import ident, validate_program
from test_contracts import sample


class SceneIdentifiers(unittest.TestCase):
    def test_usd_identifiers_keep_case_length_and_references(self):
        scene=sample();scene['scene_id']='LeatherStudio'
        obj=scene['objects'][0];obj['id']='sewing_machine_altB'
        second=copy.deepcopy(obj);second.update(id='_ToolRackWithDescriptiveName_'+('A'*65),support=obj['id'])
        scene['objects'].append(second)
        scene['cameras'][0]['id']='DetailCameraB'
        before=copy.deepcopy(scene)
        self.assertEqual(validate_program(scene),before)
        for value in (scene['scene_id'],obj['id'],second['id'],scene['cameras'][0]['id']):
            self.assertTrue(Sdf.Path.IsValidIdentifier(value))
            self.assertEqual(ident(value),value)

    def test_ids_still_identify_one_usd_prim(self):
        for value in ('../escape','a/b','a.b','1object','a-b','',None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'invalid ID'):
                ident(value)
