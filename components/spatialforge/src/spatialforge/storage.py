"""One database authority: uses the existing Harness PostgreSQL and tables."""
import json
from pathlib import Path
import time
import uuid
from sqlalchemy import Table, Column, String, JSON, MetaData, select
from benchclaw.metadata import Repository, runs, tasks, events, artifacts
from benchclaw.store import write_json, safe_path
from .contracts import normalize_native_asset_references


def uid(prefix): return prefix+'_'+uuid.uuid4().hex[:16]


class Store:
    def __init__(self, root, harness, database_url=None):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.harness=Path(harness)
        self.repo=Repository(database_url or json.loads((Path(harness)/'deployment.local.json').read_text())['database_url'])
        meta=MetaData()
        self.keys=Table('spatialforge_request_keys',meta,Column('id',String,primary_key=True),Column('run_id',String))
        self.device=Table('spatialforge_devices',meta,Column('id',String,primary_key=True),Column('record',JSON))
        meta.create_all(self.repo.engine)

    def submit(self,key,intents,workflow='scene',submitted_programs=None):
        submitted_programs=submitted_programs or []
        if submitted_programs and (workflow!='scene' or len(submitted_programs)!=len(intents)):
            raise ValueError('SceneProgram snapshots must align with scene intents')
        with self.repo.transaction() as c:
            # PostgreSQL transaction advisory lock serializes request-key insertion and device claims.
            c.exec_driver_sql('SELECT pg_advisory_xact_lock(7420391)')
            old=c.execute(select(self.keys).where(self.keys.c.id==key)).mappings().first()
            if old:
                prior=c.execute(select(runs).where(runs.c.id==old['run_id'])).mappings().one()
                if prior['plan'].get('intents')!=intents or prior['plan'].get('workflow','scene')!=workflow or prior['plan'].get('submitted_programs',[])!=submitted_programs:
                    raise ValueError('request_key already belongs to a different request')
                return old['run_id']
            rid=uid('sf')
            plan={'schema':'spatialforge.pipeline/v1','intents':intents,'workflow':workflow,'created':time.time(),'code_version':'0.3.0'}
            if submitted_programs:plan['submitted_programs']=submitted_programs
            c.execute(runs.insert().values(id=rid,state='PENDING',plan=plan,created_at=str(time.time()),code_revision='spatialforge-0.2.0'))
            for i,intent in enumerate(intents):
                tid=f'{rid}.scene{i}'
                unit={'intent':intent,'index':i,'workflow':workflow,'phase':workflow if workflow in {'asset','dataset','layout','generation'} else 'plan','revision':0}
                if submitted_programs and submitted_programs[i] is not None:unit['submitted_program']=submitted_programs[i]
                c.execute(tasks.insert().values(id=tid,run_id=rid,task_id=f'scene{i}',unit=unit,state='PENDING',attempt=0,ready_at=0))
            c.execute(self.keys.insert().values(id=key,run_id=rid))
            self.repo.event(c,rid,None,'spatialforge.submitted',{'intents':intents})
            return rid

    def snapshot(self,rid):
        if isinstance(rid,str) and '.scene' in rid and rid.startswith('sf_'):
            raise ValueError(f'Expected run_id, received task_id {rid}; use run_id={rid.split(".")[0]} for status/wait/inspect/cancel, and the full task_id for evidence/retry')
        value=self.repo.status(rid)
        if value['plan'].get('schema')!='spatialforge.pipeline/v1': raise ValueError('not a SpatialForge run')
        return value

    def update(self,tid,**fields):
        with self.repo.transaction() as c:
            old=c.execute(select(tasks).where(tasks.c.id==tid).with_for_update()).mappings().one()
            run=c.execute(select(runs).where(runs.c.id==old['run_id'])).mappings().one()
            if run['state']=='CANCELED' and fields.get('state')!='CANCELED':return
            if 'unit' in fields:fields['unit']={**old['unit'],**fields['unit']}
            c.execute(tasks.update().where(tasks.c.id==tid).values(**fields))
            self.repo.event(c,old['run_id'],tid,'spatialforge.transition',{'state':fields.get('state',old['state']),'phase':fields.get('unit',old['unit']).get('phase')})

    def retry(self,tid,feedback=None):
        """Retain old attempts and retry the failed stage; never mutate successful products."""
        if feedback is not None and (not isinstance(feedback,str) or not 1<=len(feedback)<=12000):
            raise ValueError('retry feedback must be 1..12000 characters')
        with self.repo.transaction() as c:
            c.exec_driver_sql('SELECT pg_advisory_xact_lock(7420391)')
            task=c.execute(select(tasks).where(tasks.c.id==tid).with_for_update()).mappings().one()
            run=c.execute(select(runs).where(runs.c.id==task['run_id']).with_for_update()).mappings().one()
            if run['state'] in {'CANCELED','SUCCEEDED'}:raise ValueError('cannot retry a canceled or successful run')
            if task['state']!='FAILED_FINAL':raise ValueError('only failed tasks need retry')
            unit=dict(task['unit']);phase=unit['phase'];old=self.directory(tid,unit['revision'])
            if phase=='capture' and (task.get('failure') or {}).get('stage')=='capture_transport':
                # An explicit operator retry resumes the same native files and transfer offsets.
                ended=unit.pop('worker_end',{})
                if ended.get('token'):unit['resume_capture_token']=ended['token']
                unit['transport_retry']=unit.get('transport_retry',0)+1
            if feedback is not None:
                if phase!='plan':raise ValueError('retry feedback requires a failed planning stage; use refine for captured scenes')
                unit['operator_feedback']=feedback
            if phase=='plan':
                # Failed structural proposals and model traces remain immutable.
                # A repaired planner must not replay cached invalid responses.
                if unit.get('quality_repairs'):
                    unit.setdefault('quality_source_revision',unit['revision']-1)
                if (old/'repair_seed.json').exists():
                    import shutil
                    shutil.copy2(old/'repair_seed.json',self.directory(tid,unit['revision']+1)/'repair_seed.json')
                else:
                    seeds=sorted(old.glob('model_calls/scene_plan_*/validation_error.json'),key=lambda p:int(p.parent.name.rsplit('_',1)[-1]),reverse=True)
                    for seed_path in seeds:
                        seed=json.loads(seed_path.read_text())
                        if isinstance(seed.get('proposal'),dict):
                            write_json(self.directory(tid,unit['revision']+1)/'repair_seed.json',seed);break
                unit.update(revision=unit['revision']+1,engineering_retry=True)
            if phase=='review' and (old/'capture'/'report.json').exists():
                report=json.loads((old/'capture'/'report.json').read_text())
                if report['status']!='captured':
                    unit.update(revision=unit['revision']+1,phase='capture',engineering_retry=True)
                    import shutil
                    shutil.copy2(old/'program.json',self.directory(tid,unit['revision'])/'program.json')
                    unit.pop('capture_token',None)
            c.execute(runs.update().where(runs.c.id==run['id']).values(state='PENDING'))
            c.execute(tasks.update().where(tasks.c.id==tid).values(state='READY',unit=unit,failure=None,result=None,ready_at=0,lease_owner=None))
            self.repo.event(c,run['id'],tid,'spatialforge.retry',{'phase':unit['phase'],'revision':unit['revision'],'operator_feedback':feedback})
        return {'task_id':tid,'revision':unit['revision'],'phase':unit['phase']}

    def all_work(self):
        with self.repo.engine.connect() as c:
            return [dict(r) for r in c.execute(select(tasks).join(runs,tasks.c.run_id==runs.c.id).where(runs.c.code_revision=='spatialforge-0.2.0',runs.c.state.notin_(['CANCELED','SUCCEEDED','FAILED_FINAL']))).mappings()]

    def directory(self,tid,revision):
        directory=safe_path(self.root,f'{tid}/revision_{revision}')
        directory.mkdir(parents=True,exist_ok=True)
        return directory

    def claim_desktop(self,worker):
        with self.repo.transaction() as c:
            c.exec_driver_sql('SELECT pg_advisory_xact_lock(7420391)')
            device=c.execute(select(self.device).where(self.device.c.id=='desktop-isaac')).mappings().first()
            if device and device['record'].get('active'):
                record=device['record']
                if record['worker']!=worker: return {'waiting':'device_owned_by_other_worker'}
                task=c.execute(select(tasks).where(tasks.c.id==record['task_id'])).mappings().one()
                return self._job(task,record['token'])
            for task in self.all_work():
                if task['state']=='READY' and task['unit']['phase']=='capture':
                    unit=dict(task['unit']);token=unit.pop('resume_capture_token',None) or uid('attempt'); record={'active':True,'worker':worker,'task_id':task['id'],'token':token,'time':time.time()}
                    if device:c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record=record))
                    else:c.execute(self.device.insert().values(id='desktop-isaac',record=record))
                    c.execute(tasks.update().where(tasks.c.id==task['id']).values(state='RUNNING',unit=unit,lease_owner=token,lease_expires_at=time.time()+1800))
                    self.repo.event(c,task['run_id'],task['id'],'spatialforge.desktop_claim',{'token':token})
                    return self._job(task,token)
            return {'waiting':'no_jobs'}

    def _job(self,task,token):
        directory=self.directory(task['id'],task['unit']['revision'])
        program=normalize_native_asset_references(json.loads((directory/'program.json').read_text()))
        assets=sorted({o['asset_id'] for o in program['objects'] if o['kind']=='mesh'})
        return {'task_id':task['id'],'revision':task['unit']['revision'],'token':token,
                'program':program,'assets':assets,'transport_retry':task['unit'].get('transport_retry',0),
                'capture_options':task['unit']['intent'].get('capture_options',{}),
                'capture':{'width':960,'height':720,'steps':180,'dt':1/60}}

    def desktop_state(self):
        with self.repo.engine.connect() as c:
            row=c.execute(select(self.device).where(self.device.c.id=='desktop-isaac')).mappings().first()
            return row['record'] if row else {'active':False}

    def worker_update(self,job,progress=None,outcome=None,processes_stopped=False,error=None):
        """A terminal acknowledgement releases only the matching device lease."""
        from .progress import record_progress
        with self.repo.transaction() as c:
            c.exec_driver_sql('SELECT pg_advisory_xact_lock(7420391)')
            task=c.execute(select(tasks).where(tasks.c.id==job['task_id']).with_for_update()).mappings().one()
            run=c.execute(select(runs).where(runs.c.id==task['run_id'])).mappings().one()
            if job.get('transport_retry',0)!=task['unit'].get('transport_retry',0):raise ValueError('stale desktop retry generation')
            if task['unit'].get('capture_token')==job['token']:
                return {'committed':True,'duplicate':True}
            ended=task['unit'].get('worker_end') or {}
            if ended.get('token')==job['token']:
                return {'finished':True,'duplicate':True,'state':task['state']}
            row=c.execute(select(self.device).where(self.device.c.id=='desktop-isaac')).mappings().first()
            device=row['record'] if row else {}
            if task['lease_owner']!=job['token'] or task['unit']['revision']!=job['revision'] or not device.get('active') or device.get('task_id')!=job['task_id'] or device.get('token')!=job['token']:
                raise ValueError('stale desktop attempt; device ownership unchanged')
            canceled=run['state']=='CANCELED'
            if outcome is not None:
                if outcome not in {'canceled','failed'} or processes_stopped is not True:
                    raise ValueError('terminal acknowledgement requires stopped owned processes')
                if outcome=='canceled' and not canceled:raise ValueError('run has not requested cancellation')
                state='CANCELED' if canceled else 'FAILED_FINAL'
                end={'token':job['token'],'outcome':state,'time':time.time(),'local_capture_preserved':True}
                failure=None if canceled else {'stage':'capture_transport','error':str(error or 'desktop attempt failed')[:1000],'local_capture_preserved':True}
                c.execute(tasks.update().where(tasks.c.id==task['id']).values(state=state,lease_owner=None,lease_expires_at=None,unit={**task['unit'],'worker_end':end},failure=failure))
                c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record={'active':False,'last_end':end}))
                self.repo.event(c,task['run_id'],task['id'],'spatialforge.desktop_finished',{'end':end,'failure':failure})
                record_progress(self.directory(task['id'],job['revision']),'canceled' if canceled else 'failed',worker=end,error=failure)
                return {'finished':True,'state':state,'local_capture_preserved':True}
            if task['state']!='RUNNING':raise ValueError('desktop task is not running')
            if progress:
                if progress.get('stage') not in {'capture','upload','upload_retry','capture_transport_failed'}:raise ValueError('invalid desktop progress stage')
                record_progress(self.directory(task['id'],job['revision']),**progress)
            return {'cancel':canceled,'active':True}

    def commit_capture(self,job,upload):
        with self.repo.transaction() as c:
            c.exec_driver_sql('SELECT pg_advisory_xact_lock(7420391)')
            task=c.execute(select(tasks).where(tasks.c.id==job['task_id']).with_for_update()).mappings().one()
            run=c.execute(select(runs).where(runs.c.id==task['run_id'])).mappings().one()
            if job.get('transport_retry',0)!=task['unit'].get('transport_retry',0):raise ValueError('stale desktop retry generation')
            if task['unit'].get('capture_token')==job['token']: return {'committed':True,'duplicate':True}
            device=c.execute(select(self.device).where(self.device.c.id=='desktop-isaac')).mappings().one()['record']
            if not device.get('active') or device.get('token')!=job['token'] or device.get('task_id')!=job['task_id']:raise ValueError('stale desktop device')
            if run['state']=='CANCELED' and task['lease_owner']==job['token']:
                c.execute(tasks.update().where(tasks.c.id==task['id']).values(state='CANCELED',lease_owner=None))
                c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record={'active':False}))
                return {'committed':False,'canceled':True,'partial_capture_preserved':str(upload)}
            if task['lease_owner']!=job['token'] or task['unit']['revision']!=job['revision'] or task['state']!='RUNNING': raise ValueError('stale attempt')
            directory=self.directory(task['id'],job['revision']);report=json.loads((upload/'report.json').read_text())
            if report.get('token')!=job['token']: raise ValueError('foreign report')
            dest=directory/'capture'
            if dest.exists():
                # Recover a crash after filesystem commit but before the DB transaction.
                if json.loads((dest/'report.json').read_text()).get('token')!=job['token']:
                    raise ValueError('immutable capture already exists')
            else:upload.rename(dest)
            unit={**task['unit'],'phase':'review','capture_token':job['token']}
            c.execute(tasks.update().where(tasks.c.id==task['id']).values(state='READY',unit=unit,lease_owner=None))
            c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record={'active':False}))
            self.repo.event(c,task['run_id'],task['id'],'spatialforge.capture_committed',{'report':report})
            return {'committed':True}

    def settle_runs(self):
        with self.repo.transaction() as c:
            for r in c.execute(select(runs).where(runs.c.code_revision=='spatialforge-0.2.0')).mappings():
                if r['state'] in {'CANCELED','SUCCEEDED','FAILED_FINAL'}:continue
                work=list(c.execute(select(tasks).where(tasks.c.run_id==r['id'])).mappings())
                if all(w['state'] in {'SUCCEEDED','FAILED_FINAL','CANCELED'} for w in work):
                    state='SUCCEEDED' if all(w['state']=='SUCCEEDED' for w in work) else 'FAILED_FINAL'
                    c.execute(runs.update().where(runs.c.id==r['id']).values(state=state))
                elif any(w['state']=='RUNNING' for w in work) and r['state']!='RUNNING':
                    c.execute(runs.update().where(runs.c.id==r['id']).values(state='RUNNING'))

    def cancel(self,rid):
        self.snapshot(rid)
        with self.repo.transaction() as c:
            c.execute(runs.update().where(runs.c.id==rid).values(state='CANCELED'))
            self.repo.event(c,rid,None,'spatialforge.cancel_requested')
