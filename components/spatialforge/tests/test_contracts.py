import copy
import unittest
from spatialforge.contracts import validate_program, merge_scene_extension,normalize_native_asset_references


def sample():
    return {'schema':'spatialforge.scene/v1','scene_id':'test','title':'Novel arrangement',
            'objects':[{'id':'unknown_object','label':'A novel object','kind':'box','size':[1,1,.1],
                        'color':[.2,.3,.4],'xy':[0,0],'support':'ground','base_z':0,'yaw_deg':0,
                        'dynamic':False,'mass_kg':1,'parts':[]}],
            'cameras':[{'position':[1,-2,2],'target':[0,0,0]}],'assumptions':['synthetic geometry']}


class Contracts(unittest.TestCase):
    def test_submillimeter_geometry_survives_validation_and_preview(self):
        from spatialforge.geometry_preview import preview_scene_geometry
        p=sample();obj=p['objects'][0]
        obj.update(kind='composite',size=[.3,.00025,.00025],parts=[{
            'shape':'cylinder','size':[.00025,.00025,.3],
            'rotation_deg_xyz':[0,90,0],'offset':[0,0,0],'color':[.8,.8,.8]}])
        sheet=copy.deepcopy(obj);sheet.update(id='sheet',kind='box',size=[.1,.04,.00015],parts=[],
            xy=[0,.1],appearance={'texture_id':'wood_laminate'})
        p['objects'].append(sheet)
        for schema in ('spatialforge.scene/v1','spatialforge.scene/v2'):
            p['schema']=schema;before=copy.deepcopy(p)
            self.assertEqual(validate_program(p),before)
            preview_scene_geometry(p)
            self.assertEqual(p,before)
        for value in (0,-.0001,float('nan')):
            invalid=copy.deepcopy(p);invalid['objects'][0]['parts'][0]['size'][0]=value
            with self.assertRaises(ValueError):validate_program(invalid)
            invalid=copy.deepcopy(p);invalid['objects'][1]['size'][2]=value
            with self.assertRaises(ValueError):validate_program(invalid)

    def test_omitted_yaw_matches_explicit_zero_without_rewriting_program(self):
        from spatialforge.geometry_preview import preview_scene_geometry
        for schema in ('spatialforge.scene/v1','spatialforge.scene/v2'):
            explicit=sample();explicit['schema']=schema
            child=copy.deepcopy(explicit['objects'][0]);child.update(id='child',support='unknown_object',size=[.1,.1,.1])
            explicit['objects'].append(child)
            expected=preview_scene_geometry(explicit)
            omitted=copy.deepcopy(explicit)
            for obj in omitted['objects']:obj.pop('yaw_deg')
            before=copy.deepcopy(omitted)
            validate_program(omitted)
            self.assertEqual(preview_scene_geometry(omitted),expected)
            self.assertEqual(omitted,before)
        for value in (None,'90',float('nan')):
            invalid=sample();invalid['objects'][0]['yaw_deg']=value
            with self.assertRaises(ValueError):validate_program(invalid)

    def test_noncomposite_parts_are_optional_without_rewriting_input(self):
        for kind in ('box','sphere','cylinder','container','mug'):
            p=sample();p['objects'][0]['kind']=kind;p['objects'][0].pop('parts')
            before=copy.deepcopy(p)
            self.assertEqual(validate_program(p),before)
            self.assertNotIn('parts',p['objects'][0])
        p['objects'][0]['kind']='composite'
        with self.assertRaisesRegex(ValueError,'composite needs parts'):validate_program(p)

    def test_registered_native_alias_preserves_input_and_generated_mesh_identity(self):
        p=sample();p['objects'][0].update(kind='mesh',asset_id='office_chair')
        generated=copy.deepcopy(p['objects'][0]);generated.update(id='bowl',asset_id='asset_1234567890abcdef');p['objects'].append(generated)
        before=copy.deepcopy(p);result=normalize_native_asset_references(p)
        self.assertEqual(p,before);self.assertEqual(result['objects'][0]['kind'],'office_chair')
        self.assertNotIn('asset_id',result['objects'][0]);self.assertEqual(result['objects'][1],generated)
        validate_program(result)
        p['objects'][0]['mesh_transform']={'orientation_deg_xyz':[0,0,0],'scale_mode':'uniform_fit'}
        fitted=normalize_native_asset_references(p);validate_program(fitted)
        self.assertNotIn('mesh_transform',fitted['objects'][0])
        self.assertTrue(all(fitted['objects'][0]['size'][i]<=p['objects'][0]['size'][i]+1e-9 for i in range(3)))
        p['objects'][0]['mesh_transform']={'orientation_deg_xyz':[90,0,0]}
        with self.assertRaisesRegex(ValueError,'native asset aliases'):normalize_native_asset_references(p)
    def test_infinite_lights_may_omit_position_but_local_lights_must_locate_source(self):
        for kind in ('environment','directional','sun'):
            p=sample();p['lights']=[{'id':'light','kind':kind,'intensity':100}];validate_program(p)
        for kind in ('point','spot','area'):
            p=sample();p['lights']=[{'id':'light','kind':kind,'intensity':100}]
            with self.assertRaisesRegex(ValueError,'needs position'):validate_program(p)
    def test_new_semantic_labels_and_small_scenes_work(self):validate_program(sample())

    def test_composites_are_not_limited_by_arbitrary_part_count(self):
        p=sample();obj=p['objects'][0];obj['kind']='composite';obj['size']=[2,2,2]
        obj['parts']=[{'shape':'box','size':[.1,.1,.1],'offset':[(-.8+(i%9)*.2),(-.8+((i//9)%9)*.2),(-.8+(i//81)*.2)],'color':[.5,.5,.5]} for i in range(27)]
        self.assertEqual(validate_program(p),p)
    def test_self_support_and_absent_support_fail(self):
        p=sample();p['objects'][0]['support']='unknown_object'
        with self.assertRaises(ValueError):validate_program(p)
    def test_nan_does_not_reach_isaac(self):
        p=sample();p['objects'][0]['xy'][0]=float('nan')
        with self.assertRaises(ValueError):validate_program(p)
    def test_no_model_code_escape(self):
        p=sample();p['objects'][0]['code']='print(1)'
        with self.assertRaises(ValueError):validate_program(p)
    def test_composite_parts_may_extend_beyond_placement_envelope(self):
        p=sample();o=p['objects'][0];o['kind']='composite';o['parts']=[{'shape':'box','size':[.2,.2,.2],'offset':[0,0,2],'color':[1,0,0]}]
        original=copy.deepcopy(p)
        validate_program(p)
        self.assertEqual(p,original)
    def test_support_graph_accepts_later_parents_without_reordering_submission(self):
        from spatialforge.support_graph import objects_in_support_order
        p=sample();parent=p['objects'][0]
        child=copy.deepcopy(parent);child.update(id='new_part',support=parent['id'])
        tip=copy.deepcopy(child);tip.update(id='tip',support='new_part')
        p['objects']=[tip,child,parent]
        before=copy.deepcopy(p)
        for schema in ('spatialforge.scene/v1','spatialforge.scene/v2'):
            p['schema']=before['schema']=schema
            validate_program(p)
            self.assertEqual(p,before)
            ordered=objects_in_support_order(p['objects'])
            self.assertEqual([o['id'] for o in ordered],[parent['id'],'new_part','tip'])
            self.assertIs(ordered[0],parent)
            self.assertEqual(objects_in_support_order(ordered),ordered)
        child['support']='tip'
        with self.assertRaisesRegex(ValueError,'cyclic support'):validate_program(p)
        child['support']='absent'
        with self.assertRaisesRegex(ValueError,'support.*does not exist'):validate_program(p)
    def test_closeup_and_vertical_cameras_are_valid_but_zero_view_is_not(self):
        p=sample();p['cameras']=[{'position':[.63,-.14,.75],'target':[.63,-.14,.4625]}]
        validate_program(p)
        p['cameras'][0]['target']=p['cameras'][0]['position'][:]
        with self.assertRaisesRegex(ValueError,'degenerate camera'):validate_program(p)
    def test_extension_retains_base_objects_and_metadata_without_mutating_delta(self):
        base=sample();base['schema']='spatialforge.scene/v2'
        base['materials']=[{'id':'wood','name':'wood'}];base['objects'][0]['material_id']='wood'
        added=sample();added['objects'][0].update(id='prop',support='unknown_object')
        original=copy.deepcopy(added)
        merged=merge_scene_extension(base,added);validate_program(merged)
        self.assertEqual(added,original);self.assertEqual(merged['objects'][0],base['objects'][0])
        self.assertEqual(merged['materials'],base['materials']);self.assertEqual(merged['schema'],'spatialforge.scene/v2')
        added['materials']=[{'id':'wood','name':'overwritten'}]
        with self.assertRaisesRegex(ValueError,'overwrites existing metadata'):merge_scene_extension(base,added)
    def test_executable_interactions_validate_even_when_affordances_exist(self):
        p=sample();p['objects'][0]['dynamic']=True
        p['affordances']=[{'id':'grasp','action':'grasp','object_id':'unknown_object'}]
        p['interactions']=[{'id':'push','action':'apply_force','object_id':'unknown_object','force_newtons':[1,0,0]}]
        validate_program(p)
        p['interactions'][0]['force_newtons']=[0,0,0]
        with self.assertRaisesRegex(ValueError,'magnitude'):validate_program(p)
    def test_mesh_transform_accepts_explicit_orientation_and_preserves_program(self):
        p=sample();obj=p['objects'][0];obj.update(kind='mesh',asset_id='registered_mesh')
        before=copy.deepcopy(p);validate_program(p);self.assertEqual(p,before)
        obj['mesh_transform']={'orientation_deg_xyz':[90,0,-90],'scale_mode':'uniform_fit'}
        before=copy.deepcopy(p);validate_program(p);self.assertEqual(p,before)
        obj.update(kind='generated',generation={'prompt':'A realistic object'})
        validate_program(p)
    def test_mesh_transform_rejects_distorting_modes_and_invalid_orientation(self):
        p=sample();obj=p['objects'][0];obj.update(kind='mesh',asset_id='registered_mesh')
        for transform in ({'scale_mode':'stretch_xyz'}, {'orientation_deg_xyz':[0,float('nan'),0]},
                          {'orientation_deg_xyz':[0,0]}, {'auto_pca':True}):
            with self.subTest(transform=transform):
                obj['mesh_transform']=transform
                with self.assertRaises(ValueError):validate_program(p)
        obj.update(kind='box',mesh_transform={'orientation_deg_xyz':[0,0,0]});obj.pop('asset_id')
        with self.assertRaisesRegex(ValueError,'only applies'):validate_program(p)
    def test_static_zero_mass_and_optional_camera_metadata_are_legal(self):
        p=sample();p['objects'][0]['mass_kg']=0
        p['cameras'][0]['id']='camera_full_interior_overview_from_open_south'
        validate_program(p)
        p['objects'][0]['dynamic']=True
        with self.assertRaisesRegex(ValueError,'invalid mass_kg'):validate_program(p)
    def test_protruding_parts_preserve_actual_preview_bounds_and_placement(self):
        from spatialforge.geometry_preview import preview_scene_geometry
        p=sample();obj=p['objects'][0];obj.update(kind='composite',size=[1,1,.012])
        obj['parts']=[{'shape':'box','size':[1,1,.014],'offset':[0,0,.001],'color':[0,0,0]},
                      {'shape':'box','size':[1,1,.016],'offset':[0,0,.002],'color':[0,0,0]}]
        validate_program(p)
        row=preview_scene_geometry(p)['objects'][0]
        self.assertAlmostEqual(row['initial_center_m'][2],.006)
        self.assertAlmostEqual(row['whole_object_top_z_m'],.012)
        self.assertAlmostEqual(row['composite_geometry']['top_z_m'],.016)
        self.assertAlmostEqual(row['composite_geometry']['top_inset_from_envelope_m'],-.004)
        self.assertAlmostEqual(row['box_top_faces'][1]['top_z_m'],.016)
    def test_apply_force_affordance_is_only_a_declaration_with_explicit_interactions(self):
        p=sample();p['objects'][0]['dynamic']=True
        p['affordances']=[{'id':'push_idea','action':'apply_force','object_id':'unknown_object'}]
        p['interactions']=[{'id':'push','action':'apply_force','object_id':'unknown_object','force_newtons':[1,0,0]}]
        validate_program(p)
    def test_registered_texture_supports_named_material_and_local_uv_override(self):
        p=sample();p['materials']=[{'id':'wood','name':'Wood','appearance':{'texture_id':'wood_laminate','uv_scale_m':[1,1]}}]
        p['objects'][0].update(material_id='wood',appearance={'uv_scale_m':[.5,2]})
        validate_program(p)
        for kind in ('sphere','cylinder','container'):
            p['objects'][0]['kind']=kind
            with self.subTest(kind=kind):validate_program(p)
    def test_textured_mixed_composite_preserves_parts(self):
        p=sample();obj=p['objects'][0]
        obj.update(kind='composite',appearance={'texture_id':'wood_laminate','roughness':.35},parts=[{'shape':'box','size':[1,1,.1],'offset':[0,0,0],'color':[.4,.3,.2]}])
        before=copy.deepcopy(obj);validate_program(p);self.assertEqual(obj,before)
        for kind in ('sphere','cylinder'):
            obj['parts'].append({'shape':kind,'size':[.1,.1,.1],'offset':[0,0,0],'color':[.4,.3,.2]})
        before=copy.deepcopy(obj);validate_program(p);self.assertEqual(obj,before)
    def test_texture_rejects_unknown_registry_ids_invalid_uv_and_external_paths(self):
        for appearance in ({'texture_id':'arbitrary_file'}, {'texture_id':'office_wall','uv_scale_m':[0,1]},
                           {'texture_id':'fabric_grid','uv_scale_m':[1,float('inf')]},
                           {'texture_path':'../../texture.png'}, {'uv_scale_m':[1,1]}):
            p=sample();p['objects'][0]['appearance']=appearance
            with self.subTest(appearance=appearance):
                with self.assertRaises(ValueError):validate_program(p)


if __name__=='__main__':unittest.main()
