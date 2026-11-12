import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from benchforge_core.pipelines.scene_policy import classify, check_submission, check_source, load_policy
from benchforge_core.pipelines.runner import execute_step


class ScenePolicyTests(unittest.TestCase):
    def test_pipeline_uses_policy_selected_by_service_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / 'scene-library' / 'policy.json'
            legacy.parent.mkdir()
            legacy.write_text(json.dumps({'enabled': True, 'excluded_tasks': ['sf_legacy.scene0']}))
            canonical = root / 'configured-policy.json'
            canonical.write_text(json.dumps({'enabled': True, 'enforce_realism': True,
                                             'excluded_tasks': ['sf_configured.scene0']}))
            service_config = {
                'execution_mode': 'production',
                'scene_policy_path': str(canonical),
            }
            with patch('benchforge_core.service_config.load_service_client_config', return_value=service_config):
                policy = load_policy(root, 'service.json')
            self.assertEqual(policy['execution_mode'], 'production')
            with self.assertRaisesRegex(ValueError, 'removed by the user'):
                check_source(policy, task_id='sf_configured.scene0')
            check_source(policy, task_id='sf_legacy.scene0')

    def test_explicit_exploration_mode_does_not_apply_production_admission_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_file = root / 'policy.json'
            policy_file.write_text(json.dumps({'enabled': True, 'enforce_realism': True,
                                               'excluded_tasks': ['sf_exploration.scene0']}))
            service_config = {'execution_mode': 'exploration',
                              'scene_policy_path': str(policy_file)}
            with patch('benchforge_core.service_config.load_service_client_config', return_value=service_config):
                policy = load_policy(root, 'service.json')
            self.assertEqual(policy, {'execution_mode': 'exploration'})

    def test_production_environment_cannot_silently_run_without_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict('os.environ', {'SPATIALFORGE_EXECUTION_MODE': 'production',
                                           'SPATIALFORGE_SCENE_POLICY': str(Path(tmp) / 'missing.json')}):
                with self.assertRaisesRegex(ValueError, 'requires an enabled'):
                    load_policy(tmp)

    def test_explicit_policy_environment_path_is_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / 'scene-library' / 'policy.json'
            legacy.parent.mkdir()
            legacy.write_text(json.dumps({'enabled': True, 'excluded_tasks': ['legacy']}))
            selected = root / 'canonical.json'
            selected.write_text(json.dumps({'enabled': True, 'enforce_realism': True,
                                            'excluded_tasks': ['canonical']}))
            with patch.dict('os.environ', {'SPATIALFORGE_SCENE_POLICY': str(selected)}):
                policy = load_policy(root)
            self.assertEqual(policy['execution_mode'], 'production')
            with self.assertRaisesRegex(ValueError, 'removed by the user'):
                check_source(policy, task_id='canonical')
            check_source(policy, task_id='legacy')

    def test_scene_extend_pipeline_is_registered_with_scene_program_binding(self):
        from benchforge_core.pipelines.catalog import pipeline_files
        from benchforge_core.pipelines.runner import stage_of
        definition=next(row for row in pipeline_files() if row['id']=='scene.extend')
        self.assertIn('scene_program_path',definition['inputs'])
        self.assertEqual(definition['steps'][0]['uses'],'spatialforge.extend')
        self.assertEqual(stage_of(definition['steps'][0]),'S2')

    def test_realism_policy_always_requires_a_saved_scene_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'scene-library';folder.mkdir()
            (folder/'policy.json').write_text(json.dumps({'enabled':True,'enforce_realism':True}))
            self.assertTrue(load_policy(root)['require_scene_brief'])

    def test_saved_geometry_declaration_is_shared_by_pipeline_and_scene_library(self):
        import sys
        from benchforge_core.pipelines.scene_policy import classify_planned
        from benchforge_core.pipelines.assessment import validate_assessment
        from tests.test_assessment_plan import assessment_fixture, AssessmentPlanTests
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.policy(root)
            value=assessment_fixture();value['scenes']['designs'][0]['id']='geometry-design'
            value['scenes']['designs'][0].update(name='规则几何空间关系实验',
                summary='本场景使用规则几何物体隔离相对位置判断能力，目标物体放在房间中央并与观察对象保持明确间距。地面平整，物体底面完整接触支撑面，周围留出观察和通行空间。场景不模拟日常家具的具体外形，但仍保留稳定支撑、正常尺度和不穿插等实验约束。固定相机覆盖目标物及相邻参照物，无遮挡。'*2,
                hard_requirements=['目标物体保持规则几何与正常支撑'],
                physical_assumptions=['采用合成质量与摩擦先验，只验证本场景的稳定支撑关系'],
                object_roles=[{'object_id':'target','role':'规则目标物体，用于测量空间位置关系'}],
                relations=[{'source':'target','type':'supported_by','target':'ground','description':'目标物体底面接触地面并稳定支撑'}])
            declaration={'scene_design_id':'geometry-design','scene_id':'geometry-scene','object_ids':['target'],
                'purpose':'隔离语义线索后的相对位置测量','reason':'以规则方块只测量几何推理能力',
                'simplifications':'目标物仅保留规则立方体的轮廓','retained_constraints':'保留重力、接触支撑和不穿插约束',
                'excluded_claims':'不声称日常室内写实或家具识别能力'}
            value['scenes']['geometry_exceptions']=[declaration]
            validate_assessment(value,AssessmentPlanTests.selections,AssessmentPlanTests.inputs)
            file=root/'plan.json';file.write_text(json.dumps({'assessment':value}))
            program={'scene_id':'geometry-scene','objects':[{'id':'target','kind':'box','support':'ground'}],
                'provenance':{'sources':[{'kind':'scene_plan','path':str(file),'scene_design_id':'geometry-design'}]}}
            self.assertTrue(classify_planned(program)['allowed'])
            bad=json.loads(json.dumps(value));bad['scenes']['geometry_exceptions'][0]['purpose']=''
            with self.assertRaisesRegex(ValueError,'purpose'):
                validate_assessment(bad,AssessmentPlanTests.selections,AssessmentPlanTests.inputs)
            ui=Path(__file__).resolve().parents[1]/'integrations/spatialforge/ui'
            with patch.object(sys,'path',[str(ui),*sys.path]):
                spec=importlib.util.spec_from_file_location('test_geometry_library',ui/'scene_library.py')
                library=importlib.util.module_from_spec(spec);spec.loader.exec_module(library)
            runtime=root/'runtime';source=runtime/'sf_geometry.scene0/revision_0';capture=source/'capture';capture.mkdir(parents=True)
            for relative,payload in [('program.json',program),('capture/report.json',{}),('capture/evidence.json',{})]:
                (source/relative).write_text(json.dumps(payload))
            task={'id':'sf_geometry.scene0','run_id':'sf_geometry','unit':{'revision':0,'intent':{'name':'几何相对位置实验'}},
                'request_key':'dsh:session-geometry:scene','created_at':1}
            policy=load_policy(root);policy['enforce_realism']=True
            (root/'scene-library/policy.json').write_text(json.dumps(policy))
            (capture/'view_0.png').write_bytes(b'fixture-image')
            with patch.object(sys,'path',[str(ui),*sys.path]), patch.object(library,'completed_tasks',return_value=[task]):
                catalog=library.sync_catalog({'artifacts':str(runtime)},root/'scene-library')
                self.assertEqual(catalog['items'][0]['scene_style'],'simplified_geometry')
                self.assertFalse(catalog['items'][0]['production_eligible'])
                selection=library.load_selection(root/'scene-library','session-geometry',catalog)
                self.assertEqual(selection['selected'],[])
                from benchforge_core.pipelines.scene_policy import scene_design_parser
                receipt={'passed':True,'enforced':True,'geometry_exception':classify_planned(program)['geometry_exception'],
                    'scene_brief':scene_design_parser().scene_brief(program,policy,root),
                    'evidence_versions':{relative:[(source/relative).stat().st_size,(source/relative).stat().st_mtime_ns]
                                         for relative in ('program.json','capture/report.json','capture/evidence.json')}}
                (source/'scene_acceptance.json').write_text(json.dumps(receipt))
                catalog=library.sync_catalog({'artifacts':str(runtime)},root/'scene-library')
                self.assertTrue(catalog['items'][0]['production_eligible'])
                library.save_selection(root/'scene-library','session-geometry',catalog,
                    {**selection,'selected':[{'id':task['id'],'revision':0}],'allow_new_scenes':False})
                file.write_text(file.read_text()+'\n')
                catalog=library.sync_catalog({'artifacts':str(runtime)},root/'scene-library')
                self.assertTrue(catalog['items'][0]['production_eligible'])
                self.assertEqual(len(library.load_selection(root/'scene-library','session-geometry',catalog)['selected']),1)
                value['scoring']['summary']='Only scoring prose changed; scene geometry is unchanged'
                file.write_text(json.dumps({'assessment':value},indent=2))
                catalog=library.sync_catalog({'artifacts':str(runtime)},root/'scene-library')
                self.assertTrue(catalog['items'][0]['production_eligible'])
                value['scenes']['designs'][0]['hard_requirements'].append('A new scene support requirement')
                file.write_text(json.dumps({'assessment':value}))
                catalog=library.sync_catalog({'artifacts':str(runtime)},root/'scene-library')
                self.assertFalse(catalog['items'][0]['production_eligible'])
                self.assertEqual(library.load_selection(root/'scene-library','session-geometry',catalog)['selected'],[])
            with self.assertRaises(ValueError):
                check_submission(root,'/capture',{'scene_program_path':str(root/'deleted/program.json')})

    def test_structures_and_real_asset_scenes_are_not_cube_scenes(self):
        structures=[{'id':'floor','kind':'box'},{'id':'wall_north','kind':'box'}]
        self.assertTrue(classify({'objects':structures})['allowed'])
        self.assertTrue(classify({'objects':structures+[{'id':'chair','kind':'mesh'},
            {'id':'desk','kind':'office_desk'},{'id':'shipping_crate','kind':'mesh'}]})['allowed'])
        self.assertTrue(classify({'objects':[{'id':'bicycle','kind':'mesh'},
            {'id':'rack','kind':'composite'},{'id':'bin','kind':'bin'}]})['allowed'])

    def test_furniture_names_and_one_distractor_cannot_disguise_cube_proxies(self):
        self.assertFalse(classify({'objects':[{'id':'chair','kind':'box'},{'id':'desk','kind':'box'}]})['allowed'])
        self.assertFalse(classify({'objects':[{'id':'a','kind':'box'},{'id':'b','kind':'box'},
            {'id':'c','kind':'box'},{'id':'d','kind':'box'},{'id':'mug','kind':'mug'}]})['allowed'])
        self.assertFalse(classify({'objects':[{'id':'chair','kind':'mesh'},{'id':'red_cube','kind':'box'}]})['allowed'])
        self.assertFalse(classify({'objects':[{'id':'tree','kind':'mesh'},{'id':'shed','kind':'box'},
            {'id':'plant','kind':'office_plant'},{'id':'mug','kind':'mug'}]})['allowed'])

    def policy(self, root):
        folder=root/'scene-library';folder.mkdir()
        (folder/'policy.json').write_text(json.dumps({'enabled':True,'enforce_realism':True,'excluded_tasks':['sf_removed.scene0'],
            'excluded_scene_groups':['scene-v1:removed'],'excluded_paths':[str(root/'deleted')]}))

    def test_submit_and_pipeline_reject_before_queue_and_accept_recognizable_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.policy(root)
            plan=root/'plan.json'
            plan.write_text(json.dumps({'schema':'spatialforge.assessment/v1','scenes':{'designs':[{
                'id':'chair-scene','name':'Chair scene','summary':'A chair stands on the floor with clear access around it.',
                'hard_requirements':['The chair remains upright'],'physical_assumptions':['Static support'],
                'object_roles':[{'object_id':'chair','role':'A chair used to test scene admission'}],
                'relations':[{'source':'chair','type':'supported_by','target':'ground','description':'The floor supports the chair'}]
            }]}}))
            program_value={'scene_id':'chair-scene',
                'objects':[{'id':'chair','kind':'box'}],
                'provenance':{'sources':[{'kind':'scene_plan','path':str(plan),'scene_design_id':'chair-scene'}]}}
            program=root/'program.json';program.write_text(json.dumps(program_value))
            client=Mock()
            environment={'_workspace':str(root),'inputs':{},'_run_key':'fixture'}
            with self.assertRaisesRegex(ValueError,'Scene rejected'):
                execute_step({'id':'capture','uses':'spatialforge.capture'},{'scene_program_path':str(program)},root,environment,client)
            client.assert_not_called()
            program_value['objects'][0]['kind']='mesh'
            program.write_text(json.dumps(program_value))
            check_submission(root,'/capture',{'scene_program_path':str(program)})
            with self.assertRaisesRegex(ValueError,'unchecked default planner'):
                check_submission(root,'/start',{'intents':[{'name':'house'}]})
            with self.assertRaisesRegex(ValueError,'scene_program_path'):
                check_submission(root,'/refine',{'parent_task_id':'sf_parent.scene0'})
            with self.assertRaisesRegex(ValueError,'scene_program_path'):
                check_submission(root,'/extend',{'parent_task_id':'sf_parent.scene0'})
            with self.assertRaisesRegex(ValueError,'removed by the user'):
                check_submission(root,'/dataset',{'intent':{'source_task_id':'sf_removed.scene0'}})
            with self.assertRaisesRegex(ValueError,'Unreviewed scene retries'):
                check_submission(root,'/retry',{'task_id':'sf_failed.scene0'})
            with self.assertRaises(ValueError):
                check_source(load_policy(root),scene_group='scene-v1:removed')

    def test_removal_moves_only_rejected_tasks_and_clears_saved_selections(self):
        spec=importlib.util.spec_from_file_location('remove_cubes',Path(__file__).resolve().parents[1]/'integrations/spatialforge/remove_cube_scenes.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ws=root/'workspace';library=ws/'scene-library';(library/'selections').mkdir(parents=True)
            runtime=root/'runtime';runtime.mkdir();items=[]
            for name,kind in [('sf_cube','box'),('sf_asset','mesh')]:
                source=runtime/(name+'.scene0')/'revision_0';source.mkdir(parents=True)
                (source/'program.json').write_text(json.dumps({'scene_id':name,'objects':[{'id':'chair','kind':kind}]}))
                items.append({'id':name+'.scene0','task_id':name+'.scene0','run_id':name,'name':name,'revision':0,'source_directory':str(source)})
            (library/'catalog.json').write_text(json.dumps({'items':items}))
            selection=library/'selections/session-test.json'
            selection.write_text(json.dumps({'selected':[{'id':row['id'],'revision':0} for row in items],'version':1}))
            result=module.remove(ws,runtime,True)
            self.assertEqual((result['removed'],result['remaining']),(1,1))
            policy=json.loads((library/'policy.json').read_text(encoding='utf-8'))
            self.assertTrue(policy['enforce_realism'])
            self.assertTrue(policy['require_scene_brief'])
            self.assertFalse((runtime/'sf_cube.scene0').exists())
            self.assertTrue((runtime/'sf_asset.scene0/revision_0/program.json').exists())
            self.assertTrue((Path(result['runtime_archive'])/'sf_cube.scene0/revision_0/program.json').exists())
            self.assertEqual(json.loads(selection.read_text(encoding='utf-8'))['selected'],[{'id':'sf_asset.scene0','revision':0}])
            with self.assertRaises(ValueError):check_source(load_policy(ws),task_id='sf_cube.scene0')
            with self.assertRaises(ValueError):check_source(load_policy(ws),source_path=result['runtime_archive'])

