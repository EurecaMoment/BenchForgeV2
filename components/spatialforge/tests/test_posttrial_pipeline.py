import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from spatialforge import engine
from spatialforge.contracts import validate_program,part_contract_errors
from spatialforge.layout import default_layout,validate_layout
from spatialforge.operator_evidence import evidence
from spatialforge.scene_quality import audit_scene
from test_contracts import sample


class PostTrialPipeline(unittest.TestCase):
    def test_large_simulator_array_can_be_copied_without_inline_expansion(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def snapshot(self,rid):return {'tasks':[{'id':rid+'.scene0','state':'SUCCEEDED','unit':{'revision':0}}]}
            store=Store();capture=store.root/'sf_large.scene0/revision_0/capture';capture.mkdir(parents=True)
            source=capture/'view_0_depth.npy'
            with source.open('wb') as f:f.truncate(17*1024*1024)
            result=evidence(store,'sf_large.scene0',0,'capture/view_0_depth.npy','inspect_depth')
            self.assertEqual(Path(result['source_path']).stat().st_size,source.stat().st_size)
            self.assertNotIn('data',result)

    def test_kind_parts_feedback_identifies_each_object_and_atomic_repair(self):
        raw=sample();part={'shape':'sphere','size':[.03]*3,'offset':[0]*3,'color':[0,1,0]}
        raw['objects'][0].update(kind='office_plant',parts=[part])
        second=copy.deepcopy(raw['objects'][0]);second.update(id='empty_composite',kind='composite',parts=[]);raw['objects'].append(second)
        errors=part_contract_errors(raw);self.assertEqual(len(errors),2)
        with self.assertRaises(ValueError) as error:validate_program(raw)
        self.assertIn('/objects/0',str(error.exception));self.assertIn('/objects/1',str(error.exception))
        prompt=engine.scene_repair_prompt(raw,str(error.exception),{})
        self.assertIn('"parts": [{"shape": "sphere"',prompt)
        self.assertIn('complete SceneProgram',prompt)
        fixed=copy.deepcopy(raw);fixed['objects'][0]['parts']=[];fixed['objects'][1]['kind']='box'
        validate_program(fixed)
        self.assertTrue(raw['objects'][0]['parts'])

    def test_failed_action_is_recorded_evidence_without_publication_credit(self):
        action={'before':{'position':[0,0,0]},'after':{'position':[0,0,0]},'sample_count':121,'trajectory_file':'interaction_0_trajectory.json','success':False}
        captured={'renderable':True,'views':[{}],'geometry':{'valid':True},'physics':{'stable':True},'segmentation':{'authority':'simulator'},'interaction':{'validated':False,'action_results':[action]}}
        result=audit_scene(sample(),captured)
        self.assertEqual(result['dimensions']['interaction']['evidence_level'],'observed')
        self.assertNotEqual(result['tier'],'publishable_candidate')
        self.assertIn('1 failed',result['dimensions']['interaction']['observations'][-1])

    def test_prior_evidence_access_and_copy_protect_production_and_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def snapshot(self,rid):return {'state':'FAILED_FINAL','tasks':[{'id':rid+'.scene0','state':'FAILED_FINAL','unit':{'revision':2}}]}
            store=Store();base=store.root/'sf_test.scene0';capture=base/'revision_0/capture';capture.mkdir(parents=True);(base/'revision_2').mkdir()
            (capture/'report.json').write_text(json.dumps({'interaction':{'validated':False,'action_results':[{'status':'failed','success':False}]}}))
            (base/'revision_0/geometry_preview.json').write_text(json.dumps({'authority':'program/source geometry advice; not simulation GT','warnings':[]}))
            (base/'revision_0/data_selection.json').write_text(json.dumps({'state':'candidate_pool_exhausted','shortfall':1,'gt_modified':False}))
            Image.new('RGB',(24,24)).save(capture/'view_0.png')
            listing=evidence(store,'sf_test.scene0')
            self.assertEqual(listing['revisions'][0]['captured_views'],1)
            self.assertFalse(listing['revisions'][0]['released'])
            self.assertIn('not simulation GT',evidence(store,'sf_test.scene0',0,'geometry_preview.json')['data']['authority'])
            self.assertEqual(evidence(store,'sf_test.scene0',0,'data_selection.json')['data']['shortfall'],1)
            self.assertIn('data_selection.json',[f['file'] for f in listing['revisions'][0]['files']])
            copied=evidence(store,'sf_test.scene0',0,'capture/report.json','diagnose')
            Path(copied['source_path']).write_text('modified task copy')
            self.assertIn('interaction',(capture/'report.json').read_text())
            for file in ('release/authority_bundle.zip','../service.local.json','capture/../../secret.json'):
                with self.assertRaises(ValueError):evidence(store,'sf_test.scene0',0,file)
            self.assertTrue(evidence(store,'sf_test.scene0',0,'capture/view_0.png')['image_path'].endswith('view_0.png'))

    def test_pipeline_reference_default_and_render_comparison(self):
        design=default_layout({'description':'A realistic garden workshop with 8 dev questions'})
        validate_layout(design);self.assertEqual(design['mode'],'generate');self.assertIn('Real interior architectural photograph',design['prompt'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);capture=root/'capture';capture.mkdir()
            (root/'program.json').write_text(json.dumps(sample()))
            from spatialforge.geometry_preview import preview_scene_geometry
            (root/'geometry_preview.json').write_text(json.dumps(preview_scene_geometry(sample())))
            (capture/'report.json').write_text(json.dumps({'status':'captured','renderable':True,'physics':{'stable':True}}))
            (capture/'evidence.json').write_text(json.dumps({'origin':'isaac_native','asset_dependencies':[{'entity_id':'window','appearance_overrides':[{'source_material':'MI_Window_glass','applied':[],'skipped':[{'field':'roughness','reason':'unsupported native shader parameter; original preserved'}]}]}]}))
            Image.new('RGB',(32,24),'green').save(root/'layout_reference.png');Image.new('RGB',(32,24),'gray').save(capture/'view_0.png')
            class Store:
                def directory(self,*args):return root
                def snapshot(self,*args):return {'state':'CANCELED'}
                def update(self,*args,**kwargs):pass
            task={'id':'scene','run_id':'run','unit':{'revision':0,'intent':{'target_items':8}}}
            with patch.object(engine,'completion',return_value={'acceptable':True}) as model:
                engine.review_scene(Store(),task,threading.Event())
            images=model.call_args.args[2]
            self.assertEqual(images,[capture/'view_0.png',root/'layout_reference.png'])
            self.assertIn('design_alignment',model.call_args.args[0])
            self.assertIn('MI_Window_glass',model.call_args.args[0])
            self.assertIn('unsupported native shader parameter; original preserved',model.call_args.args[0])
            self.assertIn('仿真前的程序几何建议',model.call_args.args[0])

if __name__=='__main__':unittest.main()
