"""Dispatch BenchForge capture attempts using the selected Isaac provider."""
import argparse
import ctypes
import io
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import zlib

import grpc

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from benchforge_backend.isaac.client import CaptureFailed, run_capture
from benchforge_backend.capture_recovery import local_capture_receipt,require_frozen_request
from benchforge_backend.provider_config import capture_timeout, isaac_endpoint
from benchforge_backend.runtime_config import load_worker_config
config={}
state_root=None
IS_WINDOWS=platform.system()=='Windows'
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0) if IS_WINDOWS else 0


def grpc_capture(job,directory,output):
    """Run one remote capture: upload assets, submit, poll with heartbeats, download artifacts."""
    grpc_settings = config['isaac_grpc']
    endpoint = isaac_endpoint(grpc_settings)
    rpc_timeout = grpc_settings.get('timeout_seconds', 60)
    receipt = directory / 'grpc_job.json'
    if receipt.is_file():
        existing = json.loads(receipt.read_text(encoding='utf8'))
        endpoint, started = existing['endpoint'], existing['started_at']
    else:
        started = time.time()
        write_json(receipt, {'job_id': job['token'], 'endpoint': endpoint, 'started_at': started})
    timeout=float(capture_timeout(config))
    stop={'reason':None}
    next_heartbeat=[0.]
    def on_status(status):
        now=time.time()
        if now-started>timeout:
            stop['reason']='timeout'
            return
        if now-next_heartbeat[0]>=8:
            next_heartbeat[0]=now
            try:
                canceled=api('/worker/heartbeat',{**job_identity(job),'progress':{'stage':'capture','started_at':started,'executor':'grpc','remote_job':status['state']}}).get('cancel')
            except (OSError,urllib.error.URLError):
                canceled=False
            if canceled:stop['reason']='canceled'
    job_id = job['token']
    with tempfile.TemporaryDirectory(prefix='isaac_grpc_') as temporary:
        assets={}
        for asset_id,path in (job.get('asset_paths') or {}).items():
            archive=Path(temporary)/f'{asset_id}.zip'
            base=Path(path).parent
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
                for item in sorted(base.rglob('*')):
                    if item.is_file():bundle.write(item,str(item.relative_to(base)))
            assets[f'{asset_id}.zip']=archive
        try:
            payload = {key: value for key, value in job.items() if key != 'asset_paths'}
            result=run_capture(endpoint,job_id,json.dumps(payload, ensure_ascii=False).encode('utf8'),output,
                                      assets=assets,timeout_seconds=timeout,rpc_timeout=rpc_timeout,
                                      on_status=on_status,should_stop=lambda:stop['reason'] is not None)
        except Exception:
            if stop['reason']:
                write_json(directory/'termination.json',{'reason':stop['reason'],'time':time.time(),'token':job['token']})
            raise
    write_json(directory/'grpc_capture.json',{'token':job['token'],'job_id':job_id,'endpoint':endpoint,
                                              'state':result['state'],'artifacts':result['artifacts']})


def api(path,value=None,data=None,headers=None):
    request=urllib.request.Request(config['url']+path,data=data if data is not None else json.dumps(value or {}).encode(),headers={'Authorization':'Bearer '+config['worker_token'],'Content-Type':'application/json',**(headers or {})})
    try:
        with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        detail=exc.read(2048).decode('utf8',errors='replace')
        if 400<=exc.code<500:raise ValueError(f'{path}: HTTP {exc.code}: {detail}') from exc
        raise OSError(f'{path}: HTTP {exc.code}: {detail}') from exc


