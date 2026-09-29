import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spatialforge.model import completion


def stream(content):
    event={'choices':[{'delta':{'content':content},'finish_reason':'stop'}]}
    return io.BytesIO(('data: '+json.dumps(event)+'\n\ndata: [DONE]\n').encode())


class ModelJsonRecoveryTest(unittest.TestCase):
    def test_invalid_cache_is_preserved_and_valid_rejection_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            original=json.dumps({'done':True,'finish_reason':'stop','content':'{"valid":false,"issues":[\'bad JSON\']}'})
            (directory/'response.json').write_text(original,encoding='utf8')
            with patch('spatialforge.model.urllib.request.urlopen',return_value=stream('{"valid":false,"issues":["unclear target"]}')) as request:
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
            with patch('spatialforge.model.urllib.request.urlopen',side_effect=lambda *a,**k:stream('{"valid": nope}')) as request:
                with self.assertRaises(json.JSONDecodeError):completion('Review.',tmp)
                self.assertEqual(request.call_count,3)
            self.assertEqual(len(list(Path(tmp).rglob('parse_error.json'))),3)


if __name__=='__main__':unittest.main()
