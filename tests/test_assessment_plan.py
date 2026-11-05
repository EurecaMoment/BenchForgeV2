import copy
import tempfile
import unittest
from pathlib import Path
import yaml

from benchforge_core.pipelines.assessment import assessment_template, validate_assessment
from benchforge_core.pipelines.catalog import catalog
from benchforge_core.pipelines.planner import plan
from benchforge_core.runtime import read
from benchforge_core.runtime import Runtime
from benchforge_core.pipelines.plan_edit import assessment_from_markdown, save_edit
from benchforge_core.pipelines.plan_versions import current


def assessment_fixture():
    def fill(value):
        if isinstance(value, dict):
            return {key: fill(child) for key, child in value.items()}
        if isinstance(value, list):
            return [fill(child) for child in value]
        return 'Fixture design condition' if value == '' else value
    value = fill(assessment_template()['assessment'])
    value['objectives'][0]['id'] = 'distance'
    value['coverage'] = [{'objective_id': 'distance', 'template_id': tid, 'count': count,
                          'difficulty': 'medium', 'conditions': 'Calibrated public geometry',
                          'selection_reason': 'Measure the declared distance protocol'}
                         for tid, count in [('C01-T01', 3), ('C01-T02', 2)]]
    value['scenes'].update(allow_new_scenes=True, target_scene_count=2)
    value['dataset'].update(target_items=5, seed=1030)
    value['scoring']['metrics'] = [{'template_id': tid, 'metric': 'absolute error', 'unit': 'm',
                                  'tolerance': '0.02 m', 'aggregation': 'per-template mean'}
                                 for tid in ['C01-T01', 'C01-T02']]
    value['delivery']['artifacts'] = [{'stage': stage, 'path': stage + '/artifact.json', 'format': 'json',
                                      'contents': 'Viewable stage artifact'} for stage in ['S1', 'S2', 'S3', 'S4', 'S5']]
    return value


def markdown_fixture(assessment, narrative='计划正文：使用公开图像制作距离评测。'):
    return '# 完整评测计划\n\n' + narrative + '\n\n```assessment-yaml\n' + yaml.safe_dump(
        assessment, allow_unicode=True, sort_keys=False) + '```\n'


