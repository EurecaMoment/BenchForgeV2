"""Narrow dispatcher regressions; no Isaac process or service is started."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec=importlib.util.spec_from_file_location('desktop_worker',Path(__file__).with_name('worker.py'))
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)


def asset_zip():
    value=io.BytesIO()
    with zipfile.ZipFile(value,'w') as archive:archive.writestr('mesh.json','{"vertices":[],"faces":[],"colors":[]}')
    return value.getvalue()


class WorkerTests(unittest.TestCase):
    def test_upload_failures_are_bounded_and_preserve_native_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);output=directory/'capture';output.mkdir()
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            (output/'report.json').write_text('{"status":"failed"}')
            calls=[]
            def call(path,*args,**kwargs):
                calls.append(path)
                if path=='/worker/finish':return {'finished':True,'state':'FAILED_FINAL'}
                raise OSError('connection dropped')
            with patch.object(worker,'api',side_effect=call),patch.object(worker,'owned_processes',return_value=[]),patch.object(worker.time,'sleep'):
                result=worker.upload_capture(job,directory,output)
            self.assertEqual(calls.count('/worker/upload-begin'),5)
            self.assertEqual(calls.count('/worker/finish'),1)
            self.assertTrue(result['finished']);self.assertTrue((output/'report.json').exists())
            self.assertEqual(json.loads((directory/'transport.json').read_text())['errors'],5)

    def test_finish_refuses_to_release_active_owned_process(self):
        class Process:
            def close(self):pass
        with tempfile.TemporaryDirectory() as temp,patch.object(worker,'owned_processes',return_value=[Process()]),patch.object(worker,'api') as api:
            with self.assertRaisesRegex(RuntimeError,'processes remain'):worker.finish_job({'token':'t','task_id':'r.t','revision':0},Path(temp),'failed')
            api.assert_not_called()

    def test_archive_cannot_write_above_cache(self):
        value=io.BytesIO()
        with zipfile.ZipFile(value,'w') as archive:archive.writestr('../outside.json','{}')
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(io.BytesIO(value.getvalue())) as archive:
                with self.assertRaises(ValueError):worker.extract_asset(archive,Path(directory)/'asset')
            self.assertFalse((Path(directory)/'outside.json').exists())

    def test_downloaded_asset_reused_without_second_request(self):
        with tempfile.TemporaryDirectory() as directory:
            worker.state_root=Path(directory)
            worker.config={'url':'http://localhost:3841','worker_token':'test'}
            job={'assets':['asset_test'],'program':{'objects':[{'kind':'mesh','asset_id':'asset_test'}]}}
            with patch.object(worker.urllib.request,'urlopen',return_value=io.BytesIO(asset_zip())) as request:
                first=worker.prepare_assets(job);second=worker.prepare_assets(job)
            self.assertEqual(request.call_count,1)
            self.assertEqual(first['asset_paths'],second['asset_paths'])
            self.assertTrue(Path(first['asset_paths']['asset_test']).is_file())

    def test_ownership_requires_both_executor_and_exact_attempt_request(self):
        with tempfile.TemporaryDirectory() as directory:
            request=Path(directory)/'attempt_1'/'request.json'
            script=str(worker.root/'desktop/isaac_capture.py')
            matching={'CommandLine':f'python "{script}" --request "{request}"'}
            self.assertTrue(worker.owns_command(matching,request))
            self.assertFalse(worker.owns_command({'CommandLine':f'python other.py --request "{request}"'},request))
            self.assertFalse(worker.owns_command({'CommandLine':f'python "{script}" --request "{request.parent.parent}/attempt_2/request.json"'},request))

    def test_recovered_attempt_never_launches_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            worker.state_root=Path(directory);worker.config={}
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            capture=Path(directory)/job['token']/'capture'
            def settled(*args):
                capture.mkdir(parents=True)
                (capture/'report.json').write_text(json.dumps({'status':'captured','token':job['token']}))
            with patch.object(worker,'process_snapshot',return_value=[]),patch.object(worker,'recover_other_attempts'),patch.object(worker,'owned_processes',side_effect=[[object()],[]]),patch.object(worker,'wait_owned',side_effect=settled) as wait,patch.object(worker,'api',return_value={'committed':True}),patch.object(worker.subprocess,'Popen',side_effect=AssertionError('duplicate capture launch')):
                worker.run_job(job)
            self.assertEqual(wait.call_count,1)
            self.assertTrue((capture.parent/'commit.json').exists())


if __name__=='__main__':unittest.main()
