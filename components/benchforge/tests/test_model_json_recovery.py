import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchforge_backend.model import completion


def stream(content):
    event={'choices':[{'delta':{'content':content},'finish_reason':'stop'}]}
    return io.BytesIO(('data: '+json.dumps(event)+'\n\ndata: [DONE]\n').encode())


@patch.dict(os.environ, {'BENCHFORGE_MODEL_ID':'fixture-model','BENCHFORGE_MODEL_URL':'http://fixture.invalid/v1'})
class ModelJsonRecoveryTest(unittest.TestCase):
    def test_bounded_scene_review_preserves_valid_rejection_and_handles_length_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('benchforge_backend.model.urllib.request.urlopen',return_value=stream('{"acceptable":false,"issues":["chair is inverted"]}')) as request:
                result=completion('Inspect every view.',tmp,max_tokens=1200,bounded_review=True)
                self.assertFalse(result['acceptable'])
                body=json.loads(request.call_args.args[0].data)
                self.assertTrue(body['stream']);self.assertFalse(body['chat_template_kwargs']['enable_thinking'])
                self.assertEqual(body['max_tokens'],1200)
        with tempfile.TemporaryDirectory() as tmp:
            reply={'choices':[{'delta':{'content':'{"acceptable":false}'},'finish_reason':'length'}]}
            response=io.BytesIO(('data: '+json.dumps(reply)+'\n\ndata: [DONE]\n').encode())
            with patch('benchforge_backend.model.urllib.request.urlopen',return_value=response):
                with self.assertRaisesRegex(ValueError,'incomplete'):completion('Inspect.',tmp,bounded_review=True)

    def test_bounded_disconnect_keeps_partial_evidence_and_does_not_pass(self):
        class Disconnected(io.BytesIO):
            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"{\\"acceptable\\":"}}]}\n'
                raise TimeoutError('connection stalled')
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'revision_0/model_calls/scene_review'
            with patch('benchforge_backend.model.urllib.request.urlopen',return_value=Disconnected()) as request:
                with self.assertRaisesRegex(TimeoutError,'stalled'):
                    completion('Inspect every view.',directory,bounded_review=True)
            self.assertEqual(request.call_count,1)
            saved=json.loads((directory/'response.json').read_text(encoding='utf-8'))
            self.assertFalse(saved['done']);self.assertEqual(saved['content'],'{"acceptable":')
            self.assertEqual(saved['error'],'TimeoutError')
            progress=json.loads((directory.parents[1]/'progress.json').read_text(encoding='utf-8'))
            self.assertEqual(progress['generated_characters'],len(saved['content']))

    def test_invalid_cache_is_preserved_and_valid_rejection_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            original=json.dumps({'done':True,'finish_reason':'stop','content':'{"valid":false,"issues":[\'bad JSON\']}'})
            (directory/'response.json').write_text(original,encoding='utf8')
            with patch('benchforge_backend.model.urllib.request.urlopen',return_value=stream('{"valid":false,"issues":["unclear target"]}')) as request:
                result=completion('Review the image without changing GT.',directory)
                self.assertFalse(result['valid'])
                self.assertEqual(request.call_count,1)
                self.assertEqual(completion('Review the image without changing GT.',directory),result)
                self.assertEqual(request.call_count,1)
            self.assertEqual((directory/'response.json').read_text(encoding='utf8'),original)
            self.assertTrue((directory/'parse_error.json').exists())
            self.assertTrue((directory/'retry_1'/'response.json').exists())

    def test_repeated_malformed_responses_stop_after_three_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('benchforge_backend.model.urllib.request.urlopen',side_effect=lambda *a,**k:stream('{"valid": nope}')) as request:
                with self.assertRaises(json.JSONDecodeError):completion('Review.',tmp)
                self.assertEqual(request.call_count,3)
            self.assertEqual(len(list(Path(tmp).rglob('parse_error.json'))),3)


if __name__=='__main__':unittest.main()
