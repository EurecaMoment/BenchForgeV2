"""Explicitly start configured optional backends without a global service manager."""
import json
import urllib.request
from pathlib import Path
from .artifacts import write
from .processes import start_background


def backend(args,directory,config):
    name=args['name'];cfg=config.get('backends',{}).get(name)
    if not cfg:raise ValueError(f'Configure backends.{name}.command, cwd, env and health_url; see docs/BACKENDS.md')
    action=args.get('action','status')
    def health():
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(cfg['health_url'],timeout=5) as response:
                return {'reachable':response.status==200,'response':json.load(response)}
        except (OSError,ValueError) as exc:return {'reachable':False,'error':str(exc)}
    state=health()
    if action=='status':return {'backend':name,**state}
    if action!='start':raise ValueError('Supported actions: status, start. Process IDs are returned for explicit lifecycle management.')
    if state['reachable']:return {'backend':name,'reused':True,**state}
    command=cfg['command']
    if not isinstance(command,list) or not command:raise ValueError('Backend command must be an argv list')
    log=directory/'backend.log'
    process=start_background(command,cwd=cfg.get('cwd',str(directory)),log=log,env=cfg.get('env'))
    result={'backend':name,**process,'started':True,'ready':False,'log':str(log),
            'next':'Call backend status after startup. A started process is not inference acceptance.'}
    write(directory/'backend-process.json',result)
    return result
