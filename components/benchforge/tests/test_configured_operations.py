"""Exercise configured operations without model APIs, model weights or a GPU."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from benchforge_backend.generation import GenerationTools
from benchforge_backend.layout import prepare_layout
from benchforge_backend.model import completion
from benchforge_backend.operator_catalog import _overview
from benchforge_backend.program_submission import read_program_submission
from benchforge_backend.runtime_config import load_service_config
from test_contracts import sample


class ConfiguredOperations(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_layout_uses_configured_weights_and_actual_model_receipt(self):
        (self.root/'models.json').write_text(json.dumps({'models':{'flux':{'path':'weights/chosen-klein','python':'venv/bin/python'}},'sources':{}}))
        config = self.root/'server.json'
        config.write_text(json.dumps({
            'models_config':'models.json',
            'operator_token':'fixture',
            'worker_token':'fixture',
            'execution_mode':'exploration',
        }))
        load_service_config(config)
        tools = GenerationTools(self.root/'artifacts')
        directory = self.root/'task/revision_0'
        directory.mkdir(parents=True)
        observed = []
        def worker(name, request, work, stop):
            observed.append(request)
            Image.new('RGB',(32,24),'tan').save(request['output'])
            return {'status':'ok','model':'chosen-klein'}
        with patch.object(tools, 'execute', side_effect=worker):
            prepare_layout(tools, {'layout':{'mode':'generate','prompt':'A sunny room'}}, directory, threading.Event())
        self.assertEqual(observed[0]['model_path'], str(self.root/'weights/chosen-klein'))
        receipt = json.loads((directory/'layout_reference.json').read_text())
        self.assertEqual(receipt['tool'], 'chosen-klein')
        self.assertFalse(receipt['gt_source'])
        with Image.open(directory/'layout_reference.png') as image:
            self.assertEqual(image.size, (32,24))

    def test_explicit_diffusion_override_does_not_read_missing_model_config(self):
        os.environ['BENCHFORGE_DIFFUSION_MODEL'] = str(self.root/'chosen-weights')
        tools = GenerationTools(self.root/'artifacts')
        directory = self.root/'task/revision_0'
        directory.mkdir(parents=True)
        def worker(name, request, work, stop):
            self.assertEqual(request['model_path'], os.environ['BENCHFORGE_DIFFUSION_MODEL'])
            Image.new('RGB',(24,24),'tan').save(request['output'])
            return {'status':'ok'}
        with patch.object(tools, 'execute', side_effect=worker):
            prepare_layout(tools, {'layout':{'mode':'generate','prompt':'A room'}}, directory, threading.Event())
        self.assertEqual(json.loads((directory/'layout_reference.json').read_text())['tool'], 'chosen-weights')

    def test_catalog_does_not_require_or_invent_a_model(self):
        self.assertEqual(_overview()['model'], 'unconfigured')
        os.environ['BENCHFORGE_MODEL_ID'] = 'my-vision-model'
        self.assertEqual(_overview()['model'], 'my-vision-model')

    def test_model_accepts_base_url_or_complete_endpoint(self):
        os.environ['BENCHFORGE_MODEL_ID'] = 'my-vision-model'
        event = {'choices':[{'delta':{'content':'{"result":"fixture"}'},'finish_reason':'stop'}]}
        wire = ('data: '+json.dumps(event)+'\n\ndata: [DONE]\n').encode()
        for i, url in enumerate(('http://fixture.invalid/v1', 'http://fixture.invalid/v1/chat/completions/')):
            with self.subTest(url=url):
                os.environ['BENCHFORGE_MODEL_URL'] = url
                with patch('benchforge_backend.model.urllib.request.urlopen',return_value=io.BytesIO(wire)) as send:
                    self.assertEqual(completion('Produce JSON.',self.root/str(i)), {'result':'fixture'})
                request = send.call_args.args[0]
                self.assertEqual(request.full_url, 'http://fixture.invalid/v1/chat/completions')
                self.assertEqual(json.loads(request.data)['model'], 'my-vision-model')

    def test_submission_uses_workspace_and_optional_configured_task_root(self):
        artifact = self.root/'artifacts'
        workspace = artifact/'operator_workspaces/test'
        configured = self.root/'custom-tasks'
        for folder in (workspace, configured):
            folder.mkdir(parents=True)
            (folder/'scene.json').write_text(json.dumps(sample()))
        self.assertEqual(read_program_submission(artifact,str(workspace/'scene.json'))['program'],sample())
        with self.assertRaises(ValueError) as error:
            read_program_submission(artifact,str(configured/'scene.json'))
        self.assertNotIn('/home/maqiang',str(error.exception).replace('\\','/'))
        os.environ['BENCHFORGE_TASK_ROOT'] = str(configured)
        self.assertEqual(read_program_submission(artifact,str(configured/'scene.json'))['program'],sample())


if __name__ == '__main__':
    unittest.main()
