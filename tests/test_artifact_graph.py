import tempfile
import unittest
from pathlib import Path

from benchforge_core.pipelines.artifact_graph import ArtifactGraph, inspect, make_record
from benchforge_core.pipelines.repair import choose_operator, repair_plan
from benchforge_core.pipelines.runner import run
from benchforge_core.runtime import read, write


class ArtifactGraphTests(unittest.TestCase):
    def test_records_contract_refs_and_parent_bindings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = {
                'schema': 'spatialforge.pipeline/v1', 'version': 1,
                'pipeline_id': 'fixture',
                'inputs': {'service_config': 'fixture.json'},
                'steps': [
                    {'id': 'capture', 'uses': 'spatialforge.capture',
                     'artifact_type': 'scene.capture',
                     'arguments': {'scene_program_path': '/workspace/scene.json'}},
                    {'id': 'ready', 'uses': 'spatialforge.observe',
                     'artifact_type': 'scene.evidence',
                     'arguments': {'run_id': '$capture.run_id'},
                     'await_terminal': True},
                ],
            }
            plan_path = root / 'plan.json'
            write(plan_path, plan)
            calls = []

            def client(route, arguments, config):
                calls.append(route)
                if route == '/capture':
                    return {'run_id': 'fixture-run', 'state': 'accepted'}
                return {'run_id': 'fixture-run', 'state': 'SUCCEEDED', 'capture': 'capture.json'}

            result = run({'plan': str(plan_path), '_workspace': str(root)}, root / 'execution', client=client)
            self.assertEqual(result['state'], 'completed')
            graph = ArtifactGraph(result['run'])
            self.assertEqual(len(graph.records), 2)
            capture, ready = graph.records
            self.assertEqual(capture['status'], 'candidate')
            self.assertEqual(capture['evidence_refs'], ['/workspace/scene.json'])
            self.assertEqual(ready['parents'], [capture['artifact_id']])
            self.assertEqual(ready['contract_results']['status'], 'not_applicable')
            self.assertEqual(inspect({'run': result['run']})['summary']['total'], 2)
            self.assertEqual(calls, ['/capture', '/inspect'])

    def test_missing_binding_is_recorded_without_mutating_gt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_path = root / 'plan.json'
            write(plan_path, {
                'schema': 'spatialforge.pipeline/v1', 'version': 1,
                'pipeline_id': 'fixture', 'inputs': {},
                'steps': [{'id': 'capture', 'uses': 'spatialforge.capture',
                           'arguments': {'scene_program_path': '$inputs.scene_program_path'}}],
            })
            result = run({'plan': str(plan_path), '_workspace': str(root)}, root / 'execution', client=lambda *args: {})
            self.assertEqual(result['state'], 'needs_input')
            self.assertEqual(result['repair']['operator'], 'local_field_repair')
            record = ArtifactGraph(result['run']).records[-1]
            self.assertEqual(record['status'], 'rejected')
            self.assertIn('$inputs.scene_program_path', record['contract_results']['errors'][0])
            self.assertFalse((Path(result['run']) / 'gt.json').exists())

    def test_repair_operator_is_explicit_and_bounded(self):
        self.assertEqual(choose_operator('evidence_mismatch'), 'template_rebinding')
        self.assertEqual(choose_operator('service_unavailable'), 'skill_reexecution')
        self.assertEqual(choose_operator('state_drift'), 'upstream_rollback')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            graph = ArtifactGraph(root)
            record = make_record(graph=graph, run_id='run-fixture', step_id='item',
                                 operation='templates.produce', arguments={'evidence': 'evidence.jsonl'},
                                 result={'dataset': 'dataset', 'report': 'report', 'accepted': 0},
                                 parent_ids=[])
            plan = repair_plan({'run': str(root), 'artifact_id': record['artifact_id'],
                                'failure_code': 'contract_failure'})
            self.assertEqual(plan['operator'], 'candidate_resynthesis')
            self.assertTrue(plan['requires_new_run'])
            self.assertTrue((root / 'repair-plans.jsonl').is_file())


if __name__ == '__main__':
    unittest.main()
