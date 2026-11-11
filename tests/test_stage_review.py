import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from benchforge_core.stage_review import call as call_review, review
from benchforge_core.pipelines.runner import run
from benchforge_core.pipelines.plan_edit import save_edit
from benchforge_core.pipelines.plan_versions import activate, current
from benchforge_core.runtime import Runtime, read, write


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
            service_config = root/'service.json'
            write(service_config, {'service_url': 'http://127.0.0.1:3841', 'operator_token': 'fixture',
                                   'execution_mode': 'exploration'})
            plan = root/'plan.json'
            write(plan, {'inputs': {}, 'steps': [
                {'id': name, 'uses': 'pipeline', 'pipeline_id': 'scene.capture',
                 'arguments': {'scene_program_path': name+'.json', 'service_config': str(service_config)}}
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
            service_config = root/'service.json'
            write(service_config, {'service_url': 'http://127.0.0.1:3841', 'operator_token': 'fixture',
                                   'execution_mode': 'exploration'})
            plan = root/'plan.json'
            write(plan, {'inputs': {}, 'steps': [
                {'id': 'scene', 'uses': 'pipeline', 'pipeline_id': 'scene.capture',
                 'arguments': {'scene_program_path': 'scene.json', 'service_config': str(service_config)}}]})
            args = {'plan': str(plan), 'run': str(root/'run'), '_workspace': tmp,
                    '_dsh_context': {'session_id': 'session-one'}}
            alias_parent = root/'plan-parent'
            alias_parent.mkdir()
            active_path = (alias_parent/'..'/'plan.json').as_posix()
            activate(tmp, 'session-one', active_path)
            calls = []

            def client(route, arguments, config):
                calls.append(route)
                activate(tmp, 'session-one', active_path, expected=active_path, pending=True, changes=['scene_layout'])
                return {'run_id': 'scene-fixture', 'state': 'RUNNING'}

            initial = run(args, root/'operation', client=client)
            self.assertEqual(initial['state'], 'waiting_user', initial)
            review(tmp, 'session-one', 'continue', review_id=initial['stage_review']['review_id'])
            edited = run(args, root/'operation', client=client)
            self.assertEqual(edited['state'], 'needs_plan_application')
            self.assertEqual(calls, ['/capture'])
            self.assertEqual(run(args, root/'operation', client=client)['state'], 'needs_plan_application')
            self.assertEqual(calls, ['/capture'])

    def test_different_active_plan_still_blocks_before_initial_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root/'plan.json'
            changed_plan = root/'edited-plan.json'
            document = {'inputs': {}, 'steps': [{'id': 'scene', 'uses': 'fixture', 'review_stage': 'S2'}]}
            write(plan, document)
            write(changed_plan, document)
            activate(tmp, 'session-one', str(changed_plan))
            args = {'plan': str(plan), 'run': str(root/'run'), '_workspace': tmp,
                    '_dsh_context': {'session_id': 'session-one'}}
            with patch('benchforge_core.pipelines.runner.execute_step') as execute:
                result = run(args, root/'operation')
            self.assertEqual(result['state'], 'plan_superseded')
            self.assertNotIn('stage_review', result)
            execute.assert_not_called()

    def test_default_wait_returns_after_sixty_seconds_without_ending_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = review(tmp, 'session-one', 'open', stage='S2', key='capture', artifact='capture.json', now=1000)
            elapsed = [0.0]

            def advance(seconds):
                elapsed[0] += seconds

            with patch('benchforge_core.stage_review.time.time', side_effect=lambda: 1000+elapsed[0]), \
                 patch('benchforge_core.stage_review.time.monotonic', side_effect=lambda: elapsed[0]), \
                 patch('benchforge_core.stage_review.time.sleep', side_effect=advance):
                result = call_review({'action': 'wait', '_dsh_context': {'session_id': 'session-one'}},
                                     Path(tmp)/'operations'/'wait')
            self.assertEqual(elapsed[0], 60)
            self.assertEqual(result['state'], 'waiting_user')
            self.assertFalse(result['can_continue'])
            self.assertEqual(result['review_id'], first['review_id'])
            self.assertEqual(result['deadline'], first['deadline'])
            self.assertEqual(result['remaining_seconds'], 240)

    def test_pending_plan_edit_opens_s1_only_after_application(self):
        from test_assessment_plan import assessment_fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = Runtime(root)
            runtime.dsh_context = {'session_id': 'session-edit-window'}
            try:
                document = assessment_fixture()
                original = runtime.call('pipeline_plan', {'objective': document['summary'], 'assessment': document,
                    'selections': [{'template_ids': ['C01-T01', 'C01-T02'], 'count': 5, 'reason': 'Distance protocols'}],
                    'inputs': {'seed': 1030, 'target_items': 5}})
                review(tmp, 'session-edit-window', 'continue', review_id=original['stage_review']['review_id'])
                edited = read(original['plan'])['assessment']
                edited['dataset']['seed'] = 1031
                draft = save_edit(tmp, 'session-edit-window', original['plan'], edited)
                self.assertTrue(current(tmp, 'session-edit-window')['pending'])
                self.assertIsNone(draft['stage_review'])
                self.assertEqual(review(tmp, 'session-edit-window')['state'], 'continued')
                saved = read(draft['plan'])
                arguments = {key: saved[key] for key in ('objective', 'pipeline_id', 'assessment', 'selections', 'inputs', 'steps')}
                applied = runtime.call('pipeline_plan', {**arguments, 'applies_edit': draft['plan']})
                self.assertFalse(current(tmp, 'session-edit-window')['pending'])
                self.assertEqual(applied['stage_review']['stage'], 'S1')
                self.assertEqual(applied['stage_review']['review_id'], original['stage_review']['review_id'])
                self.assertEqual(applied['stage_review']['deadline'], original['stage_review']['deadline'])
                self.assertEqual(applied['stage_review']['deadline']-applied['stage_review']['started'], 300)
                waiting = run({'plan': applied['plan'], 'run': str(root/'run'), '_workspace': tmp,
                               '_dsh_context': {'session_id': 'session-edit-window'}}, root/'operation')
                self.assertTrue(applied['stage_review']['can_continue'])
                self.assertNotEqual(waiting['stage_review']['stage'], 'S1')
                with closing(sqlite3.connect(root/'stage-reviews.sqlite')) as db:
                    count = db.execute("SELECT COUNT(*) FROM reviews WHERE stage='S1'").fetchone()[0]
                self.assertEqual(count, 1)  # One parent stage window survives executable revisions.
            finally:
                runtime.close()

    def test_seed_and_markdown_emphasis_apply_but_new_production_rule_still_blocks(self):
        from test_assessment_plan import assessment_fixture, markdown_fixture

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(tmp)
            runtime.dsh_context = {'session_id': 'session-markdown-style'}
            try:
                document = assessment_fixture()
                original = runtime.call('pipeline_plan', {'objective': document['summary'], 'assessment': document,
                    'selections': [{'template_ids': ['C01-T01', 'C01-T02'], 'count': 5, 'reason': 'Distance protocols'}],
                    'inputs': {'seed': 1030, 'target_items': 5}, 'user_markdown': markdown_fixture(document)})
                edited = read(original['plan'])['assessment']
                edited['dataset']['seed'] = 1031
                markdown = markdown_fixture(edited, '计划正文：使用公开图像制作**距离评测**。')
                draft = save_edit(tmp, 'session-markdown-style', original['plan'], markdown=markdown)
                saved = read(draft['plan'])
                arguments = {key: saved[key] for key in ('objective', 'pipeline_id', 'assessment', 'selections', 'inputs', 'steps', 'user_markdown')}
                applied = runtime.call('pipeline_plan', {**arguments, 'applies_edit': draft['plan']})
                self.assertEqual(read(applied['plan'])['inputs']['seed'], 1031)
                self.assertEqual(read(applied['plan'])['user_markdown'], markdown)
                self.assertEqual(read(applied['plan'])['steps'], saved['steps'])
                semantic_document = read(applied['plan'])['assessment']
                semantic_document['dataset']['seed'] = 1032
                semantic = markdown_fixture(semantic_document, '计划正文：使用公开图像制作**距离评测**。所有图像必须添加北向标记。')
                rule_draft = save_edit(tmp, 'session-markdown-style', applied['plan'], markdown=semantic)
                rule = read(rule_draft['plan'])
                rule_arguments = {key: rule[key] for key in ('objective', 'pipeline_id', 'assessment', 'selections', 'inputs', 'steps', 'user_markdown')}
                with self.assertRaisesRegex(ValueError, 'Markdown instructions.*updated executable steps'):
                    runtime.call('pipeline_plan', {**rule_arguments, 'applies_edit': rule_draft['plan']})
                self.assertTrue(current(tmp, 'session-markdown-style')['pending'])
            finally:
                runtime.close()


if __name__=='__main__': unittest.main()
