import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from benchforge_core.runtime import Runtime, read, write, rows, jsonl
from benchforge_core.pipelines.catalog import catalog, all_templates
from benchforge_core.pipelines.adapters import oracle
from benchforge_core.pipelines.evaluation import score
from benchforge_core.pipelines.runner import run


class PipelineTests(unittest.TestCase):
    def test_document_catalog_and_semantic_agent_selection(self):
        self.assertEqual(len(all_templates()), 267)
        self.assertEqual(catalog({'section': 'tasks', 'limit': 100})['total'], 89)
        matching = catalog({'section': 'templates', 'capability': '距离感知', 'limit': 100})
        self.assertTrue(any(t['id'] == 'C01-T01' for t in matching['items']))
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(tmp)
            response = runtime.call('pipeline_plan', {'objective': '生产距离和面积比较数据'})
            self.assertEqual(response['state'], 'needs_template_selection')
            selected = runtime.call('pipeline_plan', {'objective': '生产距离和面积比较数据', 'selections': [{'template_ids': ['C01-T01', 'P001-T01'], 'count': 8, 'reason': '按需求分别覆盖三维中心距离和二维填充面积'}]})
            self.assertEqual(selected['state'], 'planned')
            self.assertEqual(read(selected['plan'])['selections'][0]['template_ids'], ['C01-T01', 'P001-T01'])
            runtime.close()

    def test_real_outputs_oracles_no_public_authority_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(tmp)
            ids = ['C01-T01', 'C01-T02', 'C01-T03', 'C04-T01', 'C04-T02', 'C04-T03',
                   'C43-T01', 'C43-T03', 'C44-T01', 'C44-T02', 'C44-T03',
                   'P001-T01', 'P001-T02', 'P001-T03', 'P002-T01', 'P002-T02', 'P002-T03']
            planned = runtime.call('pipeline_plan', {'template_ids': ids, 'target_items': 51, 'seed': 5219})
            result = runtime.call('pipeline_run', {'plan': planned['plan']})
            self.assertEqual(result['state'], 'completed')
            dataset = Path(result['outputs']['questions']['dataset'])
            public, private = rows(dataset/'questions.jsonl'), rows(dataset/'authority.jsonl')
            self.assertEqual(len(public), 51)
            for question, truth in zip(public, private):
                self.assertNotIn('answer', question)
                self.assertNotIn('private_scene_parameters', question)
                self.assertEqual(oracle(truth['template_id'], read(dataset/truth['source'])), truth['answer'])
                self.assertTrue(score(truth, truth['answer'])['success'])
                for media in question['media']:
                    self.assertTrue((dataset/media).is_file())
            with zipfile.ZipFile(result['outputs']['package']['public_bundle']) as bundle:
                self.assertFalse(any('authority' in name or 'source' in name or name == 'sft.jsonl' for name in bundle.namelist()))
            timestamp = (dataset/'questions.jsonl').stat().st_mtime_ns
            resumed = runtime.call('pipeline_run', {'plan': planned['plan'], 'run': result['run']})
            self.assertEqual(resumed['state'], 'completed')
            self.assertEqual((dataset/'questions.jsonl').stat().st_mtime_ns, timestamp)
            predictions = Path(tmp)/'predictions.jsonl'
            jsonl(predictions, [{'item_id': t['item_id'], 'answer': t['answer']} for t in private])
            evaluated = runtime.call('pipeline_evaluate', {'dataset': str(dataset), 'predictions': str(predictions)})
            self.assertEqual(evaluated['model_api_calls'], 0)
            self.assertTrue(all(v['success_rate'] == 1 for v in evaluated['per_template'].values()))
            runtime.close()

    def test_independent_formula_and_geometry_regressions(self):
        world = {'objects': [{'center': [0, 0, 0], 'radius': 1}, {'center': [3, 4, 0], 'radius': 1}], 'requested_unit': 'm'}
        self.assertEqual(oracle('C01-T01', world)['value'], 5)
        self.assertEqual(oracle('C01-T02', world)['value'], 3)
        self.assertEqual(oracle('C43-T03', {'segments': [{'speed': 2, 'duration': 3, 'direction': 'forward'}, {'speed': 2, 'duration': 1, 'direction': 'backward'}]})['value'], 8)
        self.assertAlmostEqual(oracle('C44-T01', {'height': 4.9, 'gravity': 9.8})['value'], 1)
        self.assertFalse(score({'answer': {'value': 5, 'unit': 'm'}, 'tolerance': {'absolute': .02, 'relative': .05}}, {'value': 5, 'unit': 'cm'})['success'])

    def test_unimplemented_interactive_never_substituted(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(tmp)
            planned = runtime.call('pipeline_plan', {'template_ids': ['C81-T01'], 'target_items': 2})
            result = runtime.call('pipeline_run', {'plan': planned['plan']})
            self.assertEqual(result['state'], 'needs_evidence')
            self.assertEqual(result['steps']['questions']['result']['accepted'], 0)
            self.assertNotIn('package', result['steps'])
            runtime.close()

    def test_source_binding_and_group_split_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'simulation.json'
            write(source, {'result': {'label': 'visible'}, 'admission': {'template_id': 'C63-T01', 'protocol_id': 'D89-C63-v1', 'information_sufficient': True, 'oracle_executed': True, 'media_consistent': True, 'no_answer_leakage': True}})
            # This exercises exact source extraction; it is not a real-scene acceptance claim.
            template = next(t for t in all_templates() if t['id'] == 'C63-T01')
            record = {'template_id': template['id'], 'provenance': {'kind': 'program', 'path': str(source)}, 'parameters': {p['name']: 'explicit fixture' for p in template['parameters']}, 'provided_information': ['fixture'], 'media': [], 'answer_selector': '/result', 'admission_selector': '/admission', 'oracle_version': 'fixture-v1', 'reference_frame': 'fixture', 'scene_group_id': 'source-family-1'}
            evidence = root/'evidence.jsonl'
            jsonl(evidence, [record])
            runtime = Runtime(root)
            plan = runtime.call('pipeline_plan', {'template_ids': [template['id']], 'target_items': 1, 'evidence': str(evidence), 'split': 'train'})
            produced = runtime.call('pipeline_run', {'plan': plan['plan']})
            self.assertEqual(produced['state'], 'completed')
            second = runtime.call('pipeline_plan', {'template_ids': [template['id']], 'target_items': 1, 'evidence': str(evidence), 'split': 'test'})
            with self.assertRaisesRegex(ValueError, 'cannot cross splits'):
                runtime.call('pipeline_run', {'plan': second['plan']})
            runtime.close()

    def test_remote_wait_resume_reuses_submission_and_composes_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = Runtime(root)
            planned = runtime.call('pipeline_plan', {'pipeline_id': 'scene.capture', 'inputs': {'scene_program_path': '/workspace/scene.json', 'service_config': 'fixture.json'}})
            calls = []
            submission_keys = []
            ready = [False]
            def client(route, arguments, config):
                calls.append(route)
                if route == '/capture':
                    submission_keys.append(arguments['request_key'])
                return {'run_id': 'sf_fixture', 'state': 'SUCCEEDED' if ready[0] else 'RUNNING'} if route == '/inspect' else {'run_id': 'sf_fixture', 'state': 'accepted'}
            result = run({'plan': planned['plan'], '_workspace': str(root)}, root/'execution', client=client)
            self.assertEqual(result['state'], 'waiting')
            ready[0] = True
            final = run({'plan': planned['plan'], 'run': result['run'], '_workspace': str(root)}, root/'resume', client=client)
            self.assertEqual(final['state'], 'completed')
            self.assertEqual(calls.count('/capture'), 1)
            combined = runtime.call('pipeline_plan', {'objective': '组合采集和数据生产', 'inputs': {}, 'steps': [{'id': 'capture', 'uses': 'pipeline', 'pipeline_id': 'scene.capture', 'arguments': {'scene_program_path': '/workspace/scene.json', 'service_config': 'fixture.json'}}, {'id': 'data', 'uses': 'pipeline', 'pipeline_id': 'data.capability', 'arguments': {'selections': [{'template_ids': ['C43-T01'], 'count': 2, 'reason': 'motion rule'}], 'seed': 5, 'split': 'train'}}]})
            composed = run({'plan': combined['plan'], '_workspace': str(root)}, root/'composed', client=client)
            self.assertEqual(composed['state'], 'completed')
            self.assertEqual(composed['outputs']['data']['outputs']['questions']['accepted'], 2)
            independent = run({'plan': combined['plan'], '_workspace': str(root)}, root/'independent', client=client)
            self.assertEqual(independent['state'], 'completed')
            self.assertEqual(len(submission_keys), 3)
            self.assertEqual(len(set(submission_keys)), 3)
            resumed = run({'plan': combined['plan'], 'run': composed['run'], '_workspace': str(root)}, root/'resume-composed', client=client)
            self.assertEqual(resumed['state'], 'completed')
            self.assertEqual(len(submission_keys), 3)
            runtime.close()


if __name__ == '__main__':
    unittest.main()
