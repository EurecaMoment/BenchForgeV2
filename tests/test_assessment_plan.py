import copy
import tempfile
import unittest
from pathlib import Path

from benchforge_core.pipelines.assessment import assessment_template, validate_assessment
from benchforge_core.pipelines.catalog import catalog
from benchforge_core.pipelines.planner import plan
from benchforge_core.runtime import read
from benchforge_core.runtime import Runtime
from benchforge_core.pipelines.plan_edit import save_edit
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


class AssessmentPlanTests(unittest.TestCase):
    selections = [{'template_ids': ['C01-T01', 'C01-T02'], 'count': 5, 'reason': 'Distance protocols'}]
    inputs = {'seed': 1030, 'target_items': 5}

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
                    'inputs':{'seed':1030,'target_items':5}})
                baseline=execute(original['plan'])
                self.assertEqual(baseline['state'],'completed')
                saved=read(original['plan']);edit=copy.deepcopy(saved['assessment'])
                edit['coverage'][0]['count']=7;edit['dataset']['target_items']=7;edit['dataset']['seed']=44
                changed=save_edit(tmp,'session-direct-edit',original['plan'],edit,'dev')
                self.assertEqual(current(tmp,'session-direct-edit')['pending'],True)
                self.assertEqual(execute(original['plan'])['state'],'plan_superseded')
                self.assertEqual(execute(changed['plan'])['state'],'needs_plan_application')
                with self.assertRaisesRegex(ValueError,'replaced'):
                    save_edit(tmp,'session-direct-edit',original['plan'],edit)
                plan_args=read(changed['plan'])
                args={key:plan_args[key] for key in ('objective','pipeline_id','assessment','selections','inputs','steps')}
                with self.assertRaisesRegex(ValueError,'applies_edit'):
                    runtime.call('pipeline_plan',args)
                args['applies_edit']=changed['plan']
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
                semantic=copy.deepcopy(edit);semantic['questions']['answerability']='Public images must contain a direction marker'
                next_edit=save_edit(tmp,'session-direct-edit',applied['plan'],semantic,'dev')
                next_plan=read(next_edit['plan'])
                next_args={key:next_plan[key] for key in ('objective','pipeline_id','assessment','selections','inputs','steps')}
                with self.assertRaisesRegex(ValueError,'updated executable'):
                    runtime.call('pipeline_plan',{**next_args,'applies_edit':next_edit['plan']})
            finally:runtime.close()


if __name__ == '__main__':
    unittest.main()
