import unittest
from scene_runtime import light_specs, material_for, mesh_import_plan, render_options, room_metadata, camera_up, interaction_plan, evaluate_force_trajectory, transform_mesh_geometry, box_mesh_with_metric_uv


class SceneRuntimeTests(unittest.TestCase):
    def test_submillimeter_textured_sheet_preserves_size_and_metric_uv(self):
        result=box_mesh_with_metric_uv([.1,.04,.00015],[.5,.5])
        self.assertAlmostEqual(max(p[2] for p in result['points'])-min(p[2] for p in result['points']),.00015)
        self.assertTrue(any(abs(uv[1]-.0003)<1e-10 for uv in result['st']))
        for thickness in (0,-.00015,float('nan')):
            with self.assertRaises(ValueError):box_mesh_with_metric_uv([.1,.04,thickness],[.5,.5])

    def test_rooms_are_metadata_only(self):
        result=room_metadata({'rooms':[{'id':'room','bounds':{'center':[0,0,0],'size':[3,3,3]}}], 'portals':[{'from_room':'room','to_room':'room'}]})
        self.assertEqual(result[0]['kind'],'metadata_only')
        self.assertEqual(result[0]['geometry_source'],'explicit_scene_objects')

    def test_render_and_lights(self):
        program={'render_environment':{'renderer':'PathTracing','samples_per_pixel':32,'exposure':0},'lights':[{'id':'key','kind':'area','position':[0,0,2],'size':[1,1],'intensity':500,'color':[1,1,1]}]}
        self.assertEqual(render_options(program, {})['renderer'],'PathTracing')
        self.assertEqual(light_specs(program)[0]['kind'],'rect')
        self.assertEqual(render_options(program, {})['exposure'],0)

    def test_gaussian_quality_default_preserves_explicit_render_choices(self):
        import copy
        program={'render_environment':{'exposure':.8}}
        original=copy.deepcopy(program)
        self.assertEqual(render_options(program, {}, has_gaussians=True),
                         {'renderer':'PathTracing','samples_per_pixel':128,'exposure':.8})
        self.assertEqual(program, original)
        self.assertEqual(render_options(program, {}, has_gaussians=False),
                         {'renderer':'RaytracedLighting','exposure':.8})
        program['render_environment'].update(renderer='RaytracedLighting')
        self.assertEqual(render_options(program, {}, has_gaussians=True)['renderer'],'RaytracedLighting')
        self.assertEqual(render_options({}, {'renderer':'RaytracedLighting'}, has_gaussians=True)['renderer'],'RaytracedLighting')
        self.assertEqual(render_options({}, {'renderer':'PathTracing','samples_per_pixel':64}, has_gaussians=True)['samples_per_pixel'],64)

    def test_declared_light_mapping_disabled_and_invalid_direction(self):
        kinds=['point','spot','area','directional','sun','environment']
        self.assertEqual([v['kind'] for v in light_specs({'lights':[{'kind':kind} for kind in kinds]})],['sphere','sphere','rect','distant','distant','dome'])
        self.assertEqual(light_specs({'lights':[{'kind':'point','enabled':False}]}),[])
        with self.assertRaisesRegex(ValueError,'direction'):
            light_specs({'lights':[{'kind':'sun','direction':[0,0,0]}]})

    def test_camera_up_handles_overhead_and_rejects_zero_direction(self):
        self.assertEqual(camera_up([0,0,2],[0,0,0]),[0,1,0])
        self.assertEqual(camera_up([2,0,2],[0,0,0]),[0,0,1])
        with self.assertRaises(ValueError):camera_up([0,0,0],[0,0,0])

    def test_material_precedence_and_pbr_fallback(self):
        program={'materials':[{'id':'wood','name':'Wood','base_color':[.2,.1,.05],'roughness':.8}],}
        obj={'material_id':'wood','color':[1,1,1],'appearance':{'metallic':.1}}
        material=material_for(program,obj)
        self.assertEqual(material['color'],[.2,.1,.05]);self.assertEqual(material['appearance']['roughness'],.8)
        self.assertTrue(mesh_import_plan({'materials':[{'textures':{}}]})['uses_vertex_color_fallback'])

    def test_force_plan_rejects_static_or_unbounded_actions(self):
        program={'objects':[{'id':'can','dynamic':False}], 'interactions':[{'id':'push','action':'apply_force','object_id':'can','force_newtons':[1,0,0]}]}
        with self.assertRaisesRegex(ValueError,'dynamic'):interaction_plan(program)
        program['objects'][0]['dynamic']=True
        program['interactions'][0]['duration_steps']=601
        with self.assertRaisesRegex(ValueError,'duration_steps'):interaction_plan(program)
        program['interactions'][0]['duration_steps']=1
        program['interactions'][0]['force_newtons']=[float('nan'),0,0]
        with self.assertRaisesRegex(ValueError,'force_newtons'):interaction_plan(program)

    def test_affordance_is_not_promoted_to_executed_action(self):
        result=interaction_plan({'objects':[], 'affordances':[{'id':'grasp','action':'grasp'}]})
        self.assertFalse(result[0]['supported'])

    def test_force_evidence_distinguishes_response_noop_drift_and_fall(self):
        action=interaction_plan({'objects':[{'id':'can','dynamic':True}], 'interactions':[{'id':'push','action':'apply_force','object_id':'can','force_newtons':[1,0,0],'duration_steps':1,'observe_steps':1}]})[0]
        def sample(x,z=0):return {'position':[x,0,z],'orientation_wxyz':[1,0,0,0],'linear_velocity_m_s':[0,0,0]}
        observed=[sample(0),sample(.03),sample(.04)]
        self.assertTrue(evaluate_force_trajectory(action,observed,0)['success'])
        self.assertFalse(evaluate_force_trajectory(action,[sample(0)]*3,0)['success'])
        self.assertFalse(evaluate_force_trajectory(action,observed,.1)['success'])
        self.assertFalse(evaluate_force_trajectory(action,[sample(0),sample(.03,-.2),sample(.04)],0)['success'])
        with self.assertRaisesRegex(ValueError,'incomplete'):evaluate_force_trajectory(action,observed[:2],0)

    def test_mesh_uniform_fit_preserves_shape_and_actual_bounds(self):
        import numpy as np
        source=np.array([[-1,-2,-.5],[1,2,.5],[-1,2,.5],[1,-2,-.5]])
        transformed,info=transform_mesh_geometry(source,[.2,.2,.2],'z_up')
        np.testing.assert_allclose(info['actual_size_m'],[.1,.2,.05])
        scale=info['uniform_scale']
        for a,b in [(0,1),(0,2),(1,3)]:
            self.assertAlmostEqual(np.linalg.norm(transformed[a]-transformed[b]),scale*np.linalg.norm(source[a]-source[b]))
        self.assertEqual(info['orientation_source'],'coordinate_frame_basis_only')
        self.assertEqual(len(set(info['normalization_scale_xyz'])),1)

    def test_explicit_rotation_follows_source_basis_without_guessing(self):
        import numpy as np
        source=np.array([[-1,-2,-.5],[1,2,.5],[-1,2,.5],[1,-2,-.5]])
        transformed,info=transform_mesh_geometry(source,[.2,.2,.2],'sam3d_camera',{'orientation_deg_xyz':[90,0,0],'scale_mode':'uniform_fit'})
        np.testing.assert_allclose(transformed,source*.05,atol=1e-12)
        self.assertEqual(info['gravity_alignment'],'unmeasured')
        self.assertEqual(info['orientation_source'],'explicit_declaration')
        with self.assertRaisesRegex(ValueError,'uniform_fit'):
            transform_mesh_geometry(source,[.2,.2,.2],'z_up',{'scale_mode':'stretch'})

    def test_textured_box_outward_normals_and_metric_uv(self):
        import numpy as np
        result=box_mesh_with_metric_uv([2,3,4],[.5,2])
        points=np.array(result['points']);uv=np.array(result['st'])
        self.assertEqual(result['face_vertex_counts'],[4]*6)
        for index,normal in enumerate(result['normals']):
            face=points[index*4:index*4+4];face_uv=uv[index*4:index*4+4]
            cross=np.cross(face[1]-face[0],face[2]-face[0]);cross/=np.linalg.norm(cross)
            np.testing.assert_allclose(cross,normal)
            self.assertAlmostEqual(np.linalg.norm(face[1]-face[0])/.5,face_uv[1,0])
            self.assertAlmostEqual(np.linalg.norm(face[2]-face[1])/2,face_uv[2,1])
        np.testing.assert_allclose(np.ptp(points,axis=0),[2,3,4])


if __name__=='__main__':unittest.main()
