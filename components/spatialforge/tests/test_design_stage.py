"""Reference-first handoff with real files and isolated DB, no model or GPU."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from spatialforge import design, engine
from spatialforge.layout import validate_layout, prepare_layout
from spatialforge.observation import observe
from spatialforge.operator_evidence import evidence
from spatialforge.service import start_scene_request
import test_program_submission as fixtures


class DesignStage(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProgramSubmission()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.request = {'request_key': 'design-test', 'name': 'workshop', 'description': 'A photographic workshop with daylight'}

    def tearDown(self):
        self.fixture.tearDown()

    def start(self):
        response = design.start_design_request(self.store, self.request)
        task = self.store.snapshot(response['run_id'])['tasks'][0]
        return response, task

    def finish(self, task):
        class Tools:
            calls = []
            def execute(self, name, request, work, stop):
                self.calls.append(name)
                Image.new('RGB', (64, 48), 'tan').save(request['output'])
        tools = Tools()
        with patch.object(design, 'GenerationTools', return_value=tools):
            design.execute_design(self.store, task, threading.Event())
            # A replay uses the frozen receipt, not another diffusion call.
            design.execute_design(self.store, task, threading.Event())
        self.store.settle_runs()
        self.assertEqual(tools.calls, ['diffusion'])

    def test_program_without_reference_is_queued_with_pipeline_design(self):
        intent = deepcopy(self.fixture.intent)
        intent.pop('layout')
        run = start_scene_request(self.store, {'request_key': 'pipeline-design', 'intents': [intent]})
        task = self.store.snapshot(run['run_id'])['tasks'][0]
        self.assertEqual(task['unit']['intent']['layout']['mode'], 'generate')
        self.assertEqual(task['unit']['submitted_program']['program'], self.fixture.program)


    def test_design_is_durable_idempotent_and_not_simulator_success(self):
        response, task = self.start()
        self.assertEqual(task['unit']['phase'], 'layout')
        self.assertEqual(self.start()[0]['run_id'], response['run_id'])
        with self.assertRaisesRegex(ValueError, 'different request'):
            design.start_design_request(self.store, {**self.request, 'description': 'different'})
        self.finish(task)
        status = observe(self.store, response['run_id'])
        self.assertTrue(status['terminal'])
        row = status['tasks'][0]
        self.assertTrue(row['design_reference_ready'])
        self.assertNotIn('quality', row)
        self.assertFalse(row['design']['gt_source'])
        self.assertFalse(row['design']['simulator_capture'])
        self.assertIn('layout/reference.png', [x['file'] for x in evidence(self.store, task['id'])['layout_files']])
        self.assertTrue(Path(evidence(self.store, task['id'], file='layout/reference.png')['image_path']).is_file())

    def test_completed_design_reused_before_unchanged_program_handoff(self):
        _, task = self.start(); self.finish(task)
        intent = deepcopy(self.fixture.intent)
        intent['layout'] = {'mode': 'reference', 'design_task_id': task['id']}
        origin = design.design_directory(self.store, intent['layout'])
        source_bytes = (origin / 'layout_reference.png').read_bytes()
        run = start_scene_request(self.store, {'request_key': 'scene-after-design', 'intents': [intent]})
        scene = self.store.snapshot(run['run_id'])['tasks'][0]
        with patch.object(engine, 'completion', side_effect=AssertionError('must preserve authored scene')), patch('spatialforge.generation.GenerationTools.execute', side_effect=AssertionError('must not generate again')):
            engine.plan_scene(self.store, scene, threading.Event())
        directory = self.store.directory(scene['id'], 0)
        self.assertEqual(json.loads((directory / 'program.json').read_text()), self.fixture.program)
        self.assertEqual((directory / 'layout_reference.png').read_bytes(), source_bytes)
        self.assertEqual((origin / 'layout_reference.png').read_bytes(), source_bytes)
        receipt = json.loads((directory / 'layout_reference.json').read_text())
        self.assertEqual(receipt['prepared_from']['design_task_id'], task['id'])
        self.assertEqual(receipt['prepared_from']['reference_receipt']['tool'], 'FLUX.2-klein-9B')
        self.assertFalse(receipt['gt_source'])
        self.assertTrue(json.loads((directory / 'program_handoff.json').read_text())['exact_program_match'])
        self.assertFalse((directory / 'capture').exists())

    def test_pending_or_wrong_workflow_reference_does_not_queue_scene(self):
        _, task = self.start()
        intent = deepcopy(self.fixture.intent)
        intent['layout'] = {'mode': 'reference', 'design_task_id': task['id']}
        with self.assertRaisesRegex(ValueError, 'not complete'):
            start_scene_request(self.store, {'request_key': 'pending-ref', 'intents': [intent]})
        plain = self.fixture.submit()
        intent['layout']['design_task_id'] = plain['id']
        with self.assertRaisesRegex(ValueError, 'spatialforge_layout task'):
            start_scene_request(self.store, {'request_key': 'wrong-ref', 'intents': [intent]})
        for value in ({'mode':'reference','design_task_id':'../other'}, {'mode':'generate','design_task_id':task['id']}, {'mode':'reference','design_task_id':task['id'],'source_image':'x'}):
            with self.assertRaises(ValueError): validate_layout(value)


if __name__ == '__main__': unittest.main()
