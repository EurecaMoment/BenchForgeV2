"""No action is not a successful action; requested actions still need receipts."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from spatialforge import engine
from spatialforge.observation import quality_outcome
from test_contracts import sample


class InteractionOutcome(unittest.TestCase):
    def test_review_distinguishes_not_requested_failed_and_executed(self):
        for requested, validated, receipt, expected in (
            (False, False, False, None),
            (True, False, True, False),
            (True, True, False, False),
            (True, True, True, True),
        ):
            with self.subTest(requested=requested, validated=validated, receipt=receipt), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);capture=root/'capture';capture.mkdir()
                program=sample()
                action={'id':'push','action':'apply_force','object_id':program['objects'][0]['id']}
                program['interactions']=[action] if requested else []
                (root/'program.json').write_text(json.dumps(program))
                (capture/'report.json').write_text(json.dumps({'status':'captured','token':'actual_capture','renderable':True,'physics':{'stable':True}}))
                changes={'source_revision':'revision_0','target_revision':1,'capture_status':'not_yet_captured','scene_changes':{}}
                changes_text=json.dumps(changes)
                (root/'repair_changes.json').write_text(changes_text)
                result={**action,'success':validated,'trajectory_file':'trace.json','before_image':'before.png','after_image':'after.png'}
                interaction={'validated':validated,'action_results':[result] if requested else []}
                if not requested:interaction['reason']='no executable interaction requested'
                if receipt:
                    for name in ('trace.json','before.png','after.png'):(capture/name).write_bytes(b'fixture')
                physical={'mass_kg':6,'static_friction':.6,'dynamic_friction':.5,'mass_source':'synthetic_prior','calibrated':False}
                collision={'origin':'asset_native','paths':['/World/Objects/toolbox/Collider'],'calibrated':False}
                entity={'id':'toolbox','prim_path':'/World/Objects/toolbox','physics':physical,'collision':collision}
                materials=[{'prim_path':'/World/Objects/bench/part0','texture_id':'wood_laminate'},
                           {'prim_path':'/World/Objects/bench/part1','texture_id':'wood_laminate'}]
                (capture/'evidence.json').write_text(json.dumps({'origin':'isaac_native','interaction':interaction,
                    'entities':{'toolbox':entity},'material_dependencies':materials}))
                (capture/'view_0.png').write_bytes(b'fixture')
                (root/'layout_reference.png').write_bytes(b'fixture')
                class Store:
                    def directory(self,*args):return root
                    def snapshot(self,*args):return {'state':'CANCELED'}
                    def update(self,*args,**kwargs):pass
                task={'id':'scene','run_id':'run','unit':{'revision':0,'intent':{}}}
                with patch.object(engine,'completion',return_value={'acceptable':True}) as reviewer:
                    engine.review_scene(Store(),task,threading.Event())
                expected_images=['view_0.png']+(['before.png','after.png'] if requested and receipt else [])+['layout_reference.png']
                self.assertEqual([path.name for path in reviewer.call_args.args[2]],expected_images)
                self.assertIn('当前是采集后的场景审查，数据生成和打包尚未执行',reviewer.call_args.args[0])
                self.assertIn('target_items 是后续题目导出目标',reviewer.call_args.args[0])
                for name in expected_images[:-1]:self.assertIn(name,reviewer.call_args.args[0])
                for receipt in (physical,collision,*materials):self.assertIn(json.dumps(receipt,ensure_ascii=False),reviewer.call_args.args[0])
                delivered_changes=json.loads(reviewer.call_args.args[0].split('\n本次程序改动对照：',1)[1].split('\n',1)[0])
                self.assertEqual(delivered_changes,{**changes,'comparison_recorded_at':'before_capture','capture_status':'captured','capture_token':'actual_capture'})
                self.assertEqual((root/'repair_changes.json').read_text(),changes_text)
                review=json.loads((root/'scene_review.json').read_text())
                self.assertIs(review['interaction_passed'],expected)
                self.assertIs(review['interaction_requested'],requested)
                self.assertIs(review['passed'],expected is not False)

    def test_legacy_static_report_is_explained_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original=json.dumps({'passed':True,'interaction_passed':True,'interaction':{
                'validated':False,'action_results':[],'reason':'no executable interaction requested'}})
            path=root/'scene_review.json';path.write_text(original)
            quality=quality_outcome(root,{'scene_quality_passed':True})
            self.assertIsNone(quality['interaction_passed'])
            self.assertEqual(quality['interaction_status'],'not_requested')
            self.assertEqual(path.read_text(),original)


if __name__=='__main__':unittest.main()
