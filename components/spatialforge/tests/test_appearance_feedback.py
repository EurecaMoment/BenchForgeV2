import copy
import unittest
from spatialforge.contracts import validate_program,appearance_contract_errors,SCENE_SCHEMA_DESCRIPTION,scene_contract_capabilities
from test_contracts import sample


class AppearanceFeedbackTests(unittest.TestCase):
    def test_imported_texture_scalar_controls_are_discoverable_without_claiming_full_pbr(self):
        capability=scene_contract_capabilities()['appearance_controls']['imported_textured_mesh']
        self.assertEqual(capability['fields'],['roughness','metallic'])
        self.assertIn('metallic_roughness',capability['texture_slots'])
        self.assertIn('no texture or UV',capability['untextured_materials'])
        self.assertIn('appearance_overrides',capability['feedback'])
        self.assertIn('override the source scalar',SCENE_SCHEMA_DESCRIPTION)

    def test_unsupported_fields_locate_all_objects_without_modifying_scene(self):
        scene=sample()
        for index in range(3):
            obj=copy.deepcopy(scene['objects'][0]);obj.update(id=f'window_{index}',appearance={'roughness':0.1,'opacity':0.12})
            scene['objects'].append(obj)
        before=copy.deepcopy(scene)
        errors=appearance_contract_errors(scene)
        self.assertEqual(len(errors),3)
        with self.assertRaises(ValueError) as caught:validate_program(scene)
        message=str(caught.exception)
        for index in range(3):self.assertIn(f'window_{index}',message)
        self.assertIn('/appearance',message);self.assertIn('opacity',message);self.assertIn('allowed=',message)
        self.assertEqual(scene,before)
        self.assertIn('final scene snapshots after interactions',SCENE_SCHEMA_DESCRIPTION)

    def test_native_opacity_requires_registered_capability_after_material_merge(self):
        scene=sample();obj=scene['objects'][0]
        scene['schema']='spatialforge.scene/v2'
        scene['materials']=[{'id':'glass','name':'Native glass control','appearance':{'native_opacity_multiplier':.2}}]
        obj['material_id']='glass'
        with self.assertRaisesRegex(ValueError,'registered capable native asset'):validate_program(scene)
        obj['kind']='office_window';obj['size']=[.12,3,3]
        validate_program(scene)
        for invalid in (-.1,1.1,float('nan'),True):
            obj['appearance']={'native_opacity_multiplier':invalid}
            with self.subTest(value=invalid),self.assertRaises(ValueError):validate_program(scene)
        obj['appearance']={'native_opacity_multiplier':.3}
        validate_program(scene)
        obj['kind']='office_desk'
        with self.assertRaisesRegex(ValueError,'registered capable native asset'):validate_program(scene)


if __name__=='__main__':unittest.main()
