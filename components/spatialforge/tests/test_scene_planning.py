"""Recovery tests for planner deltas and malformed model output."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from spatialforge import engine
from test_contracts import sample


class PlanningRecovery(unittest.TestCase):
    def test_operator_feedback_and_original_validation_survive_bad_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Store:
                root=Path(tmp)
                def directory(self,*args):return self.root
                def snapshot(self,*args):return {'state':'RUNNING'}
                def update(self,*args,**kwargs):pass
            raw=sample();raw['objects'][0].update(kind='mesh',parts=[],asset_id='asset_example',mesh_transform={'scale_mode':'none'})
            (Path(tmp)/'repair_seed.json').write_text(json.dumps(raw))
            task={'id':'scene','run_id':'run','attempt':0,'unit':{'revision':1,'intent':{},'operator_feedback':'Preserve layout and correct the imported pose using existing controls.'}}
            responses=[{'replacements':[{'path':'/objects/99/scale_mode','value':'uniform_fit'}]},
                       {'replacements':[{'path':'/objects/0/mesh_transform/scale_mode','value':'uniform_fit'}]}]
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',side_effect=responses) as model:
                tools.return_value.catalog.return_value=[]
                engine.plan_scene(Store(),task,threading.Event())
            self.assertEqual(model.call_count,2)
            prompt=model.call_args_list[1].args[0]
            self.assertIn(task['unit']['operator_feedback'],prompt)
            self.assertIn('mesh_transform.scale_mode',prompt)
            self.assertIn('"mesh_transform": {"scale_mode": "none"}',prompt)
            self.assertEqual(json.loads((Path(tmp)/'program.json').read_text())['objects'][0]['mesh_transform']['scale_mode'],'uniform_fit')
            preview=json.loads((Path(tmp)/'geometry_preview.json').read_text())
            self.assertEqual(preview['warnings'][0]['code'],'preview_incomplete')

    def test_portal_failure_retains_metadata_for_local_repair(self):
        raw=sample();raw['portals']=[{'id':'door','kind':'door','bounds':{'center':[0,0,1],'size':[1,.1,2]}}]
        prompt=engine.scene_repair_prompt(raw,'portal needs id, kind, position and size',{})
        self.assertIn(json.dumps(raw['portals']),prompt)
        self.assertIn('Current FULL scene proposal',prompt)
        self.assertIn('environment_id',prompt)

    def test_invalid_delta_feedback_stays_delta_and_then_merges_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            class Store:
                def __init__(self):self.root=root;self.updated=None
                def directory(self,tid,revision):
                    path=root/tid/str(revision);path.mkdir(parents=True,exist_ok=True);return path
                def snapshot(self,rid):return {'state':'RUNNING','tasks':[{'id':'parent.scene0','unit':{'intent':{'split':'dev'}}}]}
                def update(self,tid,**fields):self.updated=fields
            store=Store();base=sample();base['materials']=[{'id':'wood','name':'wood'}]
            (store.directory('parent.scene0',0)/'program.json').write_text(json.dumps(base))
            bad=sample();bad['objects'][0].update(id='prop',support='unknown_object',xy=[3,0])
            bad['cameras'][0]['target']=bad['cameras'][0]['position'][:]
            good=copy.deepcopy(bad);good['cameras'][0]['target']=[0,0,0]
            task={'id':'child.scene0','run_id':'child','attempt':0,'unit':{'revision':0,'intent':{'parent_task_id':'parent.scene0','parent_revision':0,'split':'dev'}}}
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',side_effect=[bad,good]) as model:
                tools.return_value.catalog.return_value=[]
                engine.plan_scene(store,task,threading.Event())
            self.assertEqual(store.updated['state'],'READY')
            self.assertEqual(len(bad['objects']),1)
            feedback=model.call_args_list[1].args[0]
            self.assertIn('"id": "prop"',feedback)
            self.assertNotIn('"id": "unknown_object"',feedback)
            self.assertEqual(model.call_args_list[1].args[3],49152)
            program=json.loads((store.directory('child.scene0',0)/'program.json').read_text())
            self.assertEqual(program['objects'][0],base['objects'][0]);self.assertEqual(program['materials'],base['materials'])
            self.assertIn('Computed initial geometry advice',feedback)
            self.assertIn('"object_id": "prop", "path": "/objects/0"',feedback)

    def test_malformed_model_json_is_repaired_with_a_finite_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Store:
                root=Path(tmp)
                def directory(self,*args):return self.root
                def snapshot(self,*args):return {'state':'RUNNING'}
                def update(self,*args,**kwargs):pass
            task={'id':'scene','run_id':'run','attempt':0,'unit':{'revision':0,'intent':{}}}
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',side_effect=ValueError('invalid JSON')) as model:
                tools.return_value.catalog.return_value=[]
                with self.assertRaisesRegex(ValueError,'exhausted 3 attempts'):engine.plan_scene(Store(),task,threading.Event())
            self.assertEqual(model.call_count,3)
            self.assertEqual(len(list(Path(tmp).glob('model_calls/scene_plan_*/validation_error.json'))),3)

    def test_seed_is_repaired_without_repeating_full_scene_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Store:
                root=Path(tmp)
                def directory(self,*args):return self.root
                def snapshot(self,*args):return {'state':'RUNNING'}
                def update(self,*args,**kwargs):pass
            raw=sample();raw['cameras'][0]['target']=raw['cameras'][0]['position'][:]
            (Path(tmp)/'repair_seed.json').write_text(json.dumps({'proposal':raw,'error':'degenerate camera'}))
            task={'id':'scene','run_id':'run','attempt':0,'unit':{'revision':0,'intent':{}}}
            edits={'replacements':[{'path':'/cameras/0/target','value':[0,0,0]}]}
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',return_value=edits) as model:
                tools.return_value.catalog.return_value=[]
                engine.plan_scene(Store(),task,threading.Event())
            self.assertEqual(model.call_count,1);self.assertEqual(model.call_args.args[3],49152)
            saved=json.loads((Path(tmp)/'program.json').read_text())
            self.assertEqual(saved['objects'],raw['objects']);self.assertEqual(saved['cameras'][0]['target'],[0,0,0])

    def test_complete_revision_and_field_additions_preserve_source(self):
        raw=sample();original=copy.deepcopy(raw)
        edits=[{'path':'/title','value':'revised'}]*20
        edits.append({'path':'/objects/0/appearance','value':{'roughness':.4}})
        edits.append({'path':'/assumptions/-','value':'new task assumption'})
        updated=engine.apply_scene_replacements(raw,{'replacements':edits})
        self.assertEqual(updated['objects'][0]['appearance'],{'roughness':.4})
        self.assertEqual(updated['assumptions'][-1],'new task assumption')
        replacement=engine.apply_scene_replacements(raw,{'replacements':[{'path':'','value':updated}]})
        self.assertEqual(replacement,updated)
        self.assertEqual(raw,original)


    def test_quality_feedback_patches_the_previous_program_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Store:
                root=Path(tmp)
                def directory(self,task,revision):
                    folder=self.root/str(revision);folder.mkdir(exist_ok=True);return folder
                def snapshot(self,*args):return {'state':'RUNNING'}
                def update(self,*args,**kwargs):pass
            store=Store();previous=store.directory('scene',0);raw=sample()
            raw['lights']=[{'id':'sky','kind':'environment','position':[0,0,2],'intensity':.55}]
            (previous/'program.json').write_text(json.dumps(raw))
            (previous/'scene_review.json').write_text(json.dumps({'acceptable':False,'issues':['render too dark']}))
            task={'id':'scene','run_id':'run','attempt':0,'unit':{'revision':1,'quality_repairs':1,'intent':{}}}
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',return_value={'replacements':[{'path':'/lights/0/intensity','value':400}]}) as model:
                tools.return_value.catalog.return_value=[]
                engine.plan_scene(store,task,threading.Event())
            self.assertEqual(model.call_count,1);self.assertEqual(model.call_args.args[3],49152)
            saved=json.loads((store.directory('scene',1)/'program.json').read_text())
            self.assertEqual(saved['objects'],raw['objects']);self.assertEqual(saved['lights'][0]['intensity'],400)
            self.assertEqual(json.loads((previous/'program.json').read_text())['lights'][0]['intensity'],.55)

    def test_refine_patches_full_source_preserves_family_and_does_not_spend_quality_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Store:
                root=Path(tmp)
                updated=None
                def directory(self,task,revision):
                    folder=self.root/task/str(revision);folder.mkdir(parents=True,exist_ok=True);return folder
                def snapshot(self,*args):return {'state':'RUNNING','tasks':[{'id':'source.scene0','unit':{'intent':{'split':'dev'}}}]}
                def update(self,*args,**kwargs):self.updated=kwargs
            store=Store();source=store.directory('source.scene0',2);original=sample()
            (source/'program.json').write_text(json.dumps(original));(source/'capture').mkdir()
            (source/'capture'/'view_0.png').write_bytes(b'image attached by mocked model')
            changed=copy.deepcopy(original['objects'][0]);changed['appearance']={'texture_id':'wood_laminate','uv_scale_m':[1,1]}
            task={'id':'refined.scene0','run_id':'refined','attempt':0,'unit':{'revision':0,'intent':{'refine_task_id':'source.scene0','refine_revision':2,'description':'Add wood laminate texture to unknown_object','split':'dev'}}}
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',return_value={'replacements':[{'path':'/objects/0','value':changed}]}) as model:
                tools.return_value.catalog.return_value=[];engine.plan_scene(store,task,threading.Event())
            self.assertEqual(model.call_count,1);self.assertEqual(model.call_args.args[3],49152)
            self.assertIn('FULL scene',model.call_args.args[0]);self.assertEqual(len(model.call_args.args[2]),1)
            self.assertNotIn('quality_repairs',store.updated['unit'])
            self.assertEqual(json.loads((source/'program.json').read_text()),original)
            saved=json.loads((store.directory('refined.scene0',0)/'program.json').read_text())
            self.assertEqual(saved['objects'][0],changed)
            task['unit']['intent']['split']='test'
            with patch.object(engine,'GenerationTools') as tools:
                tools.return_value.catalog.return_value=[]
                with self.assertRaisesRegex(ValueError,'split must be inherited'):engine.plan_scene(store,task,threading.Event())


if __name__=='__main__':unittest.main()
