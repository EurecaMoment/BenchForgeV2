import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from benchforge_core.pipelines.plan_edit import save_edit
from benchforge_core.pipelines.plan_versions import current
from benchforge_core.runtime import Runtime, read
import test_assessment_plan as fixtures

source = Path(__file__).resolve().parents[1] / 'integrations/spatialforge/ui/plan_request_cli.py'
spec = importlib.util.spec_from_file_location('legacy_plan_request', source)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class LegacyPlanRequestTests(unittest.TestCase):
    def test_applied_request_is_idempotent_and_preserves_review_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = 'legacy-native-session'
            runtime = Runtime(tmp)
            runtime.dsh_context = {'session_id': session}
            document = fixtures.assessment_fixture()
            try:
                original = runtime.call('pipeline_plan', {
                    'objective': document['summary'], 'assessment': document,
                    'selections': fixtures.AssessmentPlanTests.selections,
                    'inputs': fixtures.AssessmentPlanTests.inputs,
                })
            finally:
                runtime.close()
            edited = copy.deepcopy(document)
            edited['dataset']['target_items'] = 8
            for row in edited['coverage']:
                row['count'] = 4
            saved = save_edit(tmp, session, original['plan'], edited)
            plan = read(saved['plan'])
            request = {key: plan[key] for key in ('objective', 'pipeline_id', 'assessment', 'selections', 'inputs', 'steps')}
            request['applies_edit'] = saved['plan']
            path = Path(tmp) / 'apply-request.json'
            path.write_text(json.dumps(request), encoding='utf8')
            first = legacy.submit(tmp, session, str(path))
            version = current(tmp, session)['version']
            second = legacy.submit(tmp, session, str(path))
            self.assertEqual(second['state'], 'already_applied')
            self.assertEqual(second['plan'], first['plan'])
            self.assertEqual(second['stage_review']['review_id'], first['stage_review']['review_id'])
            self.assertEqual(second['stage_review']['deadline'], first['stage_review']['deadline'])
            self.assertEqual(current(tmp, session)['version'], version)
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                legacy.submit(tmp, 'another-native-session', str(path))
            request['inputs']['target_items'] = 9
            path.write_text(json.dumps(request), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'already been applied'):
                legacy.submit(tmp, session, str(path))
            self.assertEqual(current(tmp, session)['version'], version)


if __name__ == '__main__':
    unittest.main()
