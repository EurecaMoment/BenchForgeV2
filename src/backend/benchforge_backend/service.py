import argparse
import faulthandler
import signal
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import html
import json
import logging
from pathlib import Path
import threading
import zipfile
from urllib.parse import quote,urlparse,unquote
from .files import safe_path
from .storage import Store,uid
from .engine import coordinate
from .generation import GenerationTools
from .contracts import scene_contract_capabilities
from .capture_transfer import CaptureTransfer,CHUNK_BYTES,validate_capture,decode_chunk
from .program_submission import read_program_submission
from .design import start_design_request,require_prior_reference
from . import scene_requests as _scene_requests
from .scene_requests import context_from_request as _request_context
from .workbench_queries import WORKBENCH_QUERIES, read_connection


scene_intent = _scene_requests.scene_intent


def request_error_status(method, exc):
    if isinstance(exc, FileNotFoundError) or (isinstance(exc, KeyError) and method == 'GET'):
        return 404
    if isinstance(exc, PermissionError):
        return 403
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return 400
    return 500


def gallery_path(run_id):
    return '/gallery/' + quote(str(run_id), safe='')


def start_scene_request(store,value,max_scenes=1000):
    return _scene_requests.start_scene_request(
        store,
        value,
        max_scenes,
        submission_reader=read_program_submission,
        prior_reference_checker=require_prior_reference,
    )


def start_generation_request(store,tool,value):
    from .generation_stage import validate_generation_request
    parameters=validate_generation_request(GenerationTools(store.root),tool,{k:v for k,v in value.items() if k not in {'request_key','context'}})
    intent={'tool':tool,'parameters':parameters}
    kwargs={}
    context=_request_context(value)
    if context is not None:kwargs['context']=context
    rid=store.submit(value['request_key'],[intent],'generation',**kwargs)
    return {'run_id':rid,'task_id':rid+'.scene0','state':'accepted','tool':tool}


def start_capture_request(store,value):
    return _scene_requests.start_capture_request(
        store,
        value,
        submission_reader=read_program_submission,
    )


def refine_scene_request(store,value):
    return _scene_requests.refine_scene_request(
        store,
        value,
        submission_reader=read_program_submission,
        prior_reference_checker=require_prior_reference,
    )