class AssessmentPlanTests(unittest.TestCase):
    selections = [{'template_ids': ['C01-T01', 'C01-T02'], 'count': 5, 'reason': 'Distance protocols'}]
    inputs = {'seed': 1030, 'target_items': 5}

    def test_markdown_requires_one_valid_assessment_mapping(self):
        document = assessment_fixture()
        markdown = markdown_fixture(document)
        self.assertEqual(assessment_from_markdown(markdown), document)
        variants = ['', '# Missing assessment', markdown + markdown,
                    '```assessment-yaml\nquestions: [unterminated\n```\n',
                    '```assessment-yaml\n- not a mapping\n```\n', 'x' * 512_001]
        for value in variants:
            with self.subTest(markdown=value[:80]), self.assertRaises(ValueError):
                assessment_from_markdown(value)

    def test_legacy_structured_edit_remains_supported(self):
        document = assessment_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(tmp)
            runtime.dsh_context = {'session_id': 'session-structured-edit'}
            try:
                original = runtime.call('pipeline_plan', {'objective': document['summary'], 'assessment': document,
                    'selections': self.selections, 'inputs': self.inputs})
                edit = copy.deepcopy(document)
                edit['dataset']['seed'] = 77
                revised = save_edit(tmp, 'session-structured-edit', original['plan'], edit, 'dev')
                saved = read(revised['plan'])
                self.assertEqual(saved['inputs']['seed'], 77)
                self.assertEqual(saved['inputs']['split'], 'dev')
                self.assertNotIn('user_markdown', saved)
                self.assertTrue(current(tmp, 'session-structured-edit')['pending'])
            finally:
                runtime.close()

    def test_model_template_and_persisted_plan_share_the_document(self):
        self.assertEqual(len(catalog({'section': 'plan_template'})['sections']), 11)
        document = assessment_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            result = plan({'objective': 'Distance benchmark', 'selections': self.selections,
                           'inputs': self.inputs, 'assessment': document}, tmp)
            self.assertEqual(result['assessment_status'], 'structured')
            self.assertEqual(read(result['plan'])['assessment'], document)

    def test_incomplete_or_inconsistent_design_is_rejected_before_saving(self):
        variants = []
        missing = assessment_fixture()
        del missing['questions']['answerability']
        variants.append(missing)
        counts = assessment_fixture()
        counts['coverage'][0]['count'] = 4
        variants.append(counts)
        delivery = assessment_fixture()
        delivery['delivery']['artifacts'].pop()
        variants.append(delivery)
        scoring = assessment_fixture()
        scoring['scoring']['metrics'].pop()
        variants.append(scoring)
        for value in variants:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    plan({'objective': 'Distance benchmark', 'selections': self.selections,
                          'inputs': self.inputs, 'assessment': value}, tmp)
                self.assertFalse((Path(tmp) / 'plan.json').exists())

    def test_reuse_constraints_cannot_be_bypassed_in_the_design(self):
        value = assessment_fixture()
        selection = {'selection_path': '/scene-library/session.json', 'allow_new_scenes': False,
                     'selected_scenes': [{'task_id': 'selected-scene', 'revision': 2}]}
        value['scenes'].update(selection_path=selection['selection_path'], allow_new_scenes=False,
                               selected_scenes=copy.deepcopy(selection['selected_scenes']))
        inputs = {**self.inputs, 'scene_selection': selection}
        validate_assessment(value, self.selections, inputs)
        value['scenes']['selected_scenes'][0]['revision'] = 3
        with self.assertRaisesRegex(ValueError, 'saved scene selection'):
            validate_assessment(value, self.selections, inputs)

    def test_direct_edit_changes_real_production_and_blocks_stale_plans(self):
        document=assessment_fixture()
        document['coverage']=document['coverage'][:1];document['coverage'][0]['count']=5
        document['scoring']['metrics']=document['scoring']['metrics'][:1]
        document['questions']['authority']={'answer':'private answer retained outside the public document'}
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp);runtime.dsh_context={'session_id':'session-direct-edit'}
            def execute(path):
                result=runtime.call('pipeline_run',{'plan':path})
                while result['state']=='waiting_user':
                    runtime.call('stage_review',{'action':'continue','review_id':result['stage_review']['review_id']})
                    result=runtime.call('pipeline_run',{'plan':path,'run':result['run']})
                return result
            try:
                original=runtime.call('pipeline_plan',{'objective':document['summary'],'assessment':document,
                    'selections':[{'template_ids':['C01-T01'],'count':5,'reason':'Distance protocols'}],
                    'inputs':{'seed':1030,'target_items':5},'user_markdown':markdown_fixture(document)})
                baseline=execute(original['plan'])
                self.assertEqual(baseline['state'],'completed')
                saved=read(original['plan']);edit=copy.deepcopy(saved['assessment'])
                del edit['questions']['authority']
                edit['coverage'][0]['count']=7;edit['dataset']['target_items']=7;edit['dataset']['seed']=44
                markdown=markdown_fixture(edit)
                changed=save_edit(tmp,'session-direct-edit',original['plan'],split='dev',markdown=markdown)
                self.assertEqual(current(tmp,'session-direct-edit')['pending'],True)
                self.assertEqual(execute(original['plan'])['state'],'plan_superseded')
                self.assertEqual(execute(changed['plan'])['state'],'needs_plan_application')
                with self.assertRaisesRegex(ValueError,'replaced'):
                    save_edit(tmp,'session-direct-edit',original['plan'],markdown=markdown)
                plan_args=read(changed['plan'])
                self.assertEqual(plan_args['user_markdown'],markdown)
                self.assertEqual(Path(plan_args['user_markdown_path']).read_text(encoding='utf-8'),markdown)
                self.assertEqual(plan_args['assessment']['questions']['authority'],document['questions']['authority'])
                args={key:plan_args[key] for key in ('objective','pipeline_id','assessment','selections','inputs','steps','user_markdown')}
                with self.assertRaisesRegex(ValueError,'applies_edit'):
                    runtime.call('pipeline_plan',args)
                args['applies_edit']=changed['plan']
                missing=copy.deepcopy(args);del missing['user_markdown']
                with self.assertRaisesRegex(ValueError,'complete saved user-edited Markdown'):
                    runtime.call('pipeline_plan',missing)
                wrong=copy.deepcopy(args);wrong['assessment']['questions']['answerability']='Ignored user text'
                with self.assertRaisesRegex(ValueError,'retain'):
                    runtime.call('pipeline_plan',wrong)
                applied=runtime.call('pipeline_plan',args)
                with self.assertRaisesRegex(ValueError,'edited seed'):
                    runtime.call('pipeline_run',{'plan':applied['plan'],'bindings':{'seed':999}})
                result=execute(applied['plan'])
                self.assertEqual(result['state'],'completed')
                reports=list(Path(result['run']).rglob('quality_report.json'))
                self.assertTrue(reports)
                self.assertEqual(read(reports[0])['accepted'],7)
                self.assertEqual(read(reports[0])['split'],'dev')
                self.assertEqual(read(original['plan']),saved)
                self.assertEqual(read(applied['plan'])['user_markdown'],markdown)
                semantic=markdown_fixture(edit,'公开图像必须包含方向标记；遮挡时重做采集。')
                next_edit=save_edit(tmp,'session-direct-edit',applied['plan'],split='dev',markdown=semantic)
                next_plan=read(next_edit['plan'])
                next_args={key:next_plan[key] for key in ('objective','pipeline_id','assessment','selections','inputs','steps','user_markdown')}
                with self.assertRaisesRegex(ValueError,'markdown_resolution'):
                    runtime.call('pipeline_plan',{**next_args,'applies_edit':next_edit['plan']})
            finally:runtime.close()

    def test_plain_markdown_quantity_change_is_normalized_and_produced(self):
        document=assessment_fixture()
        document['questions']['correct_answer']='private old answer'
        document['coverage']=document['coverage'][:1];document['coverage'][0]['count']=5
        document['scoring']['metrics']=document['scoring']['metrics'][:1]
        original_markdown='# Fixture design condition\n\n数据集规模为 5 题。\n'
        revised_markdown='# Fixture design condition\n\n数据集规模调整为 7 题。\n'
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp);runtime.dsh_context={'session_id':'session-markdown-normalize'}
            try:
                original=runtime.call('pipeline_plan',{'objective':document['summary'],'assessment':document,
                    'selections':[{'template_ids':['C01-T01'],'count':5,'reason':'Distance protocols'}],
                    'inputs':{'seed':1030,'target_items':5},'user_markdown':original_markdown})
                edited=save_edit(tmp,'session-markdown-normalize',original['plan'],split='train',
                    markdown=revised_markdown,base_markdown=original_markdown)
                saved=read(edited['plan'])
                self.assertTrue(saved['edit_revision']['markdown_normalization'])
                self.assertEqual(saved['assessment']['dataset']['target_items'],5,'saving prose does not guess production values')
                resolved=copy.deepcopy(saved['assessment'])
                resolved['coverage'][0]['count']=7
                resolved['dataset']['target_items']=7
                selections=[{'template_ids':['C01-T01'],'count':7,'reason':'Distance protocols'}]
                inputs=copy.deepcopy(saved['inputs'])
                inputs.update(selections=selections,target_items=7)
                steps=copy.deepcopy(saved['steps'])
                steps[0]['arguments']['selections']=selections
                resolution=[
                    {'path':'coverage.0.count','before':5,'after':7,'instruction':'数据集规模调整为 7 题。'},
                    {'path':'dataset.target_items','before':5,'after':7,'instruction':'数据集规模调整为 7 题。'}]
                apply_args={'objective':resolved['summary'],'pipeline_id':saved['pipeline_id'],
                    'assessment':resolved,'selections':selections,'inputs':inputs,'steps':steps,
                    'user_markdown':revised_markdown,'markdown_resolution':resolution,'applies_edit':edited['plan']}
                with self.assertRaisesRegex(ValueError,'cover every changed assessment field'):
                    runtime.call('pipeline_plan',{**apply_args,'markdown_resolution':resolution[:1]})
                bad_quote=copy.deepcopy(resolution);bad_quote[0]['instruction']='# Fixture design condition'
                with self.assertRaisesRegex(ValueError,'newly added or changed Markdown prose'):
                    runtime.call('pipeline_plan',{**apply_args,'markdown_resolution':bad_quote})
                bad_input=copy.deepcopy(apply_args);bad_input['inputs']['target_items']=6
                with self.assertRaisesRegex(ValueError,'target_items'):
                    runtime.call('pipeline_plan',bad_input)
                private_change=copy.deepcopy(apply_args)
                private_change['assessment']['questions']['correct_answer']='attacker supplied answer'
                private_change['markdown_resolution'].append({'path':'questions.correct_answer',
                    'before':'private old answer','after':'attacker supplied answer',
                    'instruction':'数据集规模调整为 7 题。'})
                with self.assertRaisesRegex(ValueError,'protected answer'):
                    runtime.call('pipeline_plan',private_change)
                ground_truth_change=copy.deepcopy(apply_args)
                ground_truth_change['assessment']['questions']['ground_truth']='attacker supplied truth'
                ground_truth_change['markdown_resolution'].append({'path':'questions.ground_truth',
                    'before':None,'after':'attacker supplied truth','instruction':'数据集规模调整为 7 题。'})
                with self.assertRaisesRegex(ValueError,'protected answer'):
                    runtime.call('pipeline_plan',ground_truth_change)
                applied=runtime.call('pipeline_plan',apply_args)
                applied_plan=read(applied['plan'])
                self.assertEqual(applied_plan['markdown_resolution'],resolution)
                self.assertEqual(applied_plan['edit_revision']['markdown_resolution'],resolution)
                result=runtime.call('pipeline_run',{'plan':applied['plan']})
                while result['state']=='waiting_user':
                    runtime.call('stage_review',{'action':'continue','review_id':result['stage_review']['review_id']})
                    result=runtime.call('pipeline_run',{'plan':applied['plan'],'run':result['run']})
                self.assertEqual(result['state'],'completed')
                reports=list(Path(result['run']).rglob('quality_report.json'))
                self.assertTrue(reports)
                self.assertEqual(read(reports[0])['accepted'],7)
                self.assertEqual(read(original['plan'])['assessment']['dataset']['target_items'],5)
            finally:runtime.close()

    def test_deleted_quantity_rule_can_update_assessment_without_invented_new_prose(self):
        document=assessment_fixture()
        document['questions']['authority']={'answer':'private fixture answer'}
        removed='数据集规模固定为 5 题。'
        original_markdown='# '+document['title']+'\n\n'+removed+'\n'
        edited_markdown='# '+document['title']+'\n'
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp);runtime.dsh_context={'session_id':'session-delete-normalize'}
            try:
                original=runtime.call('pipeline_plan',{'objective':document['summary'],'assessment':document,
                    'selections':self.selections,'inputs':self.inputs,'user_markdown':original_markdown})
                draft=save_edit(tmp,'session-delete-normalize',original['plan'],markdown=edited_markdown,
                                base_markdown=original_markdown)
                saved=read(draft['plan'])
                resolved=copy.deepcopy(saved['assessment'])
                for row,count in zip(resolved['coverage'],(4,3)):
                    row['count']=count
                resolved['dataset']['target_items']=7
                selections=[{'template_ids':[row['template_id']],'count':row['count'],'reason':row['selection_reason']}
                            for row in resolved['coverage']]
                inputs=copy.deepcopy(saved['inputs']);inputs.update(selections=selections,target_items=7)
                resolution=[{'path':f'coverage.{index}.count','before':saved['assessment']['coverage'][index]['count'],
                             'after':row['count'],'instruction':removed} for index,row in enumerate(resolved['coverage'])]
                resolution.append({'path':'dataset.target_items','before':5,'after':7,'instruction':removed})
                applied=runtime.call('pipeline_plan',{'objective':resolved['summary'],'pipeline_id':saved['pipeline_id'],
                    'assessment':resolved,'selections':selections,'inputs':inputs,'steps':saved['steps'],
                    'user_markdown':edited_markdown,'markdown_resolution':resolution,'applies_edit':draft['plan']})
                accepted=read(applied['plan'])
                self.assertEqual(accepted['assessment']['dataset']['target_items'],7)
                self.assertEqual([row['count'] for row in accepted['inputs']['selections']],[4,3])
                self.assertEqual(accepted['steps'],saved['steps'])
                self.assertEqual(accepted['user_markdown'],edited_markdown)
                self.assertEqual(accepted['markdown_resolution'],resolution)
                self.assertEqual(accepted['assessment']['questions']['authority'],document['questions']['authority'])
                self.assertEqual(accepted['inputs'].get('scene_selection'),saved['inputs'].get('scene_selection'))
                self.assertFalse(current(tmp,'session-delete-normalize')['pending'])
            finally:runtime.close()

    def test_deleted_rule_rejects_unchanged_missing_and_unrelated_references(self):
        document=assessment_fixture()
        removed='数据集规模固定为 5 题。'
        unrelated='报告附带成像来源说明。'
        title='# '+document['title']
        original_markdown=title+'\n\n'+removed+'\n\n'+unrelated+'\n'
        edited_markdown=title+'\n'
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp);runtime.dsh_context={'session_id':'session-delete-bad-reference'}
            try:
                original=runtime.call('pipeline_plan',{'objective':document['summary'],'assessment':document,
                    'selections':self.selections,'inputs':self.inputs,'user_markdown':original_markdown})
                draft=save_edit(tmp,'session-delete-bad-reference',original['plan'],markdown=edited_markdown,
                                base_markdown=original_markdown)
                saved=read(draft['plan'])
                resolved=copy.deepcopy(saved['assessment'])
                for row,count in zip(resolved['coverage'],(4,3)):
                    row['count']=count
                resolved['dataset']['target_items']=7
                selections=[{'template_ids':[row['template_id']],'count':row['count'],'reason':row['selection_reason']}
                            for row in resolved['coverage']]
                inputs=copy.deepcopy(saved['inputs']);inputs.update(selections=selections,target_items=7)
                resolution=[{'path':f'coverage.{index}.count','before':saved['assessment']['coverage'][index]['count'],
                             'after':row['count'],'instruction':removed} for index,row in enumerate(resolved['coverage'])]
                resolution.append({'path':'dataset.target_items','before':5,'after':7,'instruction':removed})
                arguments={'objective':resolved['summary'],'pipeline_id':saved['pipeline_id'],'assessment':resolved,
                    'selections':selections,'inputs':inputs,'steps':saved['steps'],'user_markdown':edited_markdown,
                    'applies_edit':draft['plan']}
                for reference in (title,'正文从未出现的要求。'):
                    with self.subTest(reference=reference), self.assertRaisesRegex(ValueError,'newly added or changed Markdown prose'):
                        runtime.call('pipeline_plan',{**arguments,'markdown_resolution':[
                            {**row,'instruction':reference} for row in resolution]})
                with self.assertRaisesRegex(ValueError,'Narrative rules.*updated executable steps'):
                    runtime.call('pipeline_plan',{**arguments,'markdown_resolution':[
                        {**row,'instruction':unrelated} for row in resolution]})
                self.assertTrue(current(tmp,'session-delete-bad-reference')['pending'])
            finally:runtime.close()


if __name__ == '__main__':
    unittest.main()
