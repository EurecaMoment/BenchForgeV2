import copy
import tempfile
import unittest
from pathlib import Path

from benchforge_core.pipelines.assessment import assessment_template, validate_assessment
from benchforge_core.pipelines.catalog import catalog
from benchforge_core.pipelines.planner import plan
from benchforge_core.runtime import read


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


if __name__ == '__main__':
    unittest.main()