def extend_scene_request(store,value):
    return _scene_requests.extend_scene_request(
        store,
        value,
        submission_reader=read_program_submission,
        prior_reference_checker=require_prior_reference,
    )


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    faulthandler.enable()
    if hasattr(signal,'SIGUSR1'):faulthandler.register(signal.SIGUSR1)
    from .runtime_config import load_service_config
    config=load_service_config(args.config)
    store=Store(config['artifacts'],config.get('harness'),config.get('database_url'))
    transfer=CaptureTransfer(store)
    stop=threading.Event()
    # Recover only FIT stages; desktop stages require the same worker to reconcile.
    for task in store.all_work():
        if task['state']=='RUNNING' and task['unit']['phase'] in {'plan','review','asset','dataset','layout','generation'}:store.update(task['id'],state='PENDING')
    thread=threading.Thread(target=coordinate,args=(store,stop),daemon=True);thread.start()

    class Handler(BaseHTTPRequestHandler):
        def fail(self, exc):
            status = request_error_status(self.command, exc)
            if status == 500:
                logging.getLogger('benchforge_backend.service').exception(
                    'request failed method=%s path=%s run_id=%s task_id=%s',
                    self.command, urlparse(self.path).path,
                    getattr(self, 'request_run_id', None),
                    getattr(self, 'request_task_id', None),
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
            detail = str(exc)[:1000] if status < 500 else 'Internal server error'
            self.reply({'error': type(exc).__name__, 'detail': detail}, status)

        def reply(self,value,status=200):
            data=json.dumps(value,ensure_ascii=False,default=str).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def binary(self,data,mime='application/zip'):
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            # Localhost gallery exposes only generated public imagery, never secrets or GT.
            try:
                path=unquote(urlparse(self.path).path)
                if path.startswith('/image/'):
                    file=safe_path(Path(config['artifacts']),path[len('/image/'):],must_exist=True)
                    if file.suffix.lower()!='.png':raise ValueError('only public PNG imagery')
                    data=file.read_bytes();mime='image/png'
                elif path.startswith('/gallery/'):
                    rid=path[len('/gallery/'):];self.request_run_id = rid;snap=store.snapshot(rid)
                    sections=[]
                    for task in snap['tasks']:
                        folder=store.directory(task['id'],task['unit']['revision'])
                        pics=sorted(folder.glob('capture/view_*.png'))
                        images=''.join('<a href="/image/'+p.relative_to(Path(config['artifacts'])).as_posix()+'"><img src="/image/'+p.relative_to(Path(config['artifacts'])).as_posix()+'"></a>' for p in pics)
                        result=task.get('result') or task.get('failure') or {'phase':task['unit']['phase']}
                        sections.append('<section><h2>'+html.escape(task['unit']['intent'].get('name',task['id']))+'</h2><p>'+html.escape(task['state'])+' · revision '+str(task['unit']['revision'])+'</p><div class="views">'+images+'</div><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></section>')
                    body='<html><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>BenchForge</title><style>body{background:#111827;color:#e5e7eb;font:16px system-ui;margin:32px}h1{color:#67e8f9}.views{display:flex;gap:12px;flex-wrap:wrap}.views img{width:400px;border-radius:8px}section{padding:20px;background:#1f2937;margin:16px 0;border-radius:12px}pre{white-space:pre-wrap;font-size:13px}</style><h1>BenchForge · 真实生产产物</h1><p>'+html.escape(rid)+' · '+snap['state']+'</p>'+''.join(sections)+'</html>'
                    data=body.encode();mime='text/html; charset=utf-8'
                else:self.reply({'name':'BenchForge','message':'Use /gallery/<run_id>'},404);return
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except Exception as exc:self.fail(exc)
        def do_POST(self):
            role='worker' if self.path.startswith('/worker/') else 'operator'
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+config[role+'_token']):self.reply({'error':'unauthorized'},401);return
            if self.path == '/dataset':
                self.reply({
                    'error':'Legacy dataset jobs are retired. Use data.capability or POST /start with target_items.',
                },410)
                return
            try:
                length=int(self.headers.get('Content-Length','0'))
                limit=CHUNK_BYTES if self.path=='/worker/upload-chunk' else 250*1024*1024 if self.path=='/worker/upload' else 2*1024*1024
                if self.path in WORKBENCH_QUERIES:
                    limit = 4096
                if length<0 or length>limit:raise ValueError('request size exceeds endpoint limit')
                raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('incomplete request body')
                if self.path=='/worker/upload-chunk':
                    job=json.loads(self._upload_header('Job'))
                    self.request_task_id = job.get('task_id')
                    chunk=decode_chunk(raw,self._upload_header('Encoding','identity'))
                    self.reply(transfer.chunk(job,self._upload_header('File'),int(self._upload_header('Offset')),chunk));return
                if self.path=='/worker/upload':
                    job=json.loads(self._upload_header('Job'))
                    self.request_task_id = job.get('task_id')
                    directory=Path(config['artifacts'])/'staging'/uid('upload');directory.mkdir(parents=True)
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        if len(archive.infolist())>100 or sum(x.file_size for x in archive.infolist())>500*1024*1024:raise ValueError('capture bundle too large')
                        for member in archive.infolist():
                            target=safe_path(directory,member.filename)
                            if member.is_dir() or (member.external_attr>>16)&0o170000==0o120000:raise ValueError('unsupported archive member')
                            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(member))
                    validate_capture(directory,job,store)
                    self.reply(store.commit_capture(job,directory));return
                value=json.loads(raw or b'{}')
                self.request_run_id = value.get('run_id') if isinstance(value, dict) else None
                self.request_task_id = value.get('task_id') if isinstance(value, dict) else None
                from .scene_acceptance import check_request
                check_request(store.root,self.path,value)
                if self.path in WORKBENCH_QUERIES:
                    with read_connection(store.repo.engine) as connection:
                        result = WORKBENCH_QUERIES[self.path](connection, value)
                    self.reply(result)
                elif self.path=='/catalog':
                    from .operator_catalog import catalog_response
                    self.reply(catalog_response(store,value))
                elif self.path=='/layout':
                    self.reply(start_design_request(store,value))
                elif self.path in {'/diffusion','/sam3','/trellis','/depth','/mesh-import'}:
                    tool=self.path[1:].replace('-', '_')
                    self.reply(start_generation_request(store,tool,value))
                elif self.path=='/start':
                    self.reply(start_scene_request(store,value,config.get('max_scenes_per_run',1000)))
                elif self.path=='/capture':
                    self.reply(start_capture_request(store,value))
                elif self.path=='/preview':
                    from .geometry_preview import preview_scene_geometry
                    program=read_program_submission(store.root,value['scene_program_path'])['program']
                    def mesh(asset_id):
                        return json.loads(GenerationTools(store.root).asset_path(asset_id,'mesh.json').read_text())
                    self.reply(preview_scene_geometry(program,mesh_loader=mesh))
                elif self.path=='/asset':
                    intent=value['intent']
                    if not isinstance(intent,dict) or not {'name','description'}<=set(intent) or set(intent)-{'name','description','label','source_image','source_mask','source_mesh','source_gaussian','asset_id','seed','source_up_axis','size_hint_m','subject_box','edit_reference'}:raise ValueError('invalid asset intent')
                    if not isinstance(intent['description'],str) or not 1<=len(intent['description'])<=12000:raise ValueError('invalid asset description')
                    context=_request_context(value)
                    kwargs={'context':context} if context is not None else {}
                    self.reply({'run_id':store.submit(value['request_key'],[intent],'asset',**kwargs),'state':'accepted'})
                elif self.path=='/extend':
                    self.reply(extend_scene_request(store,value))
                elif self.path=='/refine':
                    self.reply(refine_scene_request(store,value))
                elif self.path=='/observe':
                    from .observation import observe
                    result=observe(store,value['run_id']);result.pop('cursor')
                    self.reply(result)
                elif self.path=='/wait':
                    from .observation import wait_for_change
                    result=wait_for_change(store,value['run_id'],None,value.get('timeout_seconds',60),stop)
                    result.pop('cursor');self.reply(result)
                elif self.path=='/task-code':
                    from .task_workspace import run_task_code
                    self.reply(run_task_code(store.root,value['workspace_id'],value['code'],value.get('timeout_seconds',60)))
                elif self.path=='/evidence':
                    from .operator_evidence import evidence
                    self.reply(evidence(store,value['task_id'],value.get('revision'),value.get('file'),value.get('workspace_id')))
                elif self.path=='/retry':self.reply(store.retry(value['task_id'],value.get('feedback'),value.get('capture_mode','auto')))
                elif self.path=='/download':
                    task_id=value['task_id'];snap=store.snapshot(task_id.split('.')[0]);task=next(t for t in snap['tasks'] if t['id']==task_id)
                    directory=store.root/task_id/('revision_'+str(value.get('revision',task['unit']['revision'])));file=safe_path(directory,value['file'],must_exist=True)
                    if file.suffix not in {'.zip','.json','.jsonl','.usda','.glb','.png','.jpg','.jpeg','.npy','.npz','.ply','.obj','.gltf','.bin','.mp4'}:raise ValueError('unsupported artifact download')
                    self.binary(file.read_bytes(),'application/octet-stream')
                elif self.path=='/worker/asset':
                    from .contracts import ident
                    asset_id=ident(value['asset_id']);folder=safe_path(store.root/'generated_assets',asset_id)
                    if not folder.is_dir() or not (folder/'mesh.json').is_file():raise ValueError('registered asset directory unavailable')
                    bundle=io.BytesIO()
                    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
                        for path in folder.rglob('*'):
                            if path.is_file() and path.suffix.lower() in {'.json','.glb','.png','.jpg','.jpeg','.exr','.bin','.npz'}:
                                archive.write(path,path.relative_to(folder).as_posix())
                    self.binary(bundle.getvalue())
                elif self.path=='/inspect':
                    state=store.snapshot(value['run_id'])
                    self.reply({'run_id':value['run_id'],'state':state['state'],'gallery_url':gallery_path(value['run_id']),'tasks':[{**{k:t.get(k) for k in ('id','state','unit','result','failure')},'downloads':[p.relative_to(store.directory(t['id'],t['unit']['revision'])).as_posix() for p in store.directory(t['id'],t['unit']['revision']).glob('release/*.zip')]} for t in state['tasks']]})
                elif self.path=='/cancel':store.cancel(value['run_id']);self.reply({'cancel_requested':True})
                elif self.path=='/worker/claim':self.reply(store.claim_desktop(value['worker_id']))
                elif self.path=='/worker/heartbeat':
                    # Older dispatchers omitted revision; preserve their cancellation check during rollout.
                    if 'revision' not in value:
                        snap=store.snapshot(value['task_id'].split('.')[0]);self.reply({'cancel':snap['state']=='CANCELED'})
                    else:self.reply(store.worker_update({**{k:value[k] for k in ('task_id','revision','token')},'transport_retry':value.get('transport_retry',0)},progress=value.get('progress')))
                elif self.path=='/worker/finish':self.reply(store.worker_update(value['job'],outcome=value['outcome'],processes_stopped=value.get('processes_stopped'),error=value.get('error'),capture_complete=value.get('capture_complete'),capture_receipt=value.get('capture_receipt')))
                elif self.path=='/worker/upload-begin':self.reply(transfer.begin(value['job'],value['files']))
                elif self.path=='/worker/upload-commit':self.reply(transfer.commit(value['job']))
                else:self.reply({'error':'unknown operation'},404)
            except Exception as exc:self.fail(exc)
        def _upload_header(self, name, default=None):
            return self.headers.get(f'X-BenchForge-{name}', self.headers.get(f'X-SpatialForge-{name}', default))

    server=ThreadingHTTPServer(('127.0.0.1',config.get('port',3841)),Handler)
    try:server.serve_forever()
    finally:stop.set();server.server_close()


if __name__=='__main__':main()
