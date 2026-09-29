"""Submitted scenes return to their operator without a competing repair planner."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from spatialforge import engine
from test_contracts import sample


class OperatorReviewControl(unittest.TestCase):
    def review(self, submitted, repairs=0, acceptable=False, action_ok=False, renderable=True, canceled=False):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);capture=root/'capture';capture.mkdir()
        program=sample();action={'id':'push','action':'apply_force','object_id':program['objects'][0]['id']}
        program['interactions']=[action]
        (root/'program.json').write_text(json.dumps(program))
        (capture/'report.json').write_text(json.dumps({'status':'captured','renderable':renderable,'physics':{'stable':True}}))
        for name in ('trace.json','before.png','after.png'):(capture/name).write_bytes(b'fixture')
        evidence={'origin':'isaac_native','interaction':{'validated':action_ok,'action_results':[
            {**action,'success':action_ok,'trajectory_file':'trace.json','before_image':'before.png','after_image':'after.png'}]}}
        (capture/'evidence.json').write_text(json.dumps(evidence))
        unit={'revision':0,'intent':{'split':'train','target_items':1},'quality_repairs':repairs}
        if submitted:unit['submitted_program']={'program':deepcopy(program)}
        class Store:
            changes=[]
            def directory(self,*args):return root
            def snapshot(self,*args):return {'state':'CANCELED' if canceled else 'RUNNING'}
            def update(self,task_id,**changes):self.changes.append(changes)
        store=Store()
        def export(directory,split,intent):
            review=json.loads((directory/'scene_review.json').read_text())
            self.assertEqual(review['passed'],acceptable and action_ok and renderable)
            self.assertEqual(review['interaction_passed'],action_ok)
            self.assertEqual(json.loads((directory/'program.json').read_text()),program)
            self.assertEqual(json.loads((capture/'evidence.json').read_text()),evidence)
            return {'accepted':1,'scene_quality_passed':review['passed'],'publication_status':review['publication_status']}
        with patch.object(engine,'completion',return_value={'acceptable':acceptable,'issues':['fixture review']}) as model, patch.object(engine,'produce',side_effect=export) as produce:
            engine.review_scene(store,{'id':'task','run_id':'run','unit':unit},threading.Event())
        return store.changes,produce.call_count,model.call_count

    def test_authored_review_exports_without_replanning_and_preserves_failed_quality(self):
        for acceptable,action_ok in [(False,True),(True,False),(True,True)]:
            with self.subTest(acceptable=acceptable,action_ok=action_ok):
                changes,exports,calls=self.review(True,acceptable=acceptable,action_ok=action_ok)
                self.assertEqual((exports,calls),(1,1))
                final=changes[-1];self.assertEqual(final['unit']['revision'],0)
                self.assertEqual(final['unit']['quality_repairs'],0)
                self.assertEqual(final['unit']['phase'],'complete')
                self.assertEqual(final['result']['summary']['scene_quality_passed'],acceptable and action_ok)
                self.assertEqual(final['result']['summary']['publication_status'],'pilot_candidate' if acceptable and action_ok else 'exploration_requires_improvement')

    def test_text_request_keeps_existing_two_repair_rounds(self):
        for repairs in (0,1,2):
            with self.subTest(repairs=repairs):
                changes,exports,_=self.review(False,repairs=repairs)
                self.assertEqual(exports,1 if repairs==2 else 0)
                if repairs<2:
                    self.assertEqual(changes[-1]['unit']['phase'],'plan')
                    self.assertEqual(changes[-1]['unit']['quality_repairs'],repairs+1)

    def test_authored_unrenderable_capture_and_cancellation_do_not_export(self):
        changes,exports,_=self.review(True,renderable=False)
        self.assertEqual(exports,0);self.assertEqual(changes[-1]['state'],'FAILED_FINAL')
        self.assertEqual(changes[-1]['failure']['next_action'],'engineering_recovery')
        changes,exports,_=self.review(True,canceled=True)
        self.assertEqual(exports,0);self.assertEqual(changes,[])


if __name__=='__main__':unittest.main()
