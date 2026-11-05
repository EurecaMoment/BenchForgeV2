import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from benchforge_core.stage_review import review
from benchforge_core.pipelines.runner import run
from benchforge_core.pipelines.plan_versions import activate
from benchforge_core.runtime import read, write


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

    def test_nested_captures_share_one_completed_scene_review_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root/'plan.json'
            write(plan, {'inputs': {}, 'steps': [
                {'id': name, 'uses': 'pipeline', 'pipeline_id': 'scene.capture',
                 'arguments': {'scene_program_path': name+'.json', 'service_config': 'fixture.json'}}
                for name in ('kitchen', 'office', 'bedroom')]})
            args = {'plan': str(plan), 'run': str(root/'run'), '_workspace': tmp,
                    '_dsh_context': {'session_id': 'session-one'}}
            calls = []
            ready = False

            def client(route, arguments, config):
                calls.append((route, dict(arguments)))
                if route == '/capture':
                    return {'run_id': arguments['scene_program_path'], 'state': 'RUNNING'}
                return {'run_id': arguments['run_id'], 'state': 'SUCCEEDED' if ready else 'RUNNING',
                        'capture': arguments['run_id']+'.png'}

            first = run(args, root/'operation', client=client)
            self.assertEqual(first['stage_review']['stage'], 'S1')
            review(tmp, 'session-one', 'continue', review_id=first['stage_review']['review_id'])
            pending = run(args, root/'operation', client=client)
            self.assertEqual(pending['state'], 'waiting')
            self.assertEqual(sum(route == '/capture' for route, _ in calls), 1)
            ready = True
            scenes = run(args, root/'operation', client=client)
            self.assertEqual(scenes['state'], 'waiting_user')
            self.assertEqual(scenes['stage_review']['stage'], 'S2')
            self.assertEqual(sum(route == '/capture' for route, _ in calls), 3)
            summary = read(scenes['stage_review']['artifact'])
            completed = [item['result']['capture'] for item in summary['outputs']
                         if item['result'].get('state') == 'SUCCEEDED']
            self.assertEqual(completed, ['kitchen.json.png', 'office.json.png', 'bedroom.json.png'])
            self.assertTrue(all(Path(item['result_path']).is_file() for item in summary['outputs']))
            before = list(calls)
            review(tmp, 'session-one', 'pause', review_id=scenes['stage_review']['review_id'])
            self.assertEqual(run(args, root/'operation', client=client)['state'], 'paused')
            self.assertEqual(calls, before)
            review(tmp, 'session-one', 'continue', review_id=scenes['stage_review']['review_id'])
            self.assertEqual(run(args, root/'operation', client=client)['state'], 'completed')
            self.assertEqual(run(args, root/'operation', client=client)['state'], 'completed')
            self.assertEqual(calls, before)
            with closing(sqlite3.connect(root/'stage-reviews.sqlite')) as db:
                stages = db.execute('SELECT stage,COUNT(*) FROM reviews GROUP BY stage').fetchall()
            self.assertEqual(dict(stages), {'S1': 1, 'S2': 1})

    def test_same_stage_artifacts_are_aggregated_across_unclassified_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root/'plan.json'
            write(plan, {'inputs': {}, 'steps': [
                {'id': 'first-scene', 'uses': 'fixture', 'review_stage': 'S2'},
                {'id': 'helper', 'uses': 'fixture'},
                {'id': 'second-scene', 'uses': 'fixture', 'review_stage': 'S2'},
                {'id': 'annotations', 'uses': 'fixture', 'review_stage': 'S3'}]})
            args = {'plan': str(plan), 'run': str(root/'run'), '_workspace': tmp,
                    '_dsh_context': {'session_id': 'session-one'}}
            calls = []

            def execute(step, *unused):
                calls.append(step['id'])
                return {'state': 'completed', 'preview': step['id']+'.png'}

            with patch('benchforge_core.pipelines.runner.execute_step', side_effect=execute):
                initial = run(args, root/'operation')
                review(tmp, 'session-one', 'continue', review_id=initial['stage_review']['review_id'])
                scenes = run(args, root/'operation')
                self.assertEqual(calls, ['first-scene', 'helper', 'second-scene'])
                self.assertEqual(scenes['stage_review']['stage'], 'S2')
                self.assertEqual([item['result']['preview'] for item in read(scenes['stage_review']['artifact'])['outputs']],
                                 ['first-scene.png', 'second-scene.png'])
                review(tmp, 'session-one', 'continue', review_id=scenes['stage_review']['review_id'])
                annotations = run(args, root/'operation')
                self.assertEqual(annotations['stage_review']['stage'], 'S3')
                self.assertEqual(calls, ['first-scene', 'helper', 'second-scene', 'annotations'])

    def test_mixed_nested_recipe_reviews_questions_before_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root/'plan.json'
            write(plan, {'inputs': {}, 'steps': [
                {'id': 'dataset', 'uses': 'pipeline', 'pipeline_id': 'data.capability',
                 'arguments': {'selections': [], 'seed': 1, 'split': 'train'}}]})
            args = {'plan': str(plan), 'run': str(root/'run'), '_workspace': tmp,
                    '_dsh_context': {'session_id': 'session-one'}}
            with patch('benchforge_core.pipelines.runner.produce', return_value={'dataset': 'fixture', 'accepted': 3}) as produce, \
                 patch('benchforge_core.pipelines.runner.package', return_value={'public_bundle': 'fixture.zip'}) as package:
                initial = run(args, root/'operation')
                review(tmp, 'session-one', 'continue', review_id=initial['stage_review']['review_id'])
                questions = run(args, root/'operation')
                self.assertEqual(questions['stage_review']['stage'], 'S4')
                self.assertEqual(produce.call_count, 1)
                self.assertEqual(package.call_count, 0)
                review(tmp, 'session-one', 'continue', review_id=questions['stage_review']['review_id'])
                packaged = run(args, root/'operation')
                self.assertEqual(packaged['stage_review']['stage'], 'S5')
                self.assertEqual(produce.call_count, 1)
                self.assertEqual(package.call_count, 1)
                review(tmp, 'session-one', 'continue', review_id=packaged['stage_review']['review_id'])
                self.assertEqual(run(args, root/'operation')['state'], 'completed')
                self.assertEqual(package.call_count, 1)

    def test_edit_during_nested_submission_stops_old_plan_before_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root/'plan.json'
            write(plan, {'inputs': {}, 'steps': [
                {'id': 'scene', 'uses': 'pipeline', 'pipeline_id': 'scene.capture',
                 'arguments': {'scene_program_path': 'scene.json', 'service_config': 'fixture.json'}}]})
            args = {'plan': str(plan), 'run': str(root/'run'), '_workspace': tmp,
                    '_dsh_context': {'session_id': 'session-one'}}
            activate(tmp, 'session-one', str(plan))
            calls = []

            def client(route, arguments, config):
                calls.append(route)
                activate(tmp, 'session-one', str(plan), expected=str(plan), pending=True, changes=['scene_layout'])
                return {'run_id': 'scene-fixture', 'state': 'RUNNING'}

            initial = run(args, root/'operation', client=client)
            review(tmp, 'session-one', 'continue', review_id=initial['stage_review']['review_id'])
            edited = run(args, root/'operation', client=client)
            self.assertEqual(edited['state'], 'needs_plan_application')
            self.assertEqual(calls, ['/capture'])
            self.assertEqual(run(args, root/'operation', client=client)['state'], 'needs_plan_application')
            self.assertEqual(calls, ['/capture'])


if __name__=='__main__': unittest.main()
