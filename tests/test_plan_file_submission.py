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
