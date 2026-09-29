from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

from .compiler import compile_spec
from .domain import ArtifactRef, DatasetSpec, Failure, HarnessError, State, WorkResult
from .metadata import Repository
from .plugins import Registry
from .store import ArtifactStore, safe_path, write_json


class WorkflowBackend(Protocol):
    def submit(self,spec:DatasetSpec)->str: ...
    def resume(self,run_id:str)->dict: ...
    def cancel(self,run_id:str)->None: ...
    def retry(self,run_id:str,task_id:str|None=None)->None: ...
    def status(self,run_id:str)->dict: ...


class LocalWorkflowBackend:
    def __init__(self,repo:Repository,store:ArtifactStore,registry:Registry|None=None):
        self.repo,self.store,self.registry=repo,store,registry or Registry()

    def submit(self,spec):
        return self.repo.submit(compile_spec(spec,self.registry))

    def cancel(self,run_id):
        return self.repo.cancel(run_id)

    def retry(self,run_id,task_id=None):
        return self.repo.retry(run_id,task_id)

    def status(self,run_id):
        return self.repo.status(run_id)

    def recover_expired(self,run_id):
        for row in self.repo.status(run_id)['tasks']:
            if row['state']!=State.RUNNING or row['lease_expires_at']>time.time():
                continue
            token=row['lease_owner']
            try:
                recovered=self.store.recover(run_id,row['task_id'],token)
                if recovered:
                    ref,payload=recovered
                    result=WorkResult.model_validate(payload)
                    if result.status!='succeeded':
                        raise HarnessError('INVALID_RECEIPT','Only complete results can recover')
                    self.repo.finish(row['id'],token,State.SUCCEEDED,result.model_dump(mode='json'),ref.model_dump(mode='json'),allow_expired=True)
                else:
                    self.repo.finish(row['id'],token,State.FAILED_RETRYABLE,
                                     failure=Failure(code='WORKER_LOST',message='Lease expired without committed output',retryable=True).model_dump(),allow_expired=True)
            except HarnessError as exc:
                if exc.failure.code=='LEASE_LOST':
                    continue
                self.repo.finish(row['id'],token,State.FAILED_FINAL,failure=exc.failure.model_dump(),allow_expired=True)

    def execute(self,row):
        run=self.repo.status(row['run_id'])
        token=row['lease_owner']
        unit=row['unit']
        plugin=self.registry.get(unit['plugin_id'])
        try:
            health=plugin.healthcheck(unit['parameters'])
            if not health.ready:
                self.repo.finish(row['id'],token,State.BLOCKED_DEPENDENCY,
                                 failure=Failure(code=health.code,message=health.message,component=unit['plugin_id']).model_dump())
                return
            output=self.store.allocate(row['run_id'],row['task_id'],token)
            inputs={}
            for parent in run['tasks']:
                if parent['task_id'] in unit['depends_on']:
                    ref=ArtifactRef.model_validate(parent['artifact'])
                    directory=self.store.verify(ref)
                    inputs[parent['task_id']]={'bundle':parent['result']['bundle'],'directory':str(directory)}
            request_path=output/'request.json'
            result_path=output/'result.json'
            write_json(request_path,{'spec':run['plan']['spec'],'unit':unit,'output_dir':str(output),
                                     'inputs':inputs,'result_path':str(result_path)})
            env={k:v for k,v in os.environ.items() if k not in {'BENCHCLAW_DATABASE_URL','DATABASE_URL'}}
            # No shell interpretation or inherited stdin; each attempt has a separate process group.
            with (output/'worker.log').open('wb') as log:
                process=subprocess.Popen([sys.executable,'-m','benchclaw.worker',str(request_path)],
                                         cwd=output,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                         start_new_session=os.name=='posix')
                deadline=time.monotonic()+unit['retry']['timeout_seconds']
                try:
                    while process.poll() is None:
                        if time.monotonic()>deadline:
                            raise HarnessError('TASK_TIMEOUT',unit['task_id'],True)
                        current=next(t for t in self.repo.status(row['run_id'])['tasks'] if t['id']==row['id'])
                        if current['state']!=State.RUNNING or current['lease_owner']!=token:
                            raise HarnessError('LEASE_LOST',row['id'])
                        time.sleep(1)
                except BaseException:
                    if process.poll() is None:
                        if os.name=='posix':
                            os.killpg(process.pid,signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait()
                    raise
            if not result_path.is_file():
                raise HarnessError('PLUGIN_NO_RESULT',f'Worker exited {process.returncode} without a result',process.returncode<0)
            result=WorkResult.model_validate(json.loads(result_path.read_text()))
            if result.status=='succeeded' and process.returncode!=0:
                raise HarnessError('EXIT_RESULT_CONFLICT','Nonzero exit cannot report success')
            state={'succeeded':State.SUCCEEDED,'failed_retryable':State.FAILED_RETRYABLE,
                   'failed_final':State.FAILED_FINAL,'quarantined':State.QUARANTINED}[result.status]
            ref=None
            if state==State.SUCCEEDED:
                # Operational envelopes/logs are not dataset artifacts and may be empty.
                request_path.unlink()
                if (output/'worker.log').stat().st_size==0:
                    (output/'worker.log').unlink()
                ref=self.store.commit(row['run_id'],row['task_id'],token,result.model_dump(mode='json'))
            self.repo.finish(row['id'],token,state,result.model_dump(mode='json'),ref.model_dump(mode='json') if ref else None,
                             result.failure.model_dump() if result.failure else None)
        except HarnessError as exc:
            if exc.failure.code!='LEASE_LOST':
                try:
                    self.repo.finish(row['id'],token,State.FAILED_RETRYABLE if exc.failure.retryable else State.FAILED_FINAL,
                                     failure=exc.failure.model_dump(),allow_expired=exc.failure.code=='TASK_TIMEOUT')
                except HarnessError as inner:
                    if inner.failure.code!='LEASE_LOST':
                        raise
        except Exception as exc:
            self.repo.finish(row['id'],token,State.FAILED_FINAL,
                             failure=Failure(code='HARNESS_EXECUTION_ERROR',message=f'{type(exc).__name__}: {exc}').model_dump())

    def resume(self,run_id):
        self.recover_expired(run_id)
        while True:
            row=self.repo.claim(run_id)
            if row:
                self.execute(row)
                continue
            state=self.repo.refresh(run_id)
            snapshot=self.repo.status(run_id)
            retry=[r for r in snapshot['tasks'] if r['state']==State.FAILED_RETRYABLE]
            if retry and state not in {'CANCELED','FAILED_FINAL','BLOCKED_DEPENDENCY'}:
                delay=min(r['ready_at'] for r in retry)-time.time()
                time.sleep(max(.1,min(1,delay)))
                continue
            # Other coordinators or orphaned workers may hold a still-valid lease.
            # Return honest RUNNING; a later resume performs expiry recovery.
            return snapshot
