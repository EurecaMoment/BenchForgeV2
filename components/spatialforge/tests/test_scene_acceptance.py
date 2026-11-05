import copy
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

from spatialforge import engine
from spatialforge.contracts import ASSETS
from spatialforge.scene_acceptance import (admit_program, capture_acceptance, check_request,
                                          require_accepted, VISUAL_CHECKS)
from spatialforge.products import produce
from test_contracts import sample


class SceneAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.artifacts=self.root/'runtime';self.artifacts.mkdir()
        folder=self.root/'scene-library';folder.mkdir()
        self.policy=folder/'policy.json';self.policy.write_text(json.dumps({'enabled':True,'enforce_realism':True}))
        self.env=patch.dict(os.environ,{'SPATIALFORGE_SCENE_POLICY':str(self.policy)})
        self.env.start();self.addCleanup(self.env.stop)
        self.program=sample();self.program['objects'][0].update(id='cup',label='ceramic mug',kind='mug',size=ASSETS['mug']['size'])
        self.plan=self.root/'scene-plan.json'
        brief={'id':'fixture-scene','name':'明亮住宅餐桌上的陶杯场景',
            'summary':'这是一个用于检查住宅餐桌物体关系的真实场景，陶杯正立放在餐桌中央偏右的位置，杯底完整接触桌面，杯把朝向靠椅一侧，便于坐姿使用者拿取。桌椅之间留有腿部空间，桌面周围保持连续净空，窗光从侧面照入且不遮挡主要观察视线。餐桌靠近厨房一侧，日常通行路线从椅背后方经过且留有充分宽度。相机设置在入口斜前方，既能看见杯把与杯底的接触，也能辨认椅子相对桌沿的位置；场景不依赖隐藏标签判断物体用途。场景中的质量和摩擦采用合成参数，验收只证明本次静态布局和沉降状态。',
            'hard_requirements':['陶杯保持正立并稳定支撑'],'physical_assumptions':['使用未校准的合成质量和摩擦参数，只验收本次沉降状态'],
            'object_roles':[{'object_id':'cup','role':'陶杯放在桌面并面向使用者，供观察和取用'}],
            'relations':[{'source':'cup','type':'supported_by','target':'ground','description':'陶杯由场景桌面区域支撑并保持稳定'}]}
        self.plan.write_text(json.dumps({'assessment':{'schema':'spatialforge.assessment/v1','scenes':{'designs':[brief]}}}))
        self.program['provenance']={'sources':[{'kind':'scene_plan','path':str(self.plan),'scene_design_id':'fixture-scene'}]}
        self.directory=self.artifacts/'sf_test.scene0/revision_0';self.capture=self.directory/'capture';self.capture.mkdir(parents=True)
        self.report={'status':'captured','renderable':True,'physics':{'stable':True},'token':'native-attempt'}
        self.evidence={'origin':'isaac_native','token':'native-attempt','physics':{'stable':True,'steps':120,'dt':1/60},
            'frames':[{'frame_id':'view_0'}],'entities':{'cup':{'collision':{'paths':['/World/cup/Geometry']},
            'world_aabb':{'min':[-.04,-.06,0],'max':[.04,.06,.091]}}}}
        self.review={'acceptable':True,'visual_realism':{'status':'visually_plausible'},
            'brief_alignment':{'passed':True,'hard_requirements_preserved':True,'unresolved':[],
                'observations':[{'view':'view_0.png','observation':'实拍中陶杯正立放置，杯底接触场景支撑面，周围可见桌面净空。'}],
                'requirement_checks':[{'index':0,'passed':True,'view':'view_0.png','observation':'实拍中陶杯正立并由支撑面承托。'}],
                'relation_checks':[]},
            'life_review':{'checks':[
            {'check':name,'passed':True,'evidence':[{'view':'view_0.png','observation':'The captured mug is visible with its handle, resting on the ground.'}]} for name in VISUAL_CHECKS]}}
        self.save()

    def save(self):
        for path,value in [(self.directory/'program.json',self.program),(self.capture/'report.json',self.report),(self.capture/'evidence.json',self.evidence)]:
            path.write_text(json.dumps(value),encoding='utf-8')
        (self.capture/'view_0.png').write_bytes(b'fixture-image')

    def assess(self):
        return capture_acceptance(self.artifacts,self.program,self.report,self.evidence,self.review,self.capture)

    def test_real_assets_pass_but_cube_spoofs_floating_objects_and_unreal_scale_fail(self):
        self.assertTrue(admit_program(self.artifacts,self.program)['passed'])
        for edits in ({'kind':'box'},{'kind':'box','id':'floor_fake','size':[1,1,1]},
                      {'base_z':1},{'size':[9,9,9]}):
            proposal=copy.deepcopy(self.program);proposal['objects'][0].update(edits)
            with self.subTest(edits=edits),self.assertRaises(ValueError):admit_program(self.artifacts,proposal)

    def test_enforced_realism_requires_a_saved_brief_before_scene_submission(self):
        self.program.pop('provenance')
        with self.assertRaisesRegex(ValueError,'titled, detailed scene brief'):
            admit_program(self.artifacts,self.program)

    def test_stable_static_boolean_is_insufficient_and_overlapping_bounds_block_delivery(self):
        self.assertTrue(self.assess()['passed'])
        self.evidence['entities']['cup']['world_aabb']['min'][2]=.2
        self.evidence['entities']['cup']['world_aabb']['max'][2]=.3
        self.assertFalse(self.assess()['passed'])
        self.evidence['entities']['cup']['world_aabb']={'min':[-.04,-.06,0],'max':[.04,.06,.091]}
        other=copy.deepcopy(self.program['objects'][0]);other['id']='cup2';self.program['objects'].append(other)
        self.evidence['entities']['cup2']=copy.deepcopy(self.evidence['entities']['cup'])
        self.assertTrue(any('overlapping' in issue for issue in self.assess()['issues']))

    def test_native_relation_report_is_scoped_to_each_relation(self):
        table = copy.deepcopy(self.program['objects'][0])
        table.update(id='table', label='dining table', kind='office_coffee_table',
                     size=ASSETS['office_coffee_table']['size'], support='ground', base_z=0)
        self.program['objects'].append(table)
        self.evidence['entities']['table'] = {
            'collision': {'paths': ['/World/table/Geometry']},
            'world_aabb': {'min':[.4, -.5, 0], 'max':[1.4, .5, .75]},
        }
        saved = json.loads(self.plan.read_text())
        saved['assessment']['scenes']['designs'][0]['relations'] = [
            {'source':'cup', 'type':'supported_by', 'target':'ground',
             'description':'杯子保持稳定支撑'},
            {'source':'table', 'type':'supported_by', 'target':'ground',
             'description':'餐桌保持稳定支撑'},
        ]
        self.plan.write_text(json.dumps(saved))
        self.evidence['entities']['cup']['world_aabb']['min'][2] = .2
        self.evidence['entities']['cup']['world_aabb']['max'][2] = .3
        receipt = self.assess()
        checks = {row['source']: row for row in receipt['native_relation_checks']}
        self.assertFalse(checks['cup']['passed'])
        self.assertTrue(checks['table']['passed'])
        self.assertTrue(any('cup: native geometry floats' in issue for issue in receipt['physical_issues']))

    def test_visual_review_requires_six_checks_and_real_image_references(self):
        self.review['life_review']['checks'][0]['evidence'][0]['view']='invented.png'
        self.assertFalse(self.assess()['passed'])
        self.review['life_review']['checks']=[]
        self.assertFalse(self.assess()['passed'])
        self.evidence['physics']={'stable':True}
        self.assertTrue(any('physics rollout' in issue for issue in self.assess()['issues']))

    def test_unreviewed_planner_and_direct_export_are_blocked(self):
        with self.assertRaisesRegex(ValueError,'default planner'):check_request(self.artifacts,'/start',{'intents':[{'name':'room'}]})
        with self.assertRaisesRegex(ValueError,'no passing'):produce(self.directory)
        with self.assertRaisesRegex(ValueError,'retries'):check_request(self.artifacts,'/retry',{'task_id':'sf_old.scene0'})

    def test_failed_capture_only_review_cannot_mark_success_or_export(self):
        self.review['life_review']['checks'][0]['passed']=False
        store=Mock();store.root=self.artifacts;store.directory.return_value=self.directory;store.snapshot.return_value={'state':'RUNNING'}
        task={'id':'sf_test.scene0','run_id':'sf_test','unit':{'revision':0,'phase':'review','workflow':'scene','intent':{'capture_only':True},'submitted_program':{'program':self.program}}}
        with patch.object(engine,'completion',return_value=self.review),patch.object(engine,'produce',side_effect=AssertionError('invalid export')):
            engine.review_scene(store,task,Event(),capture_only=True)
        self.assertEqual(store.update.call_args.kwargs['state'],'FAILED_FINAL')
        self.assertFalse((self.directory/'scene_acceptance.json').exists() and json.loads((self.directory/'scene_acceptance.json').read_text(encoding='utf-8'))['passed'])

    def test_passing_receipt_is_invalidated_by_source_change(self):
        receipt=self.assess();self.assertTrue(receipt['passed'])
        (self.directory/'scene_acceptance.json').write_text(json.dumps(receipt))
        require_accepted(self.artifacts,self.directory)
        (self.directory/'program.json').write_text(json.dumps({**self.program,'title':'changed scene'}))
        with self.assertRaisesRegex(ValueError,'changed'):require_accepted(self.artifacts,self.directory)

    def test_accepted_capture_only_gets_reviewed_without_export(self):
        store=Mock();store.root=self.artifacts;store.directory.return_value=self.directory;store.snapshot.return_value={'state':'RUNNING'}
        task={'id':'sf_test.scene0','run_id':'sf_test','unit':{'revision':0,'phase':'review','intent':{'capture_only':True}}}
        with patch.object(engine,'completion',return_value=self.review),patch.object(engine,'produce',side_effect=AssertionError('capture-only export')):
            engine.review_scene(store,task,Event(),capture_only=True)
        self.assertEqual(store.update.call_args.kwargs['state'],'SUCCEEDED')
        require_accepted(self.artifacts,self.directory)

    def declare_geometry(self):
        self.program['objects'][0]['kind'] = 'box'
        declaration = {'scene_design_id': 'spatial-layout', 'scene_id': self.program['scene_id'],
                       'object_ids': ['cup'], 'purpose': '测量规则几何之间的空间关系',
                       'reason': '去掉纹理和语义线索以隔离几何能力',
                       'simplifications': '本场景的目标物仅使用规则方块',
                       'retained_constraints': '方块须接触地面并通过原生物理沉降',
                       'excluded_claims': '不声称真实家具辨识或日常室内写实能力'}
        brief={'id':'spatial-layout','name':'规则几何空间关系实验',
            'summary':'本场景使用规则几何物体隔离相对位置判断能力，目标物体放在房间中央并与观察对象保持明确间距。地面平整，物体底面完整接触支撑面，周围留出观察和通行空间。场景不模拟日常家具的具体外形，但仍保留稳定支撑、正常尺度和不穿插等实验约束。固定相机覆盖目标物及相邻参照物，无遮挡。'*2,
            'hard_requirements':['目标物体保持规则几何与正常支撑'],
            'physical_assumptions':['采用合成质量与摩擦先验，只验证本场景的稳定支撑关系'],
            'object_roles':[{'object_id':'cup','role':'规则目标物体，用于测量空间位置关系'}],
            'relations':[{'source':'cup','type':'supported_by','target':'ground','description':'目标物体底面接触地面并稳定支撑'}]}
        plan = {'schema': 'spatialforge.assessment/v1', 'scenes': {
            'designs': [brief], 'geometry_exceptions': [declaration]}}
        self.plan = self.root / 'saved-plan.json'
        self.plan.write_text(json.dumps({'assessment': plan}), encoding='utf-8')
        self.program['provenance'] = {'sources': [{'kind': 'scene_plan', 'path': str(self.plan),
                                                  'scene_design_id': 'spatial-layout'}]}
        self.review['visual_realism']['status'] = 'matches_declared_geometry'
        self.save()
        return plan, declaration

    def test_saved_scoped_geometry_plan_passes_admission_review_and_expires_on_edit(self):
        self.declare_geometry()
        self.assertEqual(admit_program(self.artifacts, self.program)['scene_style'], 'simplified_geometry')
        from benchforge_core.pipelines.scene_policy import check_program
        check_program({'enabled': True}, self.program)
        receipt = self.assess()
        self.assertTrue(receipt['passed'], receipt['issues'])
        self.assertEqual(receipt['scene_style'], 'simplified_geometry')
        (self.directory / 'scene_acceptance.json').write_text(json.dumps(receipt))
        require_accepted(self.artifacts, self.directory)
        self.plan.write_text(self.plan.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'simplification changed'):
            require_accepted(self.artifacts, self.directory)

    def test_plan_claim_must_be_concrete_and_match_exact_scene_and_objects(self):
        plan, declaration = self.declare_geometry()
        for edits in ({'purpose': ''}, {'scene_id': 'another-scene'}, {'object_ids': ['undeclared']},
                      {'scene_design_id': 'another-design'}, {'reason': '待填写'}):
            proposal = copy.deepcopy(plan)
            proposal['scenes']['geometry_exceptions'][0].update(edits)
            self.plan.write_text(json.dumps(proposal))
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                admit_program(self.artifacts, self.program)
        self.plan.write_text(json.dumps(plan))
        plan['scenes']['geometry_exceptions'][0].update(purpose='测量尺度', reason='隔离变量')
        self.plan.write_text(json.dumps(plan))
        self.assertEqual(admit_program(self.artifacts, self.program)['scene_style'], 'simplified_geometry')
        extra = copy.deepcopy(self.program['objects'][0]);extra['id'] = 'extra';extra['xy'] = [1, 0]
        self.program['objects'].append(extra)
        with self.assertRaisesRegex(ValueError, 'scoped declaration'):
            admit_program(self.artifacts, self.program)
        from benchforge_core.pipelines.scene_policy import check_program
        with self.assertRaises(ValueError):check_program({'enabled': True}, self.program)

    def test_geometry_exception_keeps_physics_and_view_checks_and_cannot_claim_realism(self):
        self.declare_geometry()
        self.program['objects'][0]['base_z'] = 2
        with self.assertRaisesRegex(ValueError, 'floats'):admit_program(self.artifacts, self.program)
        self.program['objects'][0]['base_z'] = 0
        self.evidence['physics'] = {'stable': True}
        self.assertFalse(self.assess()['passed'])
        self.evidence['physics'] = {'stable': True, 'steps': 120, 'dt': 1 / 60}
        self.review['visual_realism']['status'] = 'visually_plausible'
        self.assertFalse(self.assess()['passed'])
        self.review['visual_realism']['status'] = 'matches_declared_geometry'
        (self.capture / 'view_0.png').unlink()
        self.assertFalse(self.assess()['passed'])

    def test_geometry_review_receives_the_saved_experiment_constraints(self):
        self.declare_geometry()
        store=Mock();store.root=self.artifacts;store.directory.return_value=self.directory;store.snapshot.return_value={'state':'RUNNING'}
        task={'id':'sf_test.scene0','run_id':'sf_test','unit':{'revision':0,'phase':'review','intent':{'capture_only':True}}}
        with patch.object(engine, 'completion', return_value=self.review) as reviewer:
            engine.review_scene(store, task, Event(), capture_only=True)
        prompt = str(reviewer.call_args)
        self.assertIn('去掉纹理和语义线索', prompt)
        self.assertIn('matches_declared_geometry', prompt)
        self.assertEqual(store.update.call_args.kwargs['state'], 'SUCCEEDED')

    def test_geometry_plan_does_not_reinstate_a_removed_source(self):
        self.declare_geometry()
        self.program['provenance']['sources'].append({'kind': 'original_scene', 'task_id': 'sf_removed.scene0'})
        policy = {'enabled': True, 'enforce_realism': True, 'excluded_tasks': ['sf_removed.scene0']}
        self.policy.write_text(json.dumps(policy))
        with self.assertRaisesRegex(ValueError, 'removed by the user'):
            admit_program(self.artifacts, self.program)
        from benchforge_core.pipelines.scene_policy import check_program
        with self.assertRaisesRegex(ValueError, 'removed by the user'):
            check_program(policy, self.program)

    def test_detailed_brief_requires_capture_alignment_and_cannot_silently_change(self):
        plan, _ = self.declare_geometry()
        design = plan['scenes']['designs'][0]
        design.update(name='规则几何空间实验', summary='这是一个隔离语义线索的空间关系实验。' * 14,
                      hard_requirements=['目标物体保持规则几何与正常支撑'],
                      physical_assumptions=['质量和摩擦使用未校准的合成先验'],
                      object_roles=[{'object_id':'cup','role':'需要测量位置的目标方块'}],
                      relations=[{'source':'cup','type':'supported_by','target':'ground','description':'目标方块的底部接触地面并保持稳定'}])
        self.plan.write_text(json.dumps(plan))
        self.policy.write_text(json.dumps({'enabled':True,'enforce_realism':True,'require_scene_brief':True}))
        self.review.pop('brief_alignment')
        self.assertFalse(self.assess()['passed'])
        self.review['brief_alignment']={'passed':True,'hard_requirements_preserved':True,'unresolved':[],
            'observations':[{'view':'view_0.png','observation':'实际目标规则方块稳定放置在地面上，符合实验声明。'}],
            'requirement_checks':[{'index':0,'passed':True,'view':'view_0.png','observation':'实际目标方块底部稳定接触地面。'}],
            'relation_checks':[{'index':0,'passed':True,'view':'view_0.png','observation':'实际目标方块底部稳定接触地面。'}]}
        receipt=self.assess();self.assertTrue(receipt['passed'],receipt['issues'])
        previous=self.directory/'prior';previous.mkdir()
        (previous/'scene_brief.json').write_text(json.dumps(design))
        (previous/'capture').mkdir()
        (previous/'capture/view_0.png').write_bytes(b'captured prior view')
        (previous/'capture/evidence.json').write_text(json.dumps({'physics':{'stable':True}}))
        design['previous_capture_directory']=str(previous)
        design['revision_history']=[{'revision':2,'changes':['补充真实视图中观察到的净空关系'], 'evidence_directory':str(previous),
            'unresolved':[],
            'evidence_refs':[{'path':'capture/view_0.png','observation':'实拍中桌沿与目标物之间留有可见净空。'},
                {'path':'capture/evidence.json','observation':'原生物理回执确认目标物保持稳定支撑。'}]}]
        design['hard_requirements']=['移除原始要求以掩盖现有缺陷']
        self.plan.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError,'preserve every original'):admit_program(self.artifacts,self.program)
        design['hard_requirements']=['目标物体保持规则几何与正常支撑']
        self.plan.write_text(json.dumps(plan))
        receipt=self.assess();self.assertTrue(receipt['passed'],receipt['issues'])
        (self.directory/'scene_acceptance.json').write_text(json.dumps(receipt))
        require_accepted(self.artifacts,self.directory)
        self.plan.write_text(self.plan.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'changed'):require_accepted(self.artifacts,self.directory)

    def test_static_attachment_needs_an_actual_native_target_connection(self):
        self.program['objects'][0]['base_z']=1
        wall=copy.deepcopy(self.program['objects'][0]);wall.update(id='wall_north',label='wall',kind='box',size=[2,.1,2],xy=[0,.1],base_z=0)
        self.program['objects'].append(wall)
        self.program['objects'][0]['metadata']={'spatial_attachment':{'method':'static_mount','target':'wall_north',
            'axis':1,'object_face':'max','target_face':'min'}}
        saved=json.loads(self.plan.read_text())
        saved['assessment']['scenes']['designs'][0]['relations']=[{'source':'cup','type':'mounted_to',
            'target':'wall_north','description':'陶杯固定在墙面支架上并保持稳定'}]
        self.plan.write_text(json.dumps(saved))
        self.evidence['entities']['cup']['world_aabb']={'min':[-.04,-.06,1],'max':[.04,.06,1.091]}
        self.evidence['entities']['wall_north']={'collision':{'paths':['/World/wall']},
            'world_aabb':{'min':[-1,.05,0],'max':[1,.15,2]}}
        self.assertTrue(self.assess()['passed'],self.assess()['issues'])
        self.evidence['entities']['cup']['world_aabb']={'min':[-.04,-1,1],'max':[.04,-.9,1.091]}
        self.assertTrue(any('no native connection' in issue for issue in self.assess()['issues']))

    def test_executed_shelf_parts_resolve_support_without_treating_hollow_envelope_as_solid(self):
        from spatialforge.scene_relations import native_part_bounds, supported_by_parts, overlap_unresolved
        entity={'world_transform':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,1,1]],
                'geometry_parts':{'source':'executed_primitive_construction','coordinate_frame':'entity_local_meters','parts':[
                    {'prim_path':'/World/shelf/board','shape':'box','size':[1,1,.1],'offset':[0,0,-.5]},
                    {'prim_path':'/World/shelf/side','shape':'box','size':[.1,1,2],'offset':[-.5,0,0]}]}}
        parts=native_part_bounds(entity)
        cup=([-.1,-.1,.55],[.1,.1,.8])
        self.assertTrue(supported_by_parts(cup,native_part_bounds(entity,support_only=True)))
        self.assertFalse(overlap_unresolved([cup],parts))
        penetrating=([-.1,-.1,.48],[.1,.1,.8])
        self.assertTrue(overlap_unresolved([penetrating],parts))
        entity['geometry_parts']['source']='declared_only'
        self.assertEqual(native_part_bounds(entity),[])

    def test_revision_cannot_drop_known_parent_or_omit_revision_evidence(self):
        from spatialforge.scene_design import require_prior_brief, validate_brief_revision
        previous=self.directory/'prior';previous.mkdir()
        (previous/'scene_brief.json').write_text(json.dumps({'hard_requirements':['保留用户要求的正常支撑关系']}))
        (previous/'capture').mkdir()
        (previous/'capture/view_0.png').write_bytes(b'captured prior view')
        (previous/'capture/evidence.json').write_text(json.dumps({'physics':{'stable':True}}))
        with self.assertRaisesRegex(ValueError,'frozen brief'):
            require_prior_brief({},previous)
        with self.assertRaisesRegex(ValueError,'previous captured evidence'):
            validate_brief_revision({'revision_history':[{'revision':2,'changes':['修改摆放']} ]},self.directory/'next-plan.json')
        brief={'hard_requirements':['保留用户要求的正常支撑关系'],'previous_capture_directory':str(previous),
               'revision_history':[{'revision':2,'changes':['依据实拍修复悬空'],'evidence_directory':str(previous),'unresolved':[],
                 'evidence_refs':[{'path':'capture/view_0.png','observation':'实拍中花盆底部与台面之间存在可见间隙。'},
                     {'path':'capture/evidence.json','observation':'物理回执记录花盆未形成有效支撑接触。'}]}]}
        require_prior_brief(brief,previous)
        validate_brief_revision(brief,self.directory/'next-plan.json')

    def test_brief_revision_requires_real_image_and_physics_receipt_references(self):
        from spatialforge.scene_design import validate_brief_revision
        previous=self.directory/'prior';previous.mkdir()
        (previous/'capture').mkdir()
        (previous/'capture/view_0.png').write_bytes(b'captured prior view')
        (previous/'capture/evidence.json').write_text(json.dumps({'physics':{'stable':True}}))
        brief={'hard_requirements':['保留正常支撑关系'],'previous_capture_directory':str(previous),
            'revision_history':[{'revision':1,'changes':['依照现有采集补充桌面净空关系'],'evidence_directory':str(previous),'unresolved':[],
                'evidence_refs':[{'path':'capture/view_0.png','observation':'实拍图中桌面边缘区域未留出足够操作空间。'},
                    {'path':'capture/evidence.json','observation':'原生物理记录确认物体底部稳定接触桌面。'}]}]}
        validate_brief_revision(brief,self.directory/'next-plan.json')
        brief.pop('previous_capture_directory')
        brief['revision_history'][0]['revision']=1
        validate_brief_revision(brief,self.directory/'next-plan.json')
        brief['previous_capture_directory']=str(previous)
        brief['revision_history'][0]['revision']=2
        brief['revision_history'][0]['evidence_refs'].pop()
        with self.assertRaisesRegex(ValueError,'native physical'):
            validate_brief_revision(brief,self.directory/'next-plan.json')
        brief['revision_history'][0]['evidence_refs']=[{'path':'capture/missing.png','observation':'实拍图中桌面边缘区域未留出足够操作空间。'},
            {'path':'capture/evidence.json','observation':'原生物理记录确认物体底部稳定接触桌面。'}]
        with self.assertRaisesRegex(ValueError,'saved prior artifact'):
            validate_brief_revision(brief,self.directory/'next-plan.json')

    def test_brief_revision_appends_history_and_records_unresolved_issues(self):
        from spatialforge.scene_design import validate_brief_revision
        previous=self.directory/'prior';(previous/'capture').mkdir(parents=True)
        (previous/'capture/view_0.png').write_bytes(b'captured prior view')
        (previous/'capture/evidence.json').write_text(json.dumps({'physics':{'stable':True}}))
        earlier={'revision':1,'changes':['按实拍补充工作台靠窗位置'],'unresolved':[],
                 'evidence_directory':str(previous)}
        (previous/'scene_brief.json').write_text(json.dumps({'hard_requirements':['保留安全通行空间'],
            'revision_history':[earlier]}))
        latest={'revision':2,'changes':['根据实拍调整椅子朝向并修正通路'],'unresolved':['尚未验证抽屉完全打开时与椅背的净空'],
            'evidence_directory':str(previous),'evidence_refs':[
                {'path':'capture/view_0.png','observation':'椅背转向工作台后，桌前通路保持连续。'},
                {'path':'capture/evidence.json','observation':'原生物理回执显示桌面物体在沉降后保持稳定支撑。'}]}
        brief={'hard_requirements':['保留安全通行空间'],'previous_capture_directory':str(previous),
               'revision_history':[earlier,latest]}
        validate_brief_revision(brief,self.directory/'next-plan.json')
        brief['revision_history']=[latest]
        with self.assertRaisesRegex(ValueError,'preserve earlier revision records'):
            validate_brief_revision(brief,self.directory/'next-plan.json')
        brief['revision_history']=[earlier,{**latest,'revision':1}]
        with self.assertRaisesRegex(ValueError,'advance beyond'):
            validate_brief_revision(brief,self.directory/'next-plan.json')
        brief['revision_history']=[earlier,{k:v for k,v in latest.items() if k!='unresolved'}]
        with self.assertRaisesRegex(ValueError,'unresolved issues'):
            validate_brief_revision(brief,self.directory/'next-plan.json')

    def test_interaction_needs_actual_matching_successful_receipts(self):
        self.program['interactions']=[{'id':'push','action':'apply_force','object_id':'cup','force_newtons':[1,0,0],
             'duration_steps':10,'observe_steps':60,'min_displacement_m':.001,'max_displacement_m':.5,
             'max_vertical_displacement_m':.1,'max_initial_speed_m_s':1,'max_final_speed_m_s':.2,'max_drift_m':.1}]
        self.assertTrue(any('native interaction' in s for s in self.assess()['physical_issues']))
        result={'id':'push','action':'apply_force','object_id':'cup','success':True,
                'trajectory_file':'trajectory.json','before_image':'before.png','after_image':'after.png'}
        self.evidence['interaction']={'validated':True,'action_results':[result]}
        for key in ('trajectory_file','before_image','after_image'):(self.capture/result[key]).write_text('fixture')
        self.assertFalse(any('native interaction' in s for s in self.assess()['physical_issues']))
        result['object_id']='different_object'
        self.assertTrue(any('native interaction' in s for s in self.assess()['physical_issues']))

    def test_valid_native_action_images_can_support_brief_observations(self):
        self.test_detailed_brief_requires_capture_alignment_and_cannot_silently_change()
        name='interaction_0_after.png';(self.capture/name).write_text('captured fixture')
        self.evidence['interaction']={'action_results':[{'after_image':name}]}
        self.review['brief_alignment']['observations'].append({'view':name,'observation':'动作后目标保持正常支撑姿态'})
        self.review['brief_alignment']['requirement_checks'][0]['view']=name
        self.assertTrue(self.assess()['passed'],self.assess()['issues'])
        self.review['brief_alignment']['requirement_checks'][0]['view']='invented_after.png'
        self.assertFalse(self.assess()['passed'])

    def test_source_vertices_and_native_pose_resolve_empty_bounding_corners_only(self):
        from spatialforge.scene_relations import transported_mesh_bounds
        mesh={'vertices':[[1,0,0],[0,1,0],[-1,0,0],[0,-1,0],[0,0,1]]}
        identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        entity={'id':'vessel','world_transform':identity,
                'world_transform_convention':'USD row-vector matrix; translation in last row; local to world meters'}
        dep={'entity_id':'vessel','embedded_geometry':True,'shape_preserved':True,'render_representation':'mesh',
             'vertices':5,'source_bounds':[[-1,-1,0],[1,1,1]],'T_local_from_source':identity}
        self.assertEqual(transported_mesh_bounds(entity,dep,mesh),([-1.,-1.,0.],[1.,1.,1.]))
        dep['vertices']=4;self.assertIsNone(transported_mesh_bounds(entity,dep,mesh))
        dep['vertices']=5;dep['embedded_geometry']=False
        self.assertIsNone(transported_mesh_bounds(entity,dep,mesh))