def write_json(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(path)


def job_identity(job):
    return {**{key:job[key] for key in ('task_id','revision','token')},'transport_retry':job.get('transport_retry',0)}


def finish_job(job,directory,outcome,error=None):
    if config.get('isaac_mode') == 'local' or (directory / 'resident.json').is_file():
        # This small control message does not depend on any image or scene upload.
        remaining=owned_processes(directory/'request.json')
        if remaining:
            for process in remaining:process.close()
            raise RuntimeError('cannot release desktop while owned Isaac processes remain')
        resident=state_root/'resident' if state_root is not None else None
        if resident and (resident/'status.json').exists():
            status=json.loads((resident/'status.json').read_text(encoding='utf8'))
            if status.get('token')==job['token']:
                processes=resident_processes(resident)
                active=bool(processes)
                for process in processes:process.close()
                if active:raise RuntimeError('cannot release desktop during resident capture')
    try:receipt=local_capture_receipt(job,directory)
    except ValueError as exc:
        receipt=None
        error=(str(error)+'; ' if error else '')+str(exc)
    pending={'job':job_identity(job),'outcome':outcome,'processes_stopped':True,'error':error,
             'capture_complete':receipt is not None,'capture_receipt':receipt,'transport_retry':job.get('transport_retry',0)}
    write_json(directory/'finish_pending.json',pending)
    result=api('/worker/finish',pending)
    write_json(directory/'commit.json',result)
    return result


def upload_capture(job,directory,output):
    """Keep native files on disk; restart with server offsets after a broken connection."""
    if local_capture_receipt(job,directory) is None:
        raise ValueError('incomplete native capture requires executor recovery before upload')
    identity=job_identity(job);receipt=directory/'transport.json'
    state=json.loads(receipt.read_text(encoding='utf8')) if receipt.exists() else {}
    retry=job.get('transport_retry',0)
    if state.get('transport_retry',0)!=retry:state={}
    files=[{'name':p.name,'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in sorted(output.iterdir()) if p.is_file()]
    if state.get('files',files)!=files:raise ValueError('local capture changed during resumable upload')
    state={'started_at':time.time(),'errors':0,**state,'files':files,'transport_retry':retry}
    write_json(receipt,state)
    while state['errors']<5 and time.time()-state['started_at']<1800:
        try:
            response=api('/worker/upload-begin',{'job':identity,'files':files})
            if response.get('cancel'):return finish_job(job,directory,'canceled')
            if response.get('committed') or response.get('finished'):return response
            chunk_bytes=response['chunk_bytes']
            if type(chunk_bytes) is not int or not 1<=chunk_bytes<=4*1024*1024:raise ValueError('invalid server chunk size')
            for item in files:
                path=output/item['name'];offset=response['offsets'][item['name']]
                if type(offset) is not int or not 0<=offset<=item['size']:raise ValueError('invalid server offset')
                if path.stat().st_size!=item['size'] or path.stat().st_mtime_ns!=item['mtime_ns']:raise ValueError('capture file changed')
                with path.open('rb') as stream:
                    stream.seek(offset)
                    while offset<item['size']:
                        if time.time()-state['started_at']>=1800:raise TimeoutError('capture upload exceeded 30 minute budget')
                        raw=stream.read(min(chunk_bytes,item['size']-offset))
                        if not raw:raise ValueError('unexpected end of capture file')
                        compressed=zlib.compress(raw,1)
                        payload,encoding=(compressed,'deflate') if len(compressed)<len(raw) else (raw,'identity')
                        result=api('/worker/upload-chunk',data=payload,headers={'Content-Type':'application/octet-stream','X-BenchForge-Job':json.dumps(identity),'X-BenchForge-File':item['name'],'X-BenchForge-Offset':str(offset),'X-BenchForge-Encoding':encoding})
                        if result.get('cancel'):return finish_job(job,directory,'canceled')
                        if result.get('committed') or result.get('finished'):return result
                        if result['offset']!=offset+len(raw):raise ValueError('unexpected acknowledged offset')
                        offset=result['offset']
            result=api('/worker/upload-commit',{'job':identity})
            if result.get('cancel'):return finish_job(job,directory,'canceled')
            return result
        except (OSError,urllib.error.URLError) as exc:
            state['errors']+=1;state['last_error']=str(exc)[:1000]
            write_json(receipt,state)
            try:api('/worker/heartbeat',{**identity,'progress':{'stage':'upload_retry','errors':state['errors'],'max_errors':5,'error':state['last_error']}})
            except (OSError,ValueError):pass
            if state['errors']<5:time.sleep(min(5*state['errors'],20))
        except ValueError as exc:
            state['errors']=5;state['last_error']=str(exc)[:1000];write_json(receipt,state)
    return finish_job(job,directory,'failed',state.get('last_error','capture upload exceeded 30 minute budget'))


def extract_asset(archive,destination):
    """Extract only regular members underneath the dedicated cache directory."""
    destination=destination.resolve()
    members=archive.infolist()
    if len(members)>128 or sum(entry.file_size for entry in members)>2_000_000_000:
        raise ValueError('generated asset exceeds desktop transfer budget')
    for member in members:
        if '\\' in member.filename or ':' in member.filename:
            raise ValueError('invalid asset archive path')
        target=(destination/member.filename).resolve()
        if not target.is_relative_to(destination) or ((member.external_attr>>16)&0o170000)==0o120000:
            raise ValueError('asset archive escapes cache')
        if member.is_dir():target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(member) as source,target.open('wb') as stream:shutil.copyfileobj(source,stream)
    if not (destination/'mesh.json').is_file():raise ValueError('asset archive has no mesh.json')


def prepare_assets(job):
    cache=Path(config.get('asset_cache',state_root/'asset_cache')).resolve()
    cache.mkdir(parents=True,exist_ok=True)
    paths={}
    expected={obj['asset_id'] for obj in job['program']['objects'] if obj['kind']=='mesh'}
    if expected-set(job.get('assets',[])):raise ValueError('capture job omitted required asset IDs')
    for asset_id in sorted(expected):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',asset_id):raise ValueError('invalid asset ID')
        destination=cache/asset_id
        if not (destination/'mesh.json').is_file():
            request=urllib.request.Request(config['url']+'/worker/asset',data=json.dumps({'asset_id':asset_id}).encode(),headers={'Authorization':'Bearer '+config['worker_token'],'Content-Type':'application/json'})
            # A private sibling staging directory makes incomplete downloads invisible.
            with tempfile.TemporaryDirectory(prefix=asset_id+'_',dir=cache) as temporary:
                temporary=Path(temporary)
                archive_path=temporary/'download.zip'
                with urllib.request.urlopen(request,timeout=180) as response,archive_path.open('wb') as stream:
                    shutil.copyfileobj(response,stream)
                unpacked=temporary/'asset';unpacked.mkdir()
                with zipfile.ZipFile(archive_path) as archive:extract_asset(archive,unpacked)
                write_json(unpacked/'desktop_receipt.json',{'asset_id':asset_id,'downloaded_at':time.time(),'source':'BenchForge worker asset API'})
                unpacked.replace(destination)
        paths[asset_id]=str(destination/'mesh.json')
    return {**job,'asset_paths':paths}


def process_snapshot():
    # Read only candidate process metadata. No credentials or foreign command lines are logged.
    if IS_WINDOWS:
        script="""$ErrorActionPreference='Stop'
$rows=@(Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'cmd.exe' OR Name = 'kit.exe'\" | Select-Object ProcessId,ParentProcessId,CommandLine)
ConvertTo-Json -Compress -InputObject $rows
"""
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-Command',script],capture_output=True,text=True,timeout=25,creationflags=NO_WINDOW)
        if result.returncode:raise RuntimeError('cannot inspect owned Isaac processes; capture launch postponed')
        rows=json.loads(result.stdout or '[]')
        return rows if isinstance(rows,list) else [rows]
    else:
        # Linux: use ps to find python / kit processes. Match by pattern in /proc cmdline.
        out=subprocess.run(['ps','-eo','pid,ppid,args','--no-headers'],capture_output=True,text=True,timeout=15).stdout
        rows=[]
        for line in out.splitlines():
            line=line.strip()
            if not line:continue
            parts=line.split(None,2)
            if len(parts)<3:continue
            pid,ppid,cmdline=int(parts[0]),int(parts[1]),parts[2]
            lower=cmdline.lower()
            if any(key in lower for key in ('python','kit','isaac_capture','isaac_resident')):
                rows.append({'ProcessId':pid,'ParentProcessId':ppid,'CommandLine':cmdline})
        return rows


def capture_request(row):
    command=row.get('CommandLine') or ''
    script=str(root/'desktop/isaac_capture.py').replace('/','\\').casefold()
    if script not in command.replace('/','\\').casefold():return None
    argument=re.search(r'(?:^|\s)--request\s+(?:"([^"]+)"|(\S+))',command)
    return Path(argument.group(1) or argument.group(2)).resolve() if argument else None


def owns_command(row,request):
    # Resolve both sides: Windows command lines may use an 8.3 directory alias.
    return capture_request(row)==request.resolve()


def owns_resident(row,state):
    command=(row.get('CommandLine') or '').replace('/','\\')
    script=str(root/'desktop/isaac_resident.py').replace('/','\\')
    if script.casefold() not in command.casefold():return False
    argument=re.search(r'(?:^|\s)--state\s+(?:"([^"]+)"|(\S+))',command)
    return bool(argument) and Path(argument.group(1) or argument.group(2)).resolve()==state.resolve()


class OwnedProcess:
    """Keep a process handle, so monitoring follows the original process identity.

    Windows uses kernel32.WaitForSingleObject; Linux falls back to polling os.kill(pid,0).
    """
    def __init__(self,row):
        self.pid=int(row['ProcessId']);self.parent=int(row['ParentProcessId'])
        self.handle=None
        self.created=None
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            self.kernel.OpenProcess.restype=wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            self.kernel.WaitForSingleObject.restype=wintypes.DWORD
            self.kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
            self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            self.handle=self.kernel.OpenProcess(0x100000|0x1000,False,self.pid)
            if self.handle:
                creation,exit_time,kernel_time,user_time=(wintypes.FILETIME() for _ in range(4))
                if self.kernel.GetProcessTimes(self.handle,ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kernel_time),ctypes.byref(user_time)):
                    self.created=(creation.dwHighDateTime<<32)|creation.dwLowDateTime
        else:
            # Linux: pid-based liveness check; creation time from /proc
            try:
                with open(f'/proc/{self.pid}/stat') as f:
                    stat=f.read().split()
                    self.created=int(stat[21])  # starttime in clock ticks since boot
            except (FileNotFoundError,IndexError,PermissionError):
                self.created=None

    def active(self):
        if IS_WINDOWS:
            return bool(self.handle) and self.kernel.WaitForSingleObject(self.handle,0)==0x102
        else:
            import signal
            try:
                os.kill(self.pid,0)
                return True
            except (ProcessLookupError,PermissionError):
                return False

    def close(self):
        if IS_WINDOWS and self.handle:
            self.kernel.CloseHandle(self.handle);self.handle=None
        # Linux: no handle to close

    def terminate_tree(self):
        if self.active():
            if IS_WINDOWS:
                subprocess.run(['taskkill','/PID',str(self.pid),'/T','/F'],capture_output=True,timeout=25,creationflags=NO_WINDOW)
            else:
                try:
                    subprocess.run(['pkill','-TERM','-P',str(self.pid)],capture_output=True,timeout=15)
                except FileNotFoundError:pass
                try:
                    os.kill(self.pid,15)  # SIGTERM
                except (ProcessLookupError,PermissionError):pass
                time.sleep(2)
                if self.active():
                    try:
                        subprocess.run(['pkill','-KILL','-P',str(self.pid)],capture_output=True,timeout=15)
                    except FileNotFoundError:pass
                    try:
                        os.kill(self.pid,9)  # SIGKILL
                    except (ProcessLookupError,PermissionError):pass


def owned_processes(request,rows=None):
    handles=[OwnedProcess(row) for row in (process_snapshot() if rows is None else rows) if owns_command(row,request)]
    active=[]
    for process in handles:
        if process.active():active.append(process)
        else:process.close()
    return active


def resident_processes(state,rows=None):
    handles=[OwnedProcess(row) for row in (process_snapshot() if rows is None else rows) if owns_resident(row,state)]
    active=[]
    for process in handles:
        if process.active():active.append(process)
        else:process.close()
    return active


def stop_resident(state,processes):
    known={p.pid for p in processes}
    for process in resident_processes(state):
        if process.pid not in known:processes.append(process)
        else:process.close()
    for process in processes:process.terminate_tree()
    deadline=time.monotonic()+25
    while any(p.active() for p in processes) and time.monotonic()<deadline:time.sleep(.2)
    if any(p.active() for p in processes):raise RuntimeError('resident Isaac is still terminating')


def wait_owned(job,directory,processes,launched=None):
    record=directory/'process.json'
    previous=json.loads(record.read_text(encoding='utf8')) if record.is_file() else {}
    started=previous.get('started_at')
    if not started:
        times=[p.created/10_000_000-11644473600 for p in processes if IS_WINDOWS and p.created]
        started=min(times,default=time.time())
    write_json(record,{'token':job['token'],'started_at':started,'adopted':launched is None,
                       'processes':[{'pid':p.pid,'parent_pid':p.parent,'created_filetime':p.created} for p in processes]})
    try:
        while any(p.active() for p in processes) or (launched is not None and launched.poll() is None):
            time.sleep(8)
            try:canceled=api('/worker/heartbeat',{**job_identity(job),'progress':{'stage':'capture','started_at':started}}).get('cancel')
            except (OSError,urllib.error.URLError):canceled=False
            if canceled or time.time()-started>config.get('capture_timeout_seconds',1800):
                # Discover descendants again before termination, including a child whose shell exited.
                extra=owned_processes(directory/'request.json')
                known={p.pid for p in processes}
                for process in extra:
                    if process.pid not in known:processes.append(process);known.add(process.pid)
                    else:process.close()
                for process in processes:process.terminate_tree()
                if launched is not None:
                    try:launched.wait(timeout=25)
                    except subprocess.TimeoutExpired:raise RuntimeError('owned Isaac process did not terminate')
                if any(p.active() for p in processes):raise RuntimeError('owned Isaac child is still terminating; retrying ownership recovery')
                write_json(directory/'termination.json',{'reason':'canceled' if canceled else 'timeout','time':time.time(),'token':job['token']})
                break
    finally:
        for process in processes:process.close()


def recover_other_attempts(job,rows):
    """Finish waiting on a previous owned attempt before allowing another Kit."""
    requests=[capture_request(row) for row in rows]
    if not any(request and request.is_relative_to(state_root.resolve()) for request in requests):return
    # Only inspect request receipts if an actual BenchForge capture process exists.
    for request in state_root.glob('attempt_*/request.json'):
        if request.parent.name==job['token']:continue
        processes=owned_processes(request,rows)
        if processes:
            previous=json.loads(request.read_text(encoding='utf8'))
            if previous.get('token')!=request.parent.name:
                for process in processes:process.close()
                raise RuntimeError('owned Isaac request does not match its attempt directory')
            wait_owned(previous,request.parent,processes)


def run_resident(job, directory, rows):
    """Submit a mailbox request or take ownership of that request after a worker restart."""
    state = state_root / 'resident'
    state.mkdir(exist_ok=True)
    request, output = directory / 'request.json', directory / 'capture'
    receipt = directory / 'resident.json'
    result_path = directory / 'resident_result.json'
    started = json.loads(receipt.read_text(encoding='utf8'))['started_at'] if receipt.is_file() else time.time()
    if not receipt.is_file():
        write_json(receipt, {'token': job['token'], 'started_at': started})
    command = {'action': 'capture', 'request': str(request), 'output': str(output)}
    local = config.get('isaac_local', {})
    processes = resident_processes(state, rows)
    child = None
    try:
        status = api('/worker/heartbeat', {**job_identity(job), 'progress': {
            'stage': 'capture', 'started_at': started, 'executor': 'local'}})
        next_heartbeat = time.monotonic() + 8
        while True:
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding='utf8'))
                if result['state'] != 'restart_required':
                    return result
                # The resident has an incompatible boot profile. Let it exit before relaunching.
                deadline = time.monotonic() + 25
                while (any(process.active() for process in processes) or
                       (child is not None and child.poll() is None)):
                    if time.monotonic() >= deadline:
                        stop_resident(state, processes)
                        break
                    time.sleep(.2)
                result_path.unlink()
                (state / 'active.json').unlink(missing_ok=True)
                child = None

            reason = 'canceled' if status.get('cancel') else 'timeout' if time.time() - started > capture_timeout(config) else None
            if reason:
                stop_resident(state, processes)
                if child is not None:
                    child.wait(timeout=25)
                write_json(directory / 'termination.json', {'reason': reason, 'token': job['token'], 'time': time.time()})
                return {'state': 'failed', 'error': reason}

            queued = next((state / name for name in ('command.json', 'active.json')
                           if (state / name).is_file()), None)
            active = any(process.active() for process in processes) or (child is not None and child.poll() is None)
            if active and queued and queued.exists():
                try:
                    pending = json.loads(queued.read_text(encoding='utf8'))
                except FileNotFoundError:
                    # The resident moves its mailbox file as it accepts the command.
                    continue
                if pending.get('request') != command['request']:
                    previous = pending.get('request')
                    if previous and Path(previous).with_name('resident_result.json').is_file():
                        time.sleep(.2)
                        continue
                    stop_resident(state, processes)
                    if child is not None:
                        child.wait(timeout=25)
                    active, child = False, None

            if not active and child is None:
                for name in ('active.json', 'command.json', 'status.json'):
                    (state / name).unlink(missing_ok=True)
                write_json(state / 'command.json', command)
                env = {**os.environ, 'BENCHFORGE_ISAAC_ASSET_ROOT': local['asset_root']}
                with (directory / 'isaac.log').open('a', encoding='utf8') as log:
                    child = subprocess.Popen(
                        [local['python'], str(root / 'desktop/isaac_resident.py'),
                         '--state', str(state), '--idle-seconds', str(local.get('idle_seconds', 300))],
                        env=env, stdout=log, stderr=subprocess.STDOUT, cwd=root,
                        creationflags=NO_WINDOW,
                    )
            elif active and queued is None and not result_path.is_file():
                write_json(state / 'command.json', command)

            if child is not None and child.poll() is not None and not result_path.is_file():
                return {'state': 'failed', 'error': 'Isaac resident exited without a capture receipt'}
            time.sleep(2)
            if time.monotonic() >= next_heartbeat:
                status = api('/worker/heartbeat', {**job_identity(job), 'progress': {
                    'stage': 'capture', 'started_at': started, 'executor': 'local'}})
                next_heartbeat = time.monotonic() + 8
    finally:
        for process in processes:
            process.close()


