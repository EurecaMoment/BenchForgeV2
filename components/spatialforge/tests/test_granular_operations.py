"""Task operations use the existing queue and expose composable evidence."""
import json
import os
import threading
from unittest.mock import patch

from spatialforge import engine
from spatialforge.service import start_capture_request, start_generation_request
from spatialforge.operator_evidence import evidence
from spatialforge.observation import observe
from test_program_submission import ProgramSubmission


class GranularOperations(ProgramSubmission):
    def test_standard_workspace_files_are_direct_inputs(self):
        from spatialforge.generation import GenerationTools
        task_root=self.root/'standard-task';task_root.mkdir()
        source=task_root/'program.json';source.write_text(json.dumps(self.program))
        with patch.dict(os.environ,{'SPATIALFORGE_TASK_ROOT':str(task_root)}):
            self.assertEqual(GenerationTools(self.store.root).source_path(str(source)),source)
            result=start_capture_request(self.store,{'request_key':'standard-file','scene_program_path':str(source)})
        task=self.store.snapshot(result['run_id'])['tasks'][0]
        self.assertEqual(task['unit']['submitted_program']['source_path'],str(source))

    def test_capture_generated_asset_skips_model_review(self):
        self.program['objects'][0].update(kind='generated',generation={'prompt':'wood tray'})
        self.save(self.program)
        result=start_capture_request(self.store,{'request_key':'capture-generated','scene_program_path':str(self.path)})
        task=self.store.snapshot(result['run_id'])['tasks'][0]
        mesh=self.path.parent/'mesh.json';mesh.write_text(json.dumps({'vertices':[[0,0,0],[1,1,.1]],'coordinate_frame':'z_up'}))
        with patch.object(engine,'GenerationTools') as tools,patch.object(engine,'completion',side_effect=AssertionError('no planner')),patch.object(engine,'review_generated_asset',side_effect=AssertionError('no asset reviewer')):
            tools.return_value.generate_asset.return_value={'asset_id':'asset_1234567890abcdef'}
            tools.return_value.asset_path.return_value=mesh
            engine.plan_scene(self.store,task,threading.Event())
        self.assertEqual(self.store.snapshot(result['run_id'])['tasks'][0]['unit']['phase'],'capture')

    def test_capture_queues_authored_program_without_layout_or_planner(self):
        result=start_capture_request(self.store,{'request_key':'capture-only','scene_program_path':str(self.path)})
        task=self.store.snapshot(result['run_id'])['tasks'][0]
        self.assertTrue(task['unit']['intent']['capture_only'])
        self.assertNotIn('layout',task['unit']['intent'])
        with patch.object(engine,'completion',side_effect=AssertionError('no model expected')):
            engine.plan_scene(self.store,task,threading.Event())
        current=self.store.snapshot(result['run_id'])['tasks'][0]
        self.assertEqual(current['unit']['phase'],'capture')
        folder=self.store.directory(task['id'],0)
        self.assertFalse((folder/'layout_reference.png').exists())
        self.assertEqual(json.loads((folder/'program.json').read_text()),self.program)

    def test_stage_queue_and_image_evidence_keep_downstream_source_path(self):
        result=start_generation_request(self.store,'diffusion',{'request_key':'image-stage','prompt':'A repair room'})
        task=self.store.snapshot(result['run_id'])['tasks'][0]
        self.assertEqual(task['unit']['phase'],'generation')
        folder=self.store.directory(task['id'],0)
        image=folder/'generation_stage/image.png';image.parent.mkdir();image.write_bytes(b'example')
        stage={'tool':'diffusion','status':'ok','source_path':str(image),'gt_source':False,
               'files':[{'file':'generation_stage/image.png','source_path':str(image),'kind':'image'}]}
        (folder/'generation_stage.json').write_text(json.dumps(stage))
        self.store.update(task['id'],state='SUCCEEDED',result=stage,unit={**task['unit'],'phase':'complete'})
        self.store.settle_runs()
        read=evidence(self.store,task['id'],file='generation_stage/image.png')
        self.assertEqual(read['source_path'],str(image))
        self.assertEqual(read['image_path'],str(image))
        self.assertEqual(evidence(self.store,task['id'])['generation']['files'],stage['files'])
        self.assertEqual(observe(self.store,result['run_id'])['tasks'][0]['result']['source_path'],str(image))
