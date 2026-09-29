"""Run task-authored Python with writable task files and read-only Harness code."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


def run_task_code(artifact_root,workspace_id,code,timeout_seconds=60):
    if not isinstance(workspace_id,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',workspace_id):raise ValueError('invalid workspace_id')
    if not isinstance(code,str) or not 1<=len(code)<=1024*1024:raise ValueError('code must be 1..1048576 characters')
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=300:raise ValueError('timeout_seconds must be 1..300')
    root=Path(artifact_root).resolve();base=root/'operator_workspaces';base.mkdir(exist_ok=True)
    (root/'generated_assets').mkdir(exist_ok=True)
    workspace=base/workspace_id;workspace.mkdir(exist_ok=True)
    if workspace.resolve().parent!=base.resolve() or workspace.is_symlink():raise ValueError('workspace must remain inside operator_workspaces')
    call_id='code_'+uuid.uuid4().hex[:12]
    script=workspace/(call_id+'.py');script.write_text(code,encoding='utf8')
    stdout=workspace/(call_id+'.stdout');stderr=workspace/(call_id+'.stderr')
    cmd=['bwrap','--die-with-parent','--unshare-all','--new-session',
         '--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
         '--symlink','usr/bin','/bin','--tmpfs','/tmp','--proc','/proc','--dev','/dev',
         '--ro-bind',sys.prefix,sys.prefix]
    if sys.base_prefix!=sys.prefix:cmd+=['--ro-bind',sys.base_prefix,sys.base_prefix]
    cmd+=['--ro-bind',str(Path(__file__).resolve().parents[1]),'/harness',
          '--ro-bind',str(root/'generated_assets'),'/assets',
          '--bind',str(workspace),'/workspace','--chdir','/workspace',
          '--setenv','HOME','/workspace','--setenv','PYTHONPATH','/harness',
          '--setenv','PYTHONIOENCODING','utf8',sys.executable,'/workspace/'+script.name]
    started=time.time();timed_out=False
    with stdout.open('wb') as out,stderr.open('wb') as err:
        process=subprocess.Popen(cmd,stdout=out,stderr=err,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},start_new_session=True)
        try:process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out=True;os.killpg(process.pid,signal.SIGKILL);process.wait()
    artifacts=[]
    for path in workspace.rglob('*'):
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(workspace.resolve()):
            if path.stat().st_mtime>=started and not path.name.startswith(call_id):
                artifacts.append({'file':path.relative_to(workspace).as_posix(),'source_path':str(path),'bytes':path.stat().st_size})
                if len(artifacts)>=50:break
    result={'workspace_id':workspace_id,'call_id':call_id,'returncode':process.returncode,'timed_out':timed_out,
            'stdout':stdout.read_bytes()[:12000].decode('utf8',errors='replace'),
            'stderr':stderr.read_bytes()[:6000].decode('utf8',errors='replace'),'artifacts':artifacts,
            'permissions':{'task_workspace':'read_write','harness_source':'read_only','generated_assets':'read_only',
                           'authority_gt':'not_mounted','host_network':'unavailable; use production tools','gpu':'use production tools'},
            'artifact_scope':'task-authored intermediate data; never simulator or official GT'}
    (workspace/(call_id+'.receipt.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result
