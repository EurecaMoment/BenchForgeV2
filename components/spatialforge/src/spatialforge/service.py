import argparse
import faulthandler
import signal
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import html
import json
from pathlib import Path
import threading
import zipfile
from urllib.parse import urlparse,unquote
from benchclaw.store import safe_path
from .storage import Store,uid
from .engine import coordinate
from .generation import GenerationTools
from .contracts import scene_contract_capabilities
from .layout import validate_layout,default_layout
from .capture_transfer import CaptureTransfer,CHUNK_BYTES,validate_capture,decode_chunk
from .program_submission import read_program_submission
from .design import start_design_request,require_prior_reference
from .capture_scope import capture_scope


def scene_intent(intent):
    if not isinstance(intent,dict) or not {'name','description','split'}<=set(intent):raise ValueError('scene requires name, description, split')
    if set(intent)-{'name','description','split','target_items','layout','scene_program_path'}:raise ValueError('unknown scene intent fields')
    if 'scene_program_path' in intent and (not isinstance(intent['scene_program_path'],str) or not intent['scene_program_path']):raise ValueError('scene_program_path must be a task JSON source_path')
    if 'layout' in intent:validate_layout(intent['layout'])
    if intent['split'] not in {'train','dev'} or not isinstance(intent['description'],str) or not 1<=len(intent['description'])<=12000:raise ValueError('invalid scene intent')
    if not isinstance(intent['name'],str) or not 1<=len(intent['name'])<=200:raise ValueError('invalid name')
    if type(intent.get('target_items',24)) is not int or not 1<=intent.get('target_items',24)<=1000:raise ValueError('invalid target item budget')
    return intent


def start_scene_request(store,value,max_scenes=1000):
    intents=value['intents']
    if not isinstance(intents,list) or not 1<=len(intents)<=max_scenes:raise ValueError('scene count exceeds registered run budget')
    for intent in intents:scene_intent(intent)
    submissions=[read_program_submission(store.root,intent['scene_program_path']) if 'scene_program_path' in intent else None for intent in intents]
    for intent in intents:require_prior_reference(store,intent)
    intents=[{**intent,'layout':intent.get('layout') or default_layout(intent)} for intent in intents]
    return {'run_id':store.submit(value['request_key'],intents,submitted_programs=submissions if any(submissions) else None),'state':'accepted','program_handoff':['validated_frozen_snapshot' if item else 'planner' for item in submissions]}


def start_generation_request(store,tool,value):
    from .generation_stage import validate_generation_request
    parameters=validate_generation_request(GenerationTools(store.root),tool,{k:v for k,v in value.items() if k!='request_key'})
    intent={'tool':tool,'parameters':parameters}
    rid=store.submit(value['request_key'],[intent],'generation')
    return {'run_id':rid,'task_id':rid+'.scene0','state':'accepted','tool':tool}


def start_capture_request(store,value):
    submission=read_program_submission(store.root,value['scene_program_path'])
    intent={'name':value.get('name',submission['program']['title']),'description':'Capture the supplied SceneProgram.',
            'split':'dev','capture_only':True,'scene_program_path':value['scene_program_path']}
    if 'layout' in value:intent['layout']=validate_layout(value['layout'])
    if 'capture_options' in value:
        capture_scope(submission['program'],value['capture_options'])
        intent['capture_options']=value['capture_options']
    rid=store.submit(value['request_key'],[intent],submitted_programs=[submission])
    return {'run_id':rid,'task_id':rid+'.scene0','state':'accepted','operation':'capture_only'}