def run_job(job):
    if not re.fullmatch(r'attempt_[a-f0-9]{16}',job['token']):raise ValueError('invalid capture attempt token')
    directory=state_root/job['token'];directory.mkdir(exist_ok=True)
    request=directory/'request.json';output=directory/'capture';report=output/'report.json'
    if request.is_file():require_frozen_request(job,json.loads(request.read_text(encoding='utf8')))
    local = (directory / 'resident.json').is_file() or (
        not (directory / 'grpc_job.json').is_file() and config.get('isaac_mode') == 'local')
    rows = process_snapshot() if local else []
    if local:
        recover_other_attempts(job, rows)
        processes = owned_processes(request, rows)
        if processes:
            wait_owned(job, directory, processes)
    pending=directory/'finish_pending.json'
    if pending.exists():
        value=json.loads(pending.read_text(encoding='utf8'))
        if value.get('transport_retry',0)==job.get('transport_retry',0):
            finish_job(job,directory,value['outcome'],value.get('error'));return
    resident_started = local and (directory / 'resident.json').is_file()
    resident_receipt = directory / 'resident_result.json'
    resuming_upload = job.get('capture_recovery_mode') == 'resume_upload'
    local_pending = resident_started and not resuming_upload and (not resident_receipt.exists() or
        json.loads(resident_receipt.read_text(encoding='utf8'))['state'] != 'complete')
    if not report.exists() or local_pending:
        status=api('/worker/heartbeat',job_identity(job))
        if status.get('cancel') and not local_pending and not (directory / 'grpc_job.json').is_file():
            finish_job(job,directory,'canceled');return
        if status.get('committed') or status.get('finished'):write_json(directory/'commit.json',status);return
        if resident_started and request.is_file():
            job = {**job, 'asset_paths': json.loads(request.read_text(encoding='utf8')).get('asset_paths', {})}
        else:
            job = prepare_assets(job)
            write_json(request, job)
        try:
            if local:
                result = run_resident(job, directory, rows)
                if result['state'] != 'complete' or not report.is_file():
                    outcome = 'canceled' if result.get('error') == 'canceled' else 'failed'
                    return finish_job(job, directory, outcome, result.get('error') or 'Isaac did not publish a report')
            else:
                grpc_capture(job, directory, output)
        except CaptureFailed as exc:
            termination = directory / 'termination.json'
            reason = json.loads(termination.read_text(encoding='utf8'))['reason'] if termination.is_file() else None
            return finish_job(job, directory, 'canceled' if reason == 'canceled' else 'failed', str(exc))
    value=json.loads(report.read_text(encoding='utf8'))
    if value.get('status')!='captured':
        return finish_job(job,directory,'failed','; '.join(value.get('errors',[])) or 'Isaac capture did not complete')
    result=upload_capture(job,directory,output)
    write_json(directory/'commit.json',result)


