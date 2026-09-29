import copy
import json
import tempfile
import unittest
from pathlib import Path
from spatialforge.geometry_preview import mesh_fit_preview,preview_scene_geometry,compact_preview
from test_contracts import sample


def block(name,size,xy=(0,0),support='ground',base_z=0,yaw=0,parts=None):
    obj=sample()['objects'][0]
    obj.update(id=name,kind='composite' if parts else 'box',size=size,xy=list(xy),support=support,
               base_z=base_z,yaw_deg=yaw,parts=parts or [])
    return obj


def mesh(extent=(2,1,.5)):
    return {'coordinate_frame':'z_up','vertices':[[x*extent[0]/2,y*extent[1]/2,z*extent[2]/2] for x in (-1,1) for y in (-1,1) for z in (-1,1)]}


class GeometryPreviewTests(unittest.TestCase):
    def test_unordered_supports_keep_paths_and_use_actual_mesh_height(self):
        p=sample()
        table=block('table',[1,1,.7])
        fitted=block('fitted',[1,1,1],support='table')
        fitted.update(kind='mesh',asset_id='asset_0000000000000001')
        prop=block('prop',[.1,.1,.2],support='fitted',base_z=.03)
        p['objects']=[prop,fitted,table]
        before=copy.deepcopy(p)
        result=preview_scene_geometry(p,mesh_loader=lambda _:mesh((2,1,.5)))
        self.assertEqual([r['object_id'] for r in result['objects']],['prop','fitted','table'])
        self.assertEqual([r['path'] for r in result['objects']],['/objects/0','/objects/1','/objects/2'])
        self.assertAlmostEqual(result['objects'][1]['actual_size_m'][2],.25)
        self.assertAlmostEqual(result['objects'][0]['initial_bottom_z_m'],.98)
        p['objects']=[table,fitted,prop]
        ordered=preview_scene_geometry(p,mesh_loader=lambda _:mesh((2,1,.5)))
        self.assertEqual({r['object_id']:r['initial_center_m'] for r in result['objects']},
                         {r['object_id']:r['initial_center_m'] for r in ordered['objects']})
        p['objects']=[prop,fitted,table]
        self.assertEqual(p,before)

    def test_thickness_bottleneck_and_alternative_envelopes_are_explicit(self):
        result=mesh_fit_preview(mesh(),[.4,.3,.02])
        self.assertEqual(result['limiting_axes'],['z'])
        self.assertEqual(result['actual_size_m'],[.08,.04,.02])
        option=result['axis_target_examples'][0]
        self.assertEqual(option['proportional_envelope_m'],[.4,.2,.1])
        self.assertEqual(option['exceeds_original_limits_on'],['z'])
        self.assertEqual(result['semantic_upright'],'not_inferred')

    def test_source_basis_and_euler_rotation_precede_fit(self):
        source=mesh();source['coordinate_frame']='sam3d_camera'
        result=mesh_fit_preview(source,[.4,.3,.02],{'orientation_deg_xyz':[90,0,0]})
        for actual,expected in zip(result['actual_size_m'],[.08,.04,.02]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(result['gravity_alignment'],'unmeasured')
        self.assertEqual(result['orientation_source'],'explicit_declaration')

    def test_rotated_shelf_faces_use_world_xy_and_existing_negative_base_offset(self):
        p=sample();p['schema']='spatialforge.scene/v2'
        parts=[{'shape':'box','size':[2,.5,.04],'offset':[0,0,z],'color':[.5]*3} for z in (-.8,.7)]
        shelf=block('shelf',[2,.5,2],xy=(2,3),base_z=.2,yaw=90,parts=parts)
        child=block('prop',[.2,.2,.1],xy=(2,3),support='shelf',base_z=-1.78)
        p['objects']=[shelf,child];original=copy.deepcopy(p)
        result=preview_scene_geometry(p);faces=result['objects'][0]['box_top_faces']
        self.assertAlmostEqual(faces[0]['top_z_m'],.42)
        self.assertEqual(faces[0]['world_xy'],[2,3])
        self.assertAlmostEqual(faces[0]['world_corners_xy'][0][0],2.25)
        self.assertAlmostEqual(faces[0]['world_corners_xy'][0][1],2)
        options=result['objects'][1]['support_face_options']
        self.assertTrue(options[0]['footprint_within_face']);self.assertAlmostEqual(options[0]['current_bottom_gap_m'],0)
        self.assertTrue(options[0]['base_z_allowed_by_schema'])
        self.assertEqual(p,original)
        self.assertEqual([(w['object_id'],w['code']) for w in result['warnings']],[('shelf','composite_geometry_inset')])
        p['schema']='spatialforge.scene/v1'
        from spatialforge.contracts import validate_program
        validate_program(p)
        self.assertTrue(preview_scene_geometry(p)['objects'][0]['box_top_faces'][0]['base_z_allowed_by_schema'])

    def test_whole_top_does_not_claim_it_is_a_lower_board_and_overhang_is_not_contact(self):
        p=sample();p['schema']='spatialforge.scene/v2'
        shelf=block('shelf',[2,.4,2],parts=[{'shape':'box','size':[2,.4,.04],'offset':[0,0,-.5],'color':[.5]*3}])
        p['objects']=[shelf,block('prop',[.2,.2,.1],support='shelf')]
        result=preview_scene_geometry(p)
        self.assertEqual(result['objects'][1]['initial_bottom_z_m'],2)
        self.assertAlmostEqual(result['objects'][1]['support_face_options'][0]['current_bottom_gap_m'],1.48)
        self.assertIn('no_full_box_face_at_declared_height',[w['code'] for w in result['warnings']])
        p['objects'][1].update(base_z=-1.48,xy=[1,0])
        self.assertFalse(preview_scene_geometry(p)['objects'][1]['support_face_options'][0]['footprint_within_face'])

    def test_composite_underfilled_envelope_exposes_actual_bottom_without_moving_parts(self):
        p=sample();p['schema']='spatialforge.scene/v2'
        tray=block('tray',[.12,.55,.78],parts=[{'shape':'box','size':[.12,.55,.015],'offset':[0,0,-.0525],'color':[1]*3},
            {'shape':'cylinder','size':[.015,.015,.11],'offset':[0,0,0],'color':[1]*3}])
        p['objects']=[tray];original=copy.deepcopy(p)
        preview=preview_scene_geometry(p);row=preview['objects'][0]
        self.assertEqual(row['initial_bottom_z_m'],0)
        self.assertAlmostEqual(row['initial_geometry_bottom_z_m'],.33)
        self.assertAlmostEqual(row['composite_geometry']['top_z_m'],.445)
        self.assertAlmostEqual(row['base_z_for_geometry_bottom_at_support_envelope'],-.33)
        self.assertIn('composite_geometry_inset',[w['code'] for w in preview['warnings']])
        self.assertEqual(compact_preview(preview)['objects'][0]['composite_geometry']['bottom_z_m'],.33)
        self.assertEqual(p,original)

    def test_child_geometry_contact_offsets_use_parts_while_descendants_keep_envelope_contract(self):
        p=sample();p['schema']='spatialforge.scene/v2'
        p['objects']=[block('shelf',[1,1,.2]),
            block('tray',[.4,.4,.8],support='shelf',parts=[{'shape':'sphere','size':[.2,.2,.1],'offset':[0,0,-.05],'color':[1]*3}]),
            block('child',[.1]*3,support='tray')]
        preview=preview_scene_geometry(p);row=preview['objects'][1]
        self.assertAlmostEqual(row['support_face_options'][0]['current_bottom_gap_m'],0)
        self.assertAlmostEqual(row['support_face_options'][0]['geometry_bottom_gap_m'],.3)
        self.assertAlmostEqual(row['support_face_options'][0]['geometry_base_z_for_contact'],-.3)
        self.assertEqual(preview['objects'][2]['initial_bottom_z_m'],1)
        self.assertIn('no_full_box_face_at_declared_height',[w['code'] for w in preview['warnings'] if w['object_id']=='tray'])
        p['objects'][1]['base_z']=-.3
        corrected=preview_scene_geometry(p)['objects'][1]
        self.assertAlmostEqual(corrected['support_face_options'][0]['geometry_bottom_gap_m'],0)
        p['schema']='spatialforge.scene/v1'
        self.assertFalse(preview_scene_geometry(p)['objects'][1]['support_face_options'][0]['geometry_base_z_allowed_by_schema'])

    def test_reused_mesh_read_once_and_actual_height_propagates_to_child(self):
        p=sample();first=block('mesh_a',[.4,.3,.02]);first.update(kind='mesh',asset_id='asset_1234567890abcdef')
        second=copy.deepcopy(first);second['id']='mesh_b'
        p['objects']=[first,second,block('child',[.02]*3,support='mesh_a')]
        calls=[]
        def loader(asset_id):calls.append(asset_id);return mesh()
        preview=preview_scene_geometry(p,mesh_loader=loader)
        self.assertEqual(len(calls),1);self.assertEqual(preview['mesh_assets_read'],1)
        self.assertAlmostEqual(preview['objects'][2]['initial_bottom_z_m'],.02)

    def test_missing_mesh_does_not_invent_child_height_or_escape_registry(self):
        p=sample();obj=block('asset',[1]*3);obj.update(kind='mesh',asset_id='../escape')
        p['objects']=[obj,block('child',[.1]*3,support='asset')]
        with tempfile.TemporaryDirectory() as temp:
            preview=preview_scene_geometry(p,Path(temp))
        self.assertIsNone(preview['objects'][0]['actual_size_m'])
        self.assertIsNone(preview['objects'][1]['initial_center_m'])
        self.assertEqual(len(preview['warnings']),2)
        self.assertIn('invalid registered asset ID',preview['objects'][0]['unavailable'])

    def test_compact_feedback_has_hard_object_and_face_budgets(self):
        p=sample();p['objects']=[block('shelf',[2,.4,2],parts=[{'shape':'box','size':[2,.4,.01],'offset':[0,0,-.9+i*.02],'color':[.5]*3} for i in range(64)])]
        p['objects'] += [block('prop_'+str(i),[.1]*3,support='shelf') for i in range(50)]
        compact=compact_preview(preview_scene_geometry(p))
        self.assertLessEqual(len(compact['objects']),32);self.assertGreater(compact['truncated_objects'],0)
        self.assertTrue(all(len(r.get('support_face_options',[]))<=12 for r in compact['objects']))
        self.assertLessEqual(len(json.dumps(compact)),24000)


if __name__=='__main__':unittest.main()