def refine_scene_request(store,value):
    parent=value['parent_task_id'];snap=store.snapshot(parent.split('.')[0]);task=next(t for t in snap['tasks'] if t['id']==parent)
    if task['unit'].get('workflow','scene')!='scene':raise ValueError('refine requires a scene task')
    if snap['state'] not in {'SUCCEEDED','FAILED_FINAL','CANCELED'} or task['state'] not in {'SUCCEEDED','FAILED_FINAL','CANCELED'}:raise ValueError('source run is still active; wait for its terminal state before refining')
    source_revision=value.get('source_revision',task['unit']['revision'])
    if type(source_revision) is not int or not 0<=source_revision<=task['unit']['revision']:raise ValueError('source_revision must identify an existing revision')
    directory=store.root/parent/f'revision_{source_revision}'
    if not (directory/'capture'/'evidence.json').is_file():raise ValueError('refine requires captured scene evidence')
    parent_intent=task['unit']['intent']
    intent=scene_intent({'name':value['name'],'description':value['description'],'split':parent_intent['split'],'target_items':value.get('target_items',parent_intent.get('target_items',24))})
    # Refining a capture keeps its operation scope. An explicit data target opts
    # into the full pipeline; missing target_items must not silently request 24 QA.
    if parent_intent.get('capture_only') and 'target_items' not in value:
        intent.pop('target_items')
        intent['capture_only']=True
    if 'layout' in value:intent['layout']=validate_layout(value['layout'])
    submission=None
    if 'scene_program_path' in value:
        submission=read_program_submission(store.root,value['scene_program_path'])
        intent['scene_program_path']=value['scene_program_path']
    require_prior_reference(store,intent,directory)
    intent.update(refine_task_id=parent,refine_revision=source_revision,scene_family=task['unit']['intent'].get('scene_family',parent))
    rid=store.submit(value['request_key'],[intent],submitted_programs=[submission] if submission else None)
    return {'run_id':rid,'task_id':rid+'.scene0','state':'accepted','operation':'capture_only' if intent.get('capture_only') else 'scene_pipeline','inherited_split':intent['split'],'source_revision':intent['refine_revision'],'program_handoff':'validated_frozen_snapshot' if submission else 'planner_refinement'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    faulthandler.enable()
    if hasattr(signal,'SIGUSR1'):faulthandler.register(signal.SIGUSR1)
    from .runtime_config import load_service_config
    config=load_service_config(args.config);store=Store(config['artifacts'],config['harness'],config.get('database_url'))
    transfer=CaptureTransfer(store)
    stop=threading.Event()
    # Recover only FIT stages; desktop stages require the same worker to reconcile.
    for task in store.all_work():
        if task['state']=='RUNNING' and task['unit']['phase'] in {'plan','review','asset','dataset','layout','generation'}:store.update(task['id'],state='PENDING')
    thread=threading.Thread(target=coordinate,args=(store,stop),daemon=True);thread.start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
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
                    rid=path[len('/gallery/'):];snap=store.snapshot(rid)
                    sections=[]
                    for task in snap['tasks']:
                        folder=store.directory(task['id'],task['unit']['revision'])
                        pics=sorted(folder.glob('capture/view_*.png'))
                        images=''.join('<a href="/image/'+p.relative_to(Path(config['artifacts'])).as_posix()+'"><img src="/image/'+p.relative_to(Path(config['artifacts'])).as_posix()+'"></a>' for p in pics)
                        result=task.get('result') or task.get('failure') or {'phase':task['unit']['phase']}
                        sections.append('<section><h2>'+html.escape(task['unit']['intent'].get('name',task['id']))+'</h2><p>'+html.escape(task['state'])+' · revision '+str(task['unit']['revision'])+'</p><div class="views">'+images+'</div><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2))+'</pre></section>')
                    body='<html><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>SpatialForge</title><style>body{background:#111827;color:#e5e7eb;font:16px system-ui;margin:32px}h1{color:#67e8f9}.views{display:flex;gap:12px;flex-wrap:wrap}.views img{width:400px;border-radius:8px}section{padding:20px;background:#1f2937;margin:16px 0;border-radius:12px}pre{white-space:pre-wrap;font-size:13px}</style><h1>SpatialForge · 真实生产产物</h1><p>'+html.escape(rid)+' · '+snap['state']+'</p>'+''.join(sections)+'</html>'
                    data=body.encode();mime='text/html; charset=utf-8'
                else:self.reply({'name':'SpatialForge','message':'Use /gallery/<run_id>'});return
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except Exception as exc:self.reply({'error':str(exc)},404)
        def do_POST(self):
            role='worker' if self.path.startswith('/worker/') else 'operator'
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+config[role+'_token']):self.reply({'error':'unauthorized'},401);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                limit=CHUNK_BYTES if self.path=='/worker/upload-chunk' else 250*1024*1024 if self.path=='/worker/upload' else 2*1024*1024
                if length<0 or length>limit:raise ValueError('request size exceeds endpoint limit')
                raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('incomplete request body')
                if self.path=='/worker/upload-chunk':
                    job=json.loads(self.headers['X-SpatialForge-Job'])
                    chunk=decode_chunk(raw,self.headers.get('X-SpatialForge-Encoding','identity'))
                    self.reply(transfer.chunk(job,self.headers['X-SpatialForge-File'],int(self.headers['X-SpatialForge-Offset']),chunk));return
                if self.path=='/worker/upload':
                    job=json.loads(self.headers['X-SpatialForge-Job'])
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
                if self.path=='/catalog':
                    from .operator_catalog import catalog_response
                    self.reply(catalog_response(store,value))
                elif self.path=='/layout':
                    self.reply(start_design_request(store,value))
                elif self.path in {'/diffusion','/sam3','/sam3d','/depth','/mesh-import'}:
                    tool={'/mesh-import':'mesh_import','/depth':'depth_anything'}.get(self.path,self.path[1:])
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
                    if not isinstance(intent,dict) or not {'name','description'}<=set(intent) or set(intent)-{'name','description','label','source_image','source_mask','source_mesh','source_gaussian','asset_id','seed','source_up_axis','size_hint_m','subject_box','edit_reference','texture_baking'}:raise ValueError('invalid asset intent')
                    if not isinstance(intent['description'],str) or not 1<=len(intent['description'])<=12000:raise ValueError('invalid asset description')
                    self.reply({'run_id':store.submit(value['request_key'],[intent],'asset'),'state':'accepted'})
                elif self.path=='/extend':
                    parent=value['parent_task_id'];snap=store.snapshot(parent.split('.')[0]);task=next(t for t in snap['tasks'] if t['id']==parent)
                    if task['state']!='SUCCEEDED' or task['unit'].get('workflow','scene')!='scene':raise ValueError('extend an available captured scene task')
                    intent=scene_intent({'name':value['name'],'description':value['description'],'split':task['unit']['intent']['split'],'target_items':value.get('target_items',24)})
                    if 'layout' in value:intent['layout']=validate_layout(value['layout'])
                    intent.update(parent_task_id=parent,parent_revision=task['unit']['revision'],scene_family=task['unit']['intent'].get('scene_family',parent))
                    self.reply({'run_id':store.submit(value['request_key'],[intent]),'state':'accepted','inherited_split':intent['split']})
                elif self.path=='/refine':
                    self.reply(refine_scene_request(store,value))
                elif self.path=='/dataset':
                    intent=value['intent']
                    if not isinstance(intent,dict):raise ValueError('dataset intent must be an object')
                    from .integration import prepare_spec
                    prepare_spec(intent,store.harness)
                    self.reply({'run_id':store.submit(value['request_key'],[intent],'dataset'),'state':'accepted'})
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
                elif self.path=='/retry':self.reply(store.retry(value['task_id'],value.get('feedback')))
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
                    self.reply({'run_id':value['run_id'],'state':state['state'],'gallery_url':'http://127.0.0.1:3841/gallery/'+value['run_id'],'tasks':[{**{k:t.get(k) for k in ('id','state','unit','result','failure')},'downloads':[p.relative_to(store.directory(t['id'],t['unit']['revision'])).as_posix() for p in store.directory(t['id'],t['unit']['revision']).glob('release/*.zip')]} for t in state['tasks']]})
                elif self.path=='/cancel':store.cancel(value['run_id']);self.reply({'cancel_requested':True})
                elif self.path=='/worker/claim':self.reply(store.claim_desktop(value['worker_id']))
                elif self.path=='/worker/heartbeat':
                    # Older dispatchers omitted revision; preserve their cancellation check during rollout.
                    if 'revision' not in value:
                        snap=store.snapshot(value['task_id'].split('.')[0]);self.reply({'cancel':snap['state']=='CANCELED'})
                    else:self.reply(store.worker_update({**{k:value[k] for k in ('task_id','revision','token')},'transport_retry':value.get('transport_retry',0)},progress=value.get('progress')))
                elif self.path=='/worker/finish':self.reply(store.worker_update(value['job'],outcome=value['outcome'],processes_stopped=value.get('processes_stopped'),error=value.get('error')))
                elif self.path=='/worker/upload-begin':self.reply(transfer.begin(value['job'],value['files']))
                elif self.path=='/worker/upload-commit':self.reply(transfer.commit(value['job']))
                else:self.reply({'error':'unknown operation'},404)
            except Exception as exc:self.reply({'error':type(exc).__name__,'detail':str(exc)[:1000]},400)
    server=ThreadingHTTPServer(('127.0.0.1',config.get('port',3841)),Handler)
    try:server.serve_forever()
    finally:stop.set();server.server_close()


if __name__=='__main__':main()