def main():
    global config,state_root
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=root.parents[1]/'config/generated/worker.local.json')
    parser.add_argument('--once',action='store_true',help='Exit after one claimed capture')
    args=parser.parse_args()
    config=load_worker_config(args.config)
    if config.get('isaac_mode', 'grpc') == 'grpc':
        isaac_endpoint(config.get('isaac_grpc') or {})
    state_root=Path(config.get('runs') or root.parents[1]/'.benchforge/worker/runs')
    state_root.mkdir(parents=True,exist_ok=True)
    # 跨平台 supervisor mutex：Windows 用命名内核互斥量，Linux 用 pidfile。
    pidfile=state_root/'worker.pid'
    if IS_WINDOWS:
        kernel=ctypes.windll.kernel32
        kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,'Local\\BenchForgeDesktopWorker')
        if kernel.GetLastError()==183:raise SystemExit('BenchForge worker already active')
    else:
        # Linux pidfile：若存在则检查 pid 是否还活着。
        if pidfile.exists():
            try:
                old_pid=int(pidfile.read_text().strip())
                os.kill(old_pid,0)
                raise SystemExit(f'BenchForge worker already active (pid {old_pid})')
            except (ValueError,ProcessLookupError,PermissionError):
                pidfile.unlink(missing_ok=True)
        pidfile.write_text(str(os.getpid()))
    tunnel=None
    try:
        while True:
            job=None
            try:
                if config.get('ssh_host') and (tunnel is None or tunnel.poll() is not None):
                    tunnel=subprocess.Popen([config.get('ssh','ssh'),'-n','-N',*(['-F',config['ssh_config']] if config.get('ssh_config') else []),'-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=20','-o','ServerAliveCountMax=3','-L',config['ssh_forward'],config['ssh_host']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW)
                    time.sleep(2)
                job=api('/worker/claim',{'worker_id':config.get('worker_id','desktop-isaac-main')})
                if 'task_id' in job:
                    run_job(job)
                    if args.once:break
                else:time.sleep(5)
            except Exception as exc:
                with (state_root/'worker.log').open('a',encoding='utf8') as log:log.write(time.strftime('%FT%T')+' '+str(exc)+'\n')
                if job and 'token' in job:
                    directory=state_root/job['token'];directory.mkdir(exist_ok=True)
                    path=directory/'worker_errors.json'
                    record=json.loads(path.read_text(encoding='utf8')) if path.exists() else {'count':0}
                    if record.get('transport_retry',0)!=job.get('transport_retry',0):record={'count':0}
                    record.update(count=record['count']+1,error=str(exc)[:1000],transport_retry=job.get('transport_retry',0))
                    write_json(path,record)
                    if record['count']>=3 and not isinstance(exc, (grpc.RpcError, TimeoutError)):
                        try:finish_job(job,directory,'failed',record['error'])
                        except Exception as finish_error:
                            with (state_root/'worker.log').open('a',encoding='utf8') as log:log.write(time.strftime('%FT%T')+' finish pending: '+str(finish_error)+'\n')
                time.sleep(8)
    finally:
        if tunnel and tunnel.poll() is None:tunnel.terminate()
        if IS_WINDOWS:
            kernel.CloseHandle(ctypes.c_void_p(mutex))
        else:
            pidfile.unlink(missing_ok=True)


if __name__=='__main__':main()
