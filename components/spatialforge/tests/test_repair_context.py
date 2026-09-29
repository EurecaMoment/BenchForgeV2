import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from spatialforge.repair_context import build_repair_context,bound_repair_context,scene_changes
from spatialforge.operator_evidence import _allowed
from spatialforge import engine
from test_contracts import sample


class RepairContextTests(unittest.TestCase):
    def test_design_attachment_append_rebounds_details_and_preserves_manifest(self):
        rows=[{'state':'x'*950} for _ in range(30)]
        context={'attachment_manifest':[], 'current_execution':{'entities':rows,'omitted_entities':0}}
        bound_repair_context(context)
        # Fill the remaining budget to reproduce a final design append crossing it.
        remaining=24000-len(json.dumps(context,ensure_ascii=False))-20
        context['padding']='p'*max(0,remaining)
        manifest=[{'attachment_index':1,'role':'design_reference_only','path':'/design/'+'r'*150+'.png'}]
        context['attachment_manifest']=manifest
        self.assertGreater(len(json.dumps(context,ensure_ascii=False)),24000)
        before=context['current_execution']['omitted_entities']
        bound_repair_context(context)
        self.assertLessEqual(len(json.dumps(context,ensure_ascii=False)),24000)
        self.assertEqual(context['attachment_manifest'],manifest)
        self.assertGreater(context['current_execution']['omitted_entities'],before)

    def make_revision(self, root, number, angle, count=5):
        folder=root/f'revision_{number}';(folder/'capture').mkdir(parents=True)
        program=sample();program['objects'][0].update(id='pot',kind='mesh',asset_id='asset_example',parts=[],mesh_transform={'orientation_deg_xyz':[angle,0,0],'scale_mode':'uniform_fit'})
        (folder/'program.json').write_text(json.dumps(program))
        (folder/'scene_review.json').write_text(json.dumps({'passed':False,'issues':['Inspect pot in view_3 and view_4, also missing view_99'],'repair_suggestions':['Compare view_3 carefully']}))
        (folder/'capture/evidence.json').write_text(json.dumps({'origin':'isaac_native','entities':{'pot':{'world_aabb':{'min':[0,0,.33],'max':[1,1,.44]}}},'asset_dependencies':[{'entity_id':'pot','orientation_deg_xyz':[angle,0,0],'texture_sampling':'vertex_color_fallback'}]}))
        for i in range(count):Image.new('RGB',(8,8),(i*20,10,10)).save(folder/'capture'/f'view_{i}.png')
        return folder,program

    def test_referenced_close_view_included_and_previous_images_explicitly_labeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);older,_=self.make_revision(root,0,180);current,_=self.make_revision(root,1,0)
            original=(current/'program.json').read_bytes()
            context,images=build_repair_context(current,older)
            self.assertEqual(len(images),7)
            self.assertEqual(images[0].name,'view_3.png')
            self.assertEqual({p.name for p in images[:5]},{f'view_{i}.png' for i in range(5)})
            self.assertEqual(context['attachment_manifest'][5]['role'],'previous_capture')
            self.assertEqual(context['attachment_manifest'][5]['attachment_index'],6)
            self.assertEqual(context['missing_review_views'],['view_99'])
            self.assertEqual(context['changes_into_current']['changes'][0]['field'],'mesh_transform')
            self.assertEqual(context['current_execution']['entities'][0]['state']['world_aabb']['min'][2],.33)
            self.assertEqual((current/'program.json').read_bytes(),original)

    def test_id_matching_and_reversal_are_advice_not_pose_enforcement(self):
        older={'objects':[{'id':'a','mesh_transform':{'orientation_deg_xyz':[180,0,0]}},{'id':'b','size':[1,1,1]}]}
        before=copy.deepcopy(older);before['objects'][0]['mesh_transform']['orientation_deg_xyz']=[0,0,0]
        after=copy.deepcopy(older);after['objects'].reverse()
        result=scene_changes(before,after,older)
        self.assertEqual(result['total_changes'],1)
        self.assertEqual(result['changes'][0]['object_id'],'a')
        self.assertTrue(result['changes'][0]['returns_to_earlier_value'])
        self.assertEqual(result['reversal_count'],1)
        self.assertEqual(scene_changes(older,after)['total_changes'],0)

    def test_feedback_size_and_file_access_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_=self.make_revision(root,0,0,10)
            entities={f'object_{i}':{'world_aabb':{'min':[0,0,0],'max':[1,1,1]}} for i in range(200)}
            (folder/'capture/evidence.json').write_text(json.dumps({'origin':'isaac_native','entities':entities}))
            context,images=build_repair_context(folder)
            self.assertLessEqual(len(images),6);self.assertLessEqual(len(json.dumps(context,ensure_ascii=False)),24000)
            self.assertGreater(context['current_execution']['omitted_entities'],0)
            self.assertTrue(_allowed('repair_context.json'));self.assertTrue(_allowed('repair_changes.json'))
            self.assertFalse(_allowed('release/authority_bundle.zip'))
        before={'objects':[{'id':str(i),'appearance':{'value':'a'*600}} for i in range(100)]}
        after={'objects':[{'id':str(i),'appearance':{'value':'b'*600}} for i in range(100)]}
        diff=scene_changes(before,after)
        self.assertLessEqual(len(json.dumps(diff,ensure_ascii=False)),16000)
        self.assertGreater(diff['omitted_changes'],0)

    def test_pipeline_delivers_receipts_and_keeps_model_chosen_reversal_without_extra_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);older,_=self.make_revision(root,0,180);current,_=self.make_revision(root,1,0)
            class Store:
                def __init__(self):self.root=root;self.updated=None
                def directory(self,tid,rev):
                    path=root/f'revision_{rev}';path.mkdir(exist_ok=True);return path
                def snapshot(self,*args):return {'state':'RUNNING'}
                def update(self,tid,**kwargs):self.updated=kwargs
            store=Store();task={'id':'scene','run_id':'run','attempt':0,'unit':{'revision':2,'quality_repairs':2,'quality_source_revision':1,'intent':{}}}
            edits={'replacements':[{'path':'/objects/0/mesh_transform/orientation_deg_xyz','value':[180,0,0]}]}
            with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',return_value=edits) as model:
                tools.return_value.catalog.return_value=[]
                engine.plan_scene(store,task,threading.Event())
            self.assertEqual(model.call_count,1)
            prompt=model.call_args.args[0];images=model.call_args.args[2]
            self.assertIn('"current_capture"',prompt);self.assertIn('"previous_capture"',prompt)
            self.assertIn('"min": [0, 0, 0.33]',prompt)
            self.assertEqual(len(images),7);self.assertIn(current/'capture/view_3.png',images)
            changes=json.loads((root/'revision_2/repair_changes.json').read_text())
            self.assertEqual(changes['scene_changes']['reversal_count'],1)
            self.assertEqual(store.updated['unit']['quality_repairs'],2)
            self.assertEqual(store.updated['state'],'READY')
            self.assertEqual(json.loads((current/'program.json').read_text())['objects'][0]['mesh_transform']['orientation_deg_xyz'],[0,0,0])


if __name__=='__main__':unittest.main()
