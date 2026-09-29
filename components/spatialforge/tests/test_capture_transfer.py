import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zlib
from unittest.mock import patch
from spatialforge.capture_transfer import CaptureTransfer, validate_manifest, validate_capture, MAX_FILE_BYTES, decode_chunk, CHUNK_BYTES

JOB={'task_id':'sf_test.scene0','revision':0,'token':'attempt_0123456789abcdef'}


class TransferTests(unittest.TestCase):
    def test_binary_payload_required_only_for_crate_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            class Store:
                def directory(self,*args):return root
            (root/'program.json').write_text('{"cameras":[]}')
            (root/'scene.usda').write_text('#usda 1.0\n')
            (root/'evidence.json').write_text('{}')
            report={'token':JOB['token'],'status':'captured'}
            (root/'report.json').write_text(json.dumps(report))
            validate_capture(root,JOB,Store())
            report['scene_format']='usdc'
            (root/'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'incomplete native capture'):validate_capture(root,JOB,Store())
            (root/'scene.usdc').write_bytes(b'PXR-USDC')
            validate_capture(root,JOB,Store())
            report['scene_resources']=[{'file':'scene_resource_000.hdr','source':'D:/library/sky.hdr'}]
            (root/'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'incomplete native capture'):validate_capture(root,JOB,Store())
            (root/'scene_resource_000.hdr').write_bytes(b'hdr fixture')
            validate_capture(root,JOB,Store())
            files=[{'name':name,'size':1,'mtime_ns':1} for name in ('report.json','scene_resource_000.hdr','scene_resource_001.jpg','scene_resource_002.exr','scene_resource_003.mdl')]
            self.assertEqual(validate_manifest(files),files)

    def test_compression_is_bounded_and_truncated_payload_is_rejected(self):
        raw=b'0.1, 2.3, 4.5, '*100
        self.assertEqual(decode_chunk(zlib.compress(raw),'deflate'),raw)
        with self.assertRaises(ValueError):decode_chunk(zlib.compress(b' '* (CHUNK_BYTES+1)),'deflate')
        with self.assertRaises(ValueError):decode_chunk(zlib.compress(raw)[:-2],'deflate')

    def test_desktop_resumes_after_server_writes_chunk_but_reply_is_lost(self):
        spec=importlib.util.spec_from_file_location('transfer_desktop_worker',Path(__file__).resolve().parents[1]/'desktop/worker.py')
        worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)/'server'
                def worker_update(self,*args,**kwargs):return {'active':True}
                def commit_capture(self,job,data):return {'committed':True}
            store=Store();transfer=CaptureTransfer(store)
            directory=Path(temp)/'desktop';output=directory/'capture';output.mkdir(parents=True)
            raw=json.dumps({'status':'failed','token':JOB['token']}).encode()
            (output/'report.json').write_bytes(raw)
            (output/'scene.usda').write_bytes(b'#usda 1.0\n'+b' '*80)
            lost=False;resumed=[];encodings=[]
            def api(path,value=None,data=None,headers=None):
                nonlocal lost
                if path=='/worker/upload-begin':
                    result=transfer.begin(value['job'],value['files']);resumed.append(result['offsets']['report.json'])
                    return {**result,'chunk_bytes':32}
                if path=='/worker/upload-chunk':
                    encodings.append(headers['X-SpatialForge-Encoding'])
                    result=transfer.chunk(json.loads(headers['X-SpatialForge-Job']),headers['X-SpatialForge-File'],int(headers['X-SpatialForge-Offset']),decode_chunk(data,headers['X-SpatialForge-Encoding']))
                    if not lost:lost=True;raise OSError('lost reply after write')
                    return result
                if path=='/worker/heartbeat':return {'active':True}
                if path=='/worker/upload-commit':return transfer.commit(value['job'])
                raise AssertionError(path)
            with patch.object(worker,'api',side_effect=api),patch.object(worker.time,'sleep'):
                result=worker.upload_capture(JOB,directory,output)
            self.assertTrue(result['committed']);self.assertEqual(resumed,[0,32]);self.assertIn('deflate',encodings)
            self.assertEqual((store.root/'transfers'/JOB['token']/'capture/report.json').read_bytes(),raw)

    def test_disconnect_resume_duplicate_conflict_and_incomplete_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                committed=False
                def worker_update(self,job,**kwargs):return {'committed':True} if self.committed else {'active':True}
                def commit_capture(self,job,data):
                    self.committed=True
                    return {'committed':True}
            store=Store();transfer=CaptureTransfer(store)
            raw=json.dumps({'status':'failed','token':JOB['token']}).encode()
            files=[{'name':'report.json','size':len(raw),'mtime_ns':1}]
            self.assertEqual(transfer.begin(JOB,files)['offsets']['report.json'],0)
            transfer.chunk(JOB,'report.json',0,raw[:12])
            # Lost response and server restart reuse durable files.
            transfer=CaptureTransfer(store)
            self.assertEqual(transfer.begin(JOB,files)['offsets']['report.json'],12)
            self.assertEqual(transfer.chunk(JOB,'report.json',0,raw[:12])['offset'],12)
            with self.assertRaisesRegex(ValueError,'conflicting'):transfer.chunk(JOB,'report.json',0,b'bad')
            with self.assertRaisesRegex(ValueError,'incomplete'):transfer.commit(JOB)
            transfer.chunk(JOB,'report.json',12,raw[12:])
            self.assertTrue(transfer.commit(JOB)['committed'])
            self.assertTrue(transfer.commit(JOB)['committed'])

    def test_limits_traversal_and_known_large_scene_before_transfer(self):
        normal={'name':'report.json','size':20,'mtime_ns':1}
        files=[normal,{'name':'scene.usda','size':670070581,'mtime_ns':1}]
        self.assertEqual(len(validate_manifest(files)),2)
        for other in ({'name':'../scene.usda','size':10,'mtime_ns':1}, {'name':'scene.usda','size':MAX_FILE_BYTES+1,'mtime_ns':1},normal):
            with self.assertRaises(ValueError):validate_manifest([normal,other])
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def worker_update(self,*args,**kwargs):raise AssertionError('capacity must be checked before acquiring transfer')
            with self.assertRaises(ValueError):CaptureTransfer(Store()).begin(JOB,[normal,{'name':'large.usda','size':MAX_FILE_BYTES+1,'mtime_ns':1}])
            self.assertFalse((Path(temp)/'transfers').exists())

    def test_cancellation_stops_transfer_without_requiring_big_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def worker_update(self,*args,**kwargs):return {'cancel':True}
            transfer=CaptureTransfer(Store())
            self.assertTrue(transfer.begin(JOB,[{'name':'report.json','size':20,'mtime_ns':1}])['cancel'])
            self.assertTrue(transfer.chunk(JOB,'report.json',0,b'abc')['cancel'])
            self.assertFalse((Path(temp)/'transfers').exists())


if __name__=='__main__':unittest.main()
