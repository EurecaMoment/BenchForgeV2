"""Operator CLI; reads the local service credential without displaying it."""
import argparse
import json
from pathlib import Path
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser(description='SpatialForge production client')
    p.add_argument('--config',default=str(Path(__file__).resolve().parents[2]/'service.local.json'))
    p.add_argument('operation',choices=['catalog','start','asset','extend','refine','dataset','inspect','retry','cancel','download','capture','status','evidence','preview','diffusion','sam3','sam3d','depth','mesh-import','call'])
    p.add_argument('value',nargs='?',help='SceneProgram path, run/task ID, or API route for call')
    p.add_argument('request_json',nargs='?',type=Path)
    p.add_argument('--revision',type=int);p.add_argument('--name');p.add_argument('--request-key');p.add_argument('--section')
    p.add_argument('--input',type=Path,help='UTF-8 JSON request file')
    p.add_argument('--run-id');p.add_argument('--task-id');p.add_argument('--file');p.add_argument('--output',type=Path)
    args=p.parse_args();cfg=json.loads(Path(args.config).read_text())
    source=args.input or args.request_json
    data=json.loads(source.read_text(encoding='utf-8-sig')) if source else {}
    data.update({k:v for k,v in {'run_id':args.run_id,'task_id':args.task_id,'file':args.file}.items() if v})
    data.update({k:v for k,v in {'revision':args.revision,'name':args.name,'request_key':args.request_key,'section':args.section}.items() if v is not None})
    route=args.operation
    if route=='call':route=args.value.strip('/')
    elif route=='capture':
        if args.value:data['scene_program_path']=str(Path(args.value).resolve())
        data.setdefault('request_key','cli-'+uuid.uuid4().hex)
    elif route=='status':
        route='observe'
        if args.value:data['run_id']=args.value
    elif route=='evidence' and args.value:data['task_id']=args.value
    request=urllib.request.Request('http://127.0.0.1:'+str(cfg.get('port',3841))+'/'+route,
        data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+cfg['operator_token']})
    with urllib.request.urlopen(request,timeout=90) as response:
        if route=='download':
            if not args.output:p.error('download requires --output')
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(response.read());print(str(args.output))
        else:print(json.dumps(json.load(response),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
