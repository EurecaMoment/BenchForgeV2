"""Operator CLI; reads the local service credential without displaying it."""
import argparse
import json
from pathlib import Path
import urllib.request
import uuid

from service_access.runtime_config import environment_value


def main():
    p=argparse.ArgumentParser(description='BenchForge production client')
    project = Path(environment_value('BENCHFORGE_ROOT', Path(__file__).resolve().parents[3]))
    p.add_argument('--config', type=Path, default=project/'config/generated/benchforge-server.local.json')
    p.add_argument('operation',choices=['catalog','start','asset','extend','refine','dataset','inspect','retry','cancel','download','capture','status','evidence','preview','diffusion','sam3','trellis','depth','mesh-import','call'])
    p.add_argument('value',nargs='?',help='SceneProgram path, run/task ID, or API route for call')
    p.add_argument('request_json',nargs='?',type=Path)
    p.add_argument('--revision',type=int);p.add_argument('--name');p.add_argument('--request-key');p.add_argument('--section')
    p.add_argument('--input',type=Path,help='UTF-8 JSON request file')
    p.add_argument('--run-id');p.add_argument('--task-id');p.add_argument('--file');p.add_argument('--output',type=Path)
    args=p.parse_args();cfg=json.loads(args.config.read_text(encoding='utf-8'))
    token_env = cfg.get('operator_token_env')
    token = environment_value(token_env) if token_env else cfg.get('operator_token')
    if not token:
        p.error(f'Set {token_env}' if token_env else 'Configure operator_token or operator_token_env')
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
    url = cfg.get('service_url') or 'http://127.0.0.1:' + str(cfg.get('port', 3841))
    request=urllib.request.Request(url.rstrip('/')+'/'+route,
        data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=90) as response:
        if route=='download':
            if not args.output:p.error('download requires --output')
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(response.read());print(str(args.output))
        else:print(json.dumps(json.load(response),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
