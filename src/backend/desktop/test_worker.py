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


def native_capture(directory,job):
    job.setdefault('program',{'scene_id':'frozen_fixture','objects':[],'cameras':[{}]})
    job.setdefault('capture_options',{'view_indices':[0],'export_scene':False})
    output=directory/'capture';output.mkdir(parents=True,exist_ok=True)
    (directory/'request.json').write_text(json.dumps(job))
    (output/'report.json').write_text(json.dumps({'status':'captured','token':job['token']}))
    (output/'evidence.json').write_text(json.dumps({'origin':'isaac_native','token':job['token']}))
    for suffix in ('.png','.json','_depth.npy','_semantic.npy','_instance.npy'):
        (output/('view_0'+suffix)).write_bytes(b'isolated fixture')
    return output


class WorkerTests(unittest.TestCase):
    def test_upload_failures_are_bounded_and_preserve_native_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            output=native_capture(directory,job)
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
            pending=json.loads((directory/'finish_pending.json').read_text())
            self.assertTrue(pending['capture_complete'])
            self.assertEqual(pending['capture_receipt']['program'],job['program'])

    def test_finish_refuses_to_release_active_owned_process(self):
        class Process:
            def close(self):pass
        with tempfile.TemporaryDirectory() as temp,patch.object(worker,'config',{'isaac_mode':'local'}),patch.object(worker,'owned_processes',return_value=[Process()]),patch.object(worker,'api') as api:
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
            self.assertFalse(worker.owns_command({'CommandLine':f'python "{script}" --request "{request}.other"'},request))

    @unittest.skipUnless(worker.os.name=='nt','Windows short-path aliases')
    def test_short_path_request_is_owned_and_recovered(self):
        import ctypes
        with tempfile.TemporaryDirectory(prefix='benchforge long path ') as directory:
            state=Path(directory).resolve()
            previous={'token':'attempt_0123456789abcdef'}
            request=state/previous['token']/'request.json'
            request.parent.mkdir();request.write_text(json.dumps(previous))
            buffer=ctypes.create_unicode_buffer(32768)
            if not ctypes.windll.kernel32.GetShortPathNameW(str(state),buffer,len(buffer)):
                self.skipTest('This volume does not provide short-path aliases')
            alias=Path(buffer.value)/previous['token']/'request.json'
            row={'CommandLine':f'python "{worker.root / "desktop/isaac_capture.py"}" --request "{alias}"'}
            self.assertTrue(worker.owns_command(row,request))
            with patch.object(worker,'state_root',state,create=True),patch.object(worker,'owned_processes',return_value=[object()]),patch.object(worker,'wait_owned') as wait:
                worker.recover_other_attempts({'token':'attempt_fedcba9876543210'},[row])
                wait.assert_called_once_with(previous,request.parent,[unittest.mock.ANY])

    def test_recovered_attempt_never_launches_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            worker.state_root=Path(directory);worker.config={'isaac_mode':'local'}
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            capture=Path(directory)/job['token']/'capture'
            def settled(*args):
                native_capture(capture.parent,job)
            with patch.object(worker,'process_snapshot',return_value=[]),patch.object(worker,'recover_other_attempts'),patch.object(worker,'owned_processes',side_effect=[[object()],[]]),patch.object(worker,'wait_owned',side_effect=settled) as wait,patch.object(worker,'api',return_value={'committed':True}),patch.object(worker.subprocess,'Popen',side_effect=AssertionError('duplicate capture launch')):
                worker.run_job(job)
            self.assertEqual(wait.call_count,1)
            self.assertTrue((capture.parent/'commit.json').exists())

    def test_resumed_complete_capture_skips_old_failed_resident_and_finish_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            directory=state/job['token'];native_capture(directory,job)
            receipt=worker.local_capture_receipt(job,directory)
            (directory/'finish_pending.json').write_text(json.dumps({'outcome':'failed','transport_retry':0,'error':'old device loss'}))
            (directory/'resident.json').write_text(json.dumps({'token':job['token'],'started_at':worker.time.time()}))
            failure=json.dumps({'token':job['token'],'state':'failed','error':'old device loss'})
            (directory/'resident_result.json').write_text(failure)
            resumed={**job,'transport_retry':1,'capture_recovery_mode':'resume_upload','capture_resume_receipt':receipt}
            with patch.object(worker,'state_root',state),patch.object(worker,'config',{'isaac_mode':'local'}),patch.object(worker,'process_snapshot',return_value=[]), \
                 patch.object(worker,'recover_other_attempts'),patch.object(worker,'owned_processes',return_value=[]), \
                 patch.object(worker,'run_resident',side_effect=AssertionError('replayed failed resident')), \
                 patch.object(worker,'api',return_value={'committed':True}) as api, \
                 patch.object(worker.subprocess,'Popen',side_effect=AssertionError('duplicate native capture')):
                worker.run_job(resumed)
            self.assertEqual(api.call_args[0][0],'/worker/upload-begin')
            self.assertEqual((directory/'resident_result.json').read_text(),failure)
            self.assertEqual(json.loads((directory/'finish_pending.json').read_text())['transport_retry'],0)

    def test_frozen_request_change_or_missing_frame_cannot_claim_complete_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            native_capture(directory,job)
            changed={**job,'program':{**job['program'],'scene_id':'different_scene'}}
            (directory/'request.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'frozen program'):
                worker.local_capture_receipt(job,directory)
            (directory/'request.json').write_text(json.dumps(job))
            (directory/'capture/view_0_depth.npy').unlink()
            with patch.object(worker,'owned_processes',return_value=[]),patch.object(worker,'api',return_value={'finished':True}) as api:
                worker.finish_job(job,directory,'failed','upload failed')
            payload=api.call_args[0][1]
            self.assertFalse(payload['capture_complete']);self.assertIsNone(payload['capture_receipt'])


if __name__=='__main__':unittest.main()
