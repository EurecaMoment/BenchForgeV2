"""Task-authored program handoff, using isolated SQL and no model/GPU calls."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from spatialforge import engine
from spatialforge.storage import Store,runs,tasks
from spatialforge.program_submission import read_program_submission,MAX_PROGRAM_BYTES
from spatialforge.service import start_scene_request,start_capture_request,refine_scene_request
from spatialforge.operator_evidence import evidence
from test_contracts import sample


class ProgramSubmission(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'deployment.local.json').write_text(json.dumps({'database_url':'sqlite:///'+str(self.root/'test.db')}))
        self.store=Store(self.root/'artifacts',self.root)
        transaction=self.store.repo.transaction
        @contextmanager
        def isolated_transaction():
            with transaction() as connection:
                class Connection:
                    def exec_driver_sql(self,sql):
                        if sql.startswith('SELECT pg_advisory_xact_lock'):return
                        return connection.exec_driver_sql(sql)
                    def execute(self,*args,**kwargs):return connection.execute(*args,**kwargs)
                yield Connection()
        self.store.repo.transaction=isolated_transaction
        self.path=self.store.root/'operator_workspaces/fixture/program.json';self.path.parent.mkdir(parents=True)
        self.program=sample();self.save(self.program)
        self.intent={'name':'handoff fixture','description':'Engineering data handoff only','split':'dev','target_items':1,'scene_program_path':str(self.path)}
        reference=self.path.parent/'reference.png';Image.new('RGB',(24,24),'tan').save(reference)
        self.intent['layout']={'mode':'reference','source_image':str(reference)}

    def tearDown(self):
        self.store.repo.engine.dispose();self.temp.cleanup()

    def save(self,p):self.path.write_text(json.dumps(p),encoding='utf8')
    def submit(self,key='handoff'):
        reply=start_scene_request(self.store,{'request_key':key,'intents':[self.intent]})
        return self.store.snapshot(reply['run_id'])['tasks'][0]
    def plan(self,task,**model_kw):
        with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'prepare_layout',return_value=None) as layout,patch.object(engine,'completion',**model_kw) as model:
            tools.return_value.catalog.return_value=[]
            engine.plan_scene(self.store,task,threading.Event())
            return model,tools,layout

    def test_invalid_files_rejected_before_submission(self):
        for raw in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}','[','{}',' '*(MAX_PROGRAM_BYTES+1)):
            with self.subTest(raw=raw[:35]):
                self.path.write_text(raw)
                with self.assertRaises(ValueError):self.submit()
        self.save(self.program)
        for path in (self.root/'outside.json',self.path.with_suffix('.py')):
            path.write_text(json.dumps(self.program))
            with self.assertRaisesRegex(ValueError,'inside an operator task workspace'):read_program_submission(self.store.root,str(path))
        outside=self.root/'outside.json'
        link=self.path.parent/'link.json'
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'inside an operator task workspace'):read_program_submission(self.store.root,str(link))
        self.assertEqual(self.store.all_work(),[])

    def test_missing_mesh_and_invalid_native_pose_rejected(self):
        p=deepcopy(self.program);p['objects'][0].update(kind='mesh',asset_id='missing_asset');self.save(p)
        with self.assertRaisesRegex(ValueError,'registered mesh unavailable'):self.submit()
        p['objects'][0].update(asset_id='office_chair',mesh_transform={'orientation_deg_xyz':[90,0,0]});self.save(p)
        with self.assertRaisesRegex(ValueError,'native asset aliases'):self.submit()
        self.assertEqual(self.store.all_work(),[])

    def test_invalid_appearance_vectors_locate_the_task_record(self):
        self.program['objects'][0]['appearance']={'texture_id':'wood_laminate','uv_scale_m':1}
        self.save(self.program)
        with self.assertRaisesRegex(ValueError,'object unknown_object /objects/0/appearance: invalid vector'):self.submit()

    def test_snapshot_survives_file_changes_and_idempotency_checks_content(self):
        task=self.submit();again=self.submit();self.assertEqual(task['id'],again['id'])
        self.program['title']='changed after acceptance';self.save(self.program)
        frozen=self.store.snapshot(task['run_id'])['tasks'][0]['unit']['submitted_program']['program']
        self.assertNotEqual(frozen['title'],self.program['title'])
        with self.assertRaisesRegex(ValueError,'different request'):self.submit()
        legacy={k:v for k,v in self.intent.items() if k!='scene_program_path'}
        run=self.store.submit('legacy',[legacy]);self.assertEqual(run,self.store.submit('legacy',[legacy]))
        self.assertNotIn('submitted_program',self.store.snapshot(run)['tasks'][0]['unit'])

    def test_first_pass_preserves_whole_program_skips_planner_and_catalog(self):
        # A large layout change cannot be represented by the old 16 replacement limit.
        for i in range(20):
            obj=deepcopy(self.program['objects'][0]);obj.update(id=f'object_{i}',xy=[(i%5)*1.5-3,(i//5)*1.5-2.25]);self.program['objects'].append(obj)
        self.save(self.program);task=self.submit()
        model,tools,layout=self.plan(task,side_effect=AssertionError('planner must not rewrite submitted data'))
        model.assert_not_called();tools.return_value.catalog.assert_not_called();layout.assert_called_once()
        directory=self.store.directory(task['id'],0)
        self.assertEqual(json.loads((directory/'program.json').read_text()),self.program)
        receipt=evidence(self.store,task['id'],0,'program_handoff.json')['data']
        self.assertTrue(receipt['exact_program_match']);self.assertEqual(receipt['prepared_object_count'],21)
        self.assertEqual(evidence(self.store,task['id'],0,'submitted_program.json')['data'],self.program)
        self.assertEqual(self.store.snapshot(task['run_id'])['tasks'][0]['state'],'READY')

    def test_native_normalization_retains_snapshot_and_explains_difference(self):
        self.program['objects'][0].update(kind='mesh',asset_id='office_chair');self.save(self.program);task=self.submit()
        self.plan(task,side_effect=AssertionError('unexpected planner'))
        receipt=evidence(self.store,task['id'],0,'program_handoff.json')['data']
        self.assertFalse(receipt['exact_program_match']);self.assertIn('kind',receipt['changed_objects'][0]['fields'])
        self.assertEqual(evidence(self.store,task['id'],0,'submitted_program.json')['data'],self.program)

    def test_refine_inherits_family_preserves_parent_and_rejects_active_source(self):
        parent=self.submit();directory=self.store.directory(parent['id'],0);(directory/'capture').mkdir()
        (directory/'capture/evidence.json').write_text('{}');(directory/'program.json').write_text(json.dumps(self.program))
        request={'request_key':'refined','parent_task_id':parent['id'],'name':'full layout replacement','description':'Use authored program','scene_program_path':str(self.path),'layout':self.intent['layout']}
        with self.assertRaisesRegex(ValueError,'still active'):refine_scene_request(self.store,request)
        with self.store.repo.transaction() as c:
            c.execute(runs.update().where(runs.c.id==parent['run_id']).values(state='SUCCEEDED'))
            c.execute(tasks.update().where(tasks.c.id==parent['id']).values(state='SUCCEEDED'))
        authored=deepcopy(self.program);authored['objects'][0]['xy']=[2,1];self.save(authored)
        reply=refine_scene_request(self.store,request);task=self.store.snapshot(reply['run_id'])['tasks'][0]
        self.assertEqual(task['unit']['intent']['scene_family'],parent['id']);self.assertEqual(reply['inherited_split'],'dev')
        self.assertEqual(task['unit']['intent']['target_items'],1)
        self.plan(task,side_effect=AssertionError('refine must use whole program'))
        self.assertEqual(json.loads((self.store.directory(task['id'],0)/'program.json').read_text()),authored)
        self.assertEqual(json.loads((directory/'program.json').read_text()),self.program)
        self.assertNotIn('quality_repairs',task['unit'])

    def test_refine_can_choose_earlier_capture_after_later_plan_failed(self):
        parent=self.submit();directory=self.store.directory(parent['id'],0);(directory/'capture').mkdir()
        (directory/'capture/evidence.json').write_text('{}');(directory/'program.json').write_text(json.dumps(self.program))
        unit={**parent['unit'],'revision':1,'phase':'plan'}
        with self.store.repo.transaction() as c:
            c.execute(runs.update().where(runs.c.id==parent['run_id']).values(state='FAILED_FINAL'))
            c.execute(tasks.update().where(tasks.c.id==parent['id']).values(state='FAILED_FINAL',unit=unit))
        request={'request_key':'earlier-capture','parent_task_id':parent['id'],'source_revision':0,'name':'revise capture','description':'Use earlier capture','scene_program_path':str(self.path),'layout':self.intent['layout']}
        reply=refine_scene_request(self.store,request)
        self.assertEqual(reply['source_revision'],0)
        self.assertEqual(self.store.snapshot(reply['run_id'])['tasks'][0]['unit']['intent']['refine_revision'],0)
        self.assertEqual(json.loads((directory/'program.json').read_text()),self.program)

    def test_refine_preserves_capture_scope_unless_data_target_is_explicit(self):
        result=start_capture_request(self.store,{'request_key':'capture-parent','scene_program_path':str(self.path)})
        parent=self.store.snapshot(result['run_id'])['tasks'][0]
        directory=self.store.directory(parent['id'],0);(directory/'capture').mkdir()
        (directory/'capture/evidence.json').write_text('{}')
        (directory/'program.json').write_text(json.dumps(self.program))
        self.store.update(parent['id'],state='SUCCEEDED',unit={**parent['unit'],'phase':'complete'})
        self.store.settle_runs()
        request={'request_key':'capture-refine','parent_task_id':parent['id'],'name':'new capture',
                 'description':'Improve materials','scene_program_path':str(self.path),'layout':self.intent['layout']}
        reply=refine_scene_request(self.store,request)
        child=self.store.snapshot(reply['run_id'])['tasks'][0]
        self.assertTrue(child['unit']['intent']['capture_only'])
        self.assertNotIn('target_items',child['unit']['intent'])
        self.assertEqual(reply['operation'],'capture_only')
        self.assertEqual(reply['task_id'],child['id'])
        self.plan(child,side_effect=AssertionError('authored capture must not invoke planner'))
        self.assertEqual(self.store.snapshot(reply['run_id'])['tasks'][0]['unit']['phase'],'capture')
        expanded=refine_scene_request(self.store,{**request,'request_key':'explicit-data','target_items':8})
        intent=self.store.snapshot(expanded['run_id'])['tasks'][0]['unit']['intent']
        self.assertNotIn('capture_only',intent)
        self.assertEqual(intent['target_items'],8)
        self.assertEqual(expanded['operation'],'scene_pipeline')

    def test_later_quality_repair_uses_previous_program_and_receipt(self):
        task=self.submit();self.plan(task)
        directory=self.store.directory(task['id'],0)
        # Previous realized data must be the seed, rather than resetting to submission.
        previous=deepcopy(self.program);previous['objects'][0]['xy']=[1,1]
        (directory/'program.json').write_text(json.dumps(previous));(directory/'scene_review.json').write_text('{"acceptable":false,"issues":["camera"]}')
        task['unit'].update(revision=1,quality_source_revision=0,quality_repairs=1)
        model,_,_=self.plan(task,return_value={'replacements':[{'path':'/cameras/0/position','value':[2,-3,2]}]})
        self.assertEqual(model.call_count,1)
        p=json.loads((self.store.directory(task['id'],1)/'program.json').read_text())
        self.assertEqual(p['objects'],previous['objects']);self.assertEqual(p['cameras'][0]['position'],[2,-3,2])
        receipt=evidence(self.store,task['id'],1,'program_handoff.json')['data']
        self.assertFalse(receipt['exact_program_match']);self.assertIn('cameras',receipt['changed_sections'])
        self.assertEqual(task['unit']['quality_repairs'],1)

    def test_generated_assets_still_realized_without_mutating_submission(self):
        generation={'prompt':'a small reusable bowl','label':'bowl','source_image':'/task/reference.png',
                    'source_mask':'/task/mask.png','subject_box':[10,20,200,180],'seed':17,'edit_reference':False}
        self.program['objects'][0].update(kind='generated',generation=generation);self.save(self.program)
        task=self.submit()
        with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'prepare_layout',return_value=None),patch.object(engine,'completion',side_effect=AssertionError('unexpected planner')),patch.object(engine,'review_generated_asset',return_value={'asset_id':'asset_fixture'}):
            tools.return_value.generate_asset.return_value={'asset_id':'asset_fixture'}
            engine.plan_scene(self.store,task,threading.Event())
            tools.return_value.generate_asset.assert_called_once()
            self.assertEqual(tools.return_value.generate_asset.call_args.args[0],
                             {'size_hint_m':self.program['objects'][0]['size'],**generation})
        self.assertEqual(task['unit']['submitted_program']['program']['objects'][0]['kind'],'generated')
        self.assertEqual(task['unit']['submitted_program']['program']['objects'][0]['generation'],generation)
        p=json.loads((self.store.directory(task['id'],0)/'program.json').read_text())
        self.assertEqual(p['objects'][0]['kind'],'mesh')


if __name__=='__main__':unittest.main()
