import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from benchforge_core.stage_review import review
from benchforge_core.pipelines.runner import run
from benchforge_core.runtime import write


class StageReviewTests(unittest.TestCase):
    def test_deadline_survives_reopening_and_expires_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=review(tmp,'session-one','open',stage='S1',key='plan-v1',artifact='plan.json',now=1000)
            reopened=review(tmp,'session-one','open',stage='S1',key='plan-v1',artifact='plan.json',now=1100)
            self.assertEqual(first['review_id'],reopened['review_id'])
            self.assertEqual(reopened['deadline'],1300)
            self.assertFalse(review(tmp,'session-one',now=1299)['can_continue'])
            self.assertTrue(review(tmp,'session-one',now=1300)['can_continue'])
            self.assertEqual(review(tmp,'session-one',now=1400)['state'],'elapsed')

    def test_user_instruction_and_pause_prevent_timeout_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=review(tmp,'session-one','open',stage='S3',key='annotations-v1',artifact='annotations.json',now=1000)
            review(tmp,'session-one','pause',review_id=first['review_id'],now=1050)
            self.assertFalse(review(tmp,'session-one',now=1500)['can_continue'])
            review(tmp,'session-one','instruction',review_id=first['review_id'],instruction='改变相机位置',now=1501)
            result=review(tmp,'session-one',now=2000)
            self.assertEqual(result['instruction'],'改变相机位置')
            self.assertEqual(result['state'],'needs_input')
            self.assertFalse(result['can_continue'])
            with self.assertRaises(ValueError):
                review(tmp,'session-two','continue',review_id=first['review_id'])

    def test_runner_blocks_each_stage_and_preserves_completed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            plan=root/'plan.json'
            write(plan,{'inputs':{},'steps':[{'id':stage,'uses':'test.operation','review_stage':stage} for stage in ('S2','S3','S4','S5')]})
            args={'plan':str(plan),'run':str(root/'run'),'_workspace':tmp,'_dsh_context':{'session_id':'session-one'}}
            calls=[]
            def execute(step,*unused):
                calls.append(step['id'])
                return {'state':'completed','artifact':'saved'}
            with patch('benchforge_core.pipelines.runner.execute_step',side_effect=execute):
                for stage in ('S1','S2','S3','S4','S5'):
                    result=run(args,root/'operation')
                    self.assertEqual(result['state'],'waiting_user')
                    self.assertEqual(result['stage_review']['stage'],stage)
                    before=list(calls)
                    self.assertEqual(run(args,root/'operation')['state'],'waiting_user')
                    self.assertEqual(calls,before)
                    review(tmp,'session-one','continue',review_id=result['stage_review']['review_id'])
                self.assertEqual(run(args,root/'operation')['state'],'completed')
                self.assertEqual(calls,['S2','S3','S4','S5'])
                self.assertEqual(run(args,root/'operation')['state'],'completed')
                self.assertEqual(calls,['S2','S3','S4','S5'])


if __name__=='__main__': unittest.main()
