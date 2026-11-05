import copy
import json
import tempfile
import unittest
from pathlib import Path

from benchforge_core.runtime import Runtime, read
from benchforge_core.pipelines.assessment import validate_assessment, AssessmentValidationError
from benchforge_core.pipelines.plan_input import resolve_request
import test_assessment_plan as fixtures

assessment_fixture = fixtures.assessment_fixture


class PlanFileSubmissionTests(unittest.TestCase):
    def test_file_and_inline_preserve_document_and_session_review(self):
        document = assessment_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'assessment.json'
            source.write_text(json.dumps(document), encoding='utf-8')
            runtime = Runtime(tmp)
            runtime.dsh_context = {'session_id': 'file-plan-session'}
            request = {'objective': document['summary'], 'assessment_path': source.name,
                       'selections': fixtures.AssessmentPlanTests.selections, 'inputs': fixtures.AssessmentPlanTests.inputs}
            try:
                checked = runtime.call('pipeline_plan', {**request, 'validate_only': True})
                self.assertEqual(checked['state'], 'validated')
                self.assertFalse((Path(checked['artifact_dir']) / 'plan.json').exists())
                result = runtime.call('pipeline_plan', request)
                saved = read(result['plan'])
                self.assertEqual(saved['assessment'], document)
                self.assertEqual(saved['authoring_sources']['assessment_path'], str(source.resolve()))
                self.assertEqual(result['stage_review']['state'], 'waiting_user')
            finally:
                runtime.close()

    def test_full_request_retains_host_context_and_rejects_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'request.json'
            base = {'objective': 'Distance', 'assessment': assessment_fixture(),
                    'selections': fixtures.AssessmentPlanTests.selections, 'inputs': fixtures.AssessmentPlanTests.inputs}
            source.write_text(json.dumps(base), encoding='utf-8')
            result, _ = resolve_request({'request_path': source.name, '_dsh_context': {'session_id': 'host'}}, tmp)
            self.assertEqual(result, {**base, '_dsh_context': {'session_id': 'host'}})
            with self.assertRaisesRegex(ValueError, 'not both'):
                resolve_request({'request_path': source.name, 'objective': 'Override'}, tmp)
            for key in ('_dsh_context', '_plan_edit', 'request_path'):
                source.write_text(json.dumps({**base, key: {}}), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'unsupported fields'):
                    resolve_request({'request_path': source.name}, tmp)

    def test_lint_reports_all_missing_fields_and_preserves_source(self):
        value = assessment_fixture()
        del value['scoring']
        del value['risks']
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'assessment.json'
            text = json.dumps(value)
            source.write_text(text, encoding='utf-8')
            runtime = Runtime(tmp)
            try:
                result = runtime.call('pipeline_plan', {'assessment_path': source.name, 'validate_only': True,
                    'selections': fixtures.AssessmentPlanTests.selections, 'inputs': fixtures.AssessmentPlanTests.inputs})
                self.assertEqual(result['state'], 'needs_plan_revision')
                self.assertEqual(len(result['issues']), 2)
                self.assertTrue(any('scoring' in x for x in result['issues']))
                self.assertTrue(any('risks' in x for x in result['issues']))
                self.assertEqual(source.read_text(encoding='utf-8'), text)
                self.assertFalse((Path(result['artifact_dir']) / 'plan.json').exists())
            finally:
                runtime.close()

    def test_preflight_combines_missing_sections_scene_fields_and_allocation_errors(self):
        value = assessment_fixture()
        del value['scoring']
        del value['risks']
        del value['questions']['answerability']
        value['dataset']['target_items'] = 6
        design = value['scenes']['designs'][0]
        design.update(summary='杯子位于桌面，椅子面向桌子。', hard_requirements=['杯子正立'],
                      physical_assumptions=['静态支撑'],
                      object_roles=[{'object_id': 'desk'}, {'role': '椅子'}],
                      relations=[{'source': 'chair', 'type': 'facing', 'target': 'desk'},
                                 {'type': 'near', 'target': 'desk', 'description': '便于取用'}])
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'assessment.json'
            original = json.dumps(value, ensure_ascii=False)
            source.write_text(original, encoding='utf-8')
            runtime = Runtime(tmp)
            try:
                result = runtime.call('pipeline_plan', {'assessment_path': source.name, 'validate_only': True,
                    'selections': fixtures.AssessmentPlanTests.selections, 'inputs': fixtures.AssessmentPlanTests.inputs})
                self.assertEqual(result['state'], 'needs_plan_revision')
                for path in ('assessment.scoring', 'assessment.risks', 'assessment.questions.answerability',
                             'assessment.scenes.designs[0].object_roles[0].role',
                             'assessment.scenes.designs[0].object_roles[1].object_id',
                             'assessment.scenes.designs[0].relations[0].description',
                             'assessment.scenes.designs[0].relations[1].source', 'assessment.dataset.target_items'):
                    with self.subTest(path=path):
                        self.assertTrue(any(path in issue for issue in result['issues']), result['issues'])
                self.assertEqual(source.read_text(encoding='utf-8'), original)
                self.assertFalse((Path(result['artifact_dir']) / 'plan.json').exists())
                self.assertEqual(result['authoring_sources']['assessment_path'], str(source.resolve()))
            finally:
                runtime.close()

    def test_preflight_handles_malformed_fields_without_hiding_independent_errors(self):
        value = assessment_fixture()
        value['objectives'][0]['id'] = []
        value['coverage'][0]['count'] = None
        value['execution'][0]['stage'] = {}
        value['scoring']['metrics'][0] = []
        value['delivery']['artifacts'][0]['stage'] = []
        value['dataset']['seed'] = 'seed'
        value['scenes']['allow_new_scenes'] = 'yes'
        value['questions']['answerability'] = None
        before = copy.deepcopy(value)
        with self.assertRaises(AssessmentValidationError) as raised:
            validate_assessment(value, fixtures.AssessmentPlanTests.selections, fixtures.AssessmentPlanTests.inputs)
        for path in ('assessment.objectives[0].id', 'assessment.coverage[0].count', 'assessment.execution[0].stage',
                     'assessment.scoring.metrics[0]', 'assessment.delivery.artifacts[0].stage',
                     'assessment.dataset.seed', 'assessment.scenes.allow_new_scenes', 'assessment.questions.answerability'):
            with self.subTest(path=path):
                self.assertTrue(any(path in issue for issue in raised.exception.issues), raised.exception.issues)
        self.assertEqual(value, before)

    def test_concise_scene_brief_is_accepted_without_optional_design_advice(self):
        value = assessment_fixture()
        value['scenes']['designs'][0].update(name='书桌', summary='杯子位于桌面。',
            hard_requirements=['杯子正立'], physical_assumptions=['静态支撑'],
            object_roles=[{'object_id': 'desk', 'role': '书桌'}, {'object_id': 'cup', 'role': '水杯'}],
            relations=[{'source': 'cup', 'type': 'supported_by', 'target': 'desk', 'description': '桌面支撑'}])
        result = validate_assessment(value, fixtures.AssessmentPlanTests.selections, fixtures.AssessmentPlanTests.inputs)
        self.assertEqual(result, value)
        self.assertIsNot(result, value)
        self.assertNotIn('geometry_exceptions', result['scenes'])
        self.assertNotIn('revision_history', result['scenes']['designs'][0])

    def test_declared_geometry_placeholders_are_reported_together_at_their_fields(self):
        value = assessment_fixture()
        fields = ('purpose', 'reason', 'simplifications', 'retained_constraints', 'excluded_claims')
        value['scenes']['geometry_exceptions'] = [{
            'scene_design_id': value['scenes']['designs'][0]['id'], 'scene_id': 'declared-experiment',
            'object_ids': ['cube'], **{key: 'none' for key in fields}}]
        with self.assertRaises(AssessmentValidationError) as raised:
            validate_assessment(value, fixtures.AssessmentPlanTests.selections, fixtures.AssessmentPlanTests.inputs)
        for key in fields:
            self.assertTrue(any(f'assessment.scenes.geometry_exceptions[0].{key}' in issue
                                for issue in raised.exception.issues), raised.exception.issues)

    def test_invalid_files_do_not_create_a_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'bad.json'
            for text in ('{invalid', '[]'):
                source.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    resolve_request({'assessment_path': source.name}, tmp)
            with self.assertRaisesRegex(ValueError, 'not both'):
                resolve_request({'assessment_path': source.name, 'assessment': {}}, tmp)
            with self.assertRaisesRegex(ValueError, 'existing JSON'):
                resolve_request({'assessment_path': 'missing.json'}, tmp)

    def test_failed_inline_submission_keeps_a_reusable_complete_draft(self):
        value = assessment_fixture()
        del value['risks']
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(tmp)
            try:
                result = runtime.call('pipeline_plan', {'assessment': value, 'validate_only': True,
                    'selections': fixtures.AssessmentPlanTests.selections, 'inputs': fixtures.AssessmentPlanTests.inputs})
                draft = read(result['authoring_sources']['request_path'])
                self.assertEqual(draft['assessment'], value)
                self.assertNotIn('_dsh_context', draft)
                self.assertNotIn('validate_only', draft)
                self.assertFalse((Path(result['artifact_dir']) / 'plan.json').exists())
            finally:
                runtime.close()

    def test_concise_roles_are_valid_but_object_references_still_checked(self):
        from benchforge_core.pipelines.scene_policy import scene_design_parser
        brief = {'name': '书桌', 'summary': '杯子立在桌面上，椅子面向书桌，通道保持畅通。',
                 'hard_requirements': ['杯子正立'], 'physical_assumptions': ['静态支撑'],
                 'object_roles': [{'object_id': 'ground', 'role': '地面'}, {'object_id': 'cup', 'role': '水杯'}],
                 'relations': [{'source': 'cup', 'type': 'supported_by', 'target': 'ground', 'description': '落地'}]}
        parser = scene_design_parser()
        self.assertEqual(parser.validate_scene_brief(brief, {'ground', 'cup'}), brief)
        for section, key in (('object_roles', 'object_id'), ('relations', 'source')):
            broken = copy.deepcopy(brief)
            broken[section][0][key] = 'missing'
            with self.assertRaises(ValueError):
                parser.validate_scene_brief(broken, {'ground', 'cup'})


if __name__ == '__main__':
    unittest.main()
