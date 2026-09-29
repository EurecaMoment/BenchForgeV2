import unittest
from test_contracts import sample
from spatialforge.contracts import validate_program


class InteractionCameraContract(unittest.TestCase):
    def test_optional_camera_names_an_existing_authored_view(self):
        program=sample()
        program['objects'][0]['dynamic']=True
        program['cameras'][0]['id']='action_view'
        program['interactions']=[{'id':'push','action':'apply_force','object_id':'unknown_object',
                                  'force_newtons':[1,0,0],'camera_id':'action_view'}]
        self.assertEqual(validate_program(program),program)
        program['interactions'][0]['camera_id']='missing'
        with self.assertRaisesRegex(ValueError,'camera_id'):validate_program(program)
        program['interactions'][0].pop('camera_id')
        self.assertEqual(validate_program(program),program)
