"""Persist scene production and capture state in the BenchForge database."""
import json
from pathlib import Path
import time
import uuid
from sqlalchemy import Table, Column, String, JSON, MetaData, inspect, select, update as sql_update
from .metadata import Repository, runs, tasks
from .files import write_json, safe_path
from .contracts import normalize_native_asset_references
from .program_submission import submission_identity
from .run_context import RunContext
from .runtime_config import resolve_database_url
from .scene_design import canonical_schema


def uid(prefix): return prefix+'_'+uuid.uuid4().hex[:16]


class Store:
    def __init__(self, root, harness=None, database_url=None):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.repo=Repository(resolve_database_url(harness,database_url))
        meta=MetaData()
        self.keys=Table('benchforge_request_keys',meta,Column('id',String,primary_key=True),Column('run_id',String))
        self.device=Table('benchforge_devices',meta,Column('id',String,primary_key=True),Column('record',JSON))
        with self.repo.transaction() as conn:
            self.repo.lock_queue(conn)
            tables = set(inspect(conn).get_table_names())
            for legacy, current in (
                ('spatialforge_request_keys', self.keys.name),
                ('spatialforge_devices', self.device.name),
            ):
                if legacy not in tables:
                    continue
                if current not in tables:
                    conn.exec_driver_sql(f'ALTER TABLE {legacy} RENAME TO {current}')
                elif conn.exec_driver_sql(f'SELECT 1 FROM {legacy} LIMIT 1').first():
                    raise ValueError(f'{legacy} still contains deployment state alongside {current}; reconcile the tables before starting BenchForge')
            meta.create_all(conn)

    def submit(self,key,intents,workflow='scene',submitted_programs=None,context=None):
        if workflow == 'dataset':
            raise ValueError('Legacy dataset jobs are retired. Use data.capability or submit a scene with target_items.')
        from .scene_acceptance import policy_for, check_references, admit_program
        external_context = RunContext.from_request(context)
        if external_context is None:
            external_context = RunContext()
        parent_runs = {
            str(intent.get(key)).split('.')[0]
            for intent in intents
            for key in ('parent_task_id', 'refine_task_id', 'extend_task_id')
            if intent.get(key)
        }
        if len(parent_runs) > 1:
            raise ValueError('one run cannot have multiple parent runs')
        inferred_parent = next(iter(parent_runs), None)
        if inferred_parent and external_context.parent_run_id not in (None, inferred_parent):
            raise ValueError('context.parent_run_id must match the scene lineage')
        if inferred_parent and not external_context.parent_run_id:
            external_context = RunContext(
                workspace_id=external_context.workspace_id,
                session_id=external_context.session_id,
                parent_run_id=inferred_parent,
            )
        scene_modes = [intent.get('execution_mode') for intent in intents] if workflow == 'scene' else []
        policies = {
            mode: policy_for(self.root, mode)
            for mode in set(scene_modes)
        }
        policy = next((value for value in policies.values() if value), {})
        if policy:
            check_references(intents,policy)
            requires_scene_programs = workflow == 'scene' and any(
                mode in (None, 'production') for mode in scene_modes
            )
            if requires_scene_programs:
                if not submitted_programs or len(submitted_programs)!=len(intents) or any(not row for row in submitted_programs):
                    raise ValueError('Realistic production requires complete SceneProgram snapshots; no planner fallback')
                for intent,submission in zip(intents,submitted_programs):
                    mode = intent.get('execution_mode')
                    admission=admit_program(self.root,submission['program'],allow_generated=True,execution_mode=mode)
                    lineage_task_id=intent.get('refine_task_id') or intent.get('extend_task_id')
                    if lineage_task_id:
                        from .scene_design import require_prior_brief
                        require_prior_brief(admission.get('scene_brief') or {},
                            self.root/lineage_task_id/('revision_'+str(intent.get('refine_revision',intent.get('extend_revision')))))
        submitted_programs=submitted_programs or []
        if submitted_programs and (workflow!='scene' or len(submitted_programs)!=len(intents)):
            raise ValueError('SceneProgram snapshots must align with scene intents')
        with self.repo.transaction() as c:
            self.repo.lock_queue(c)
            old=c.execute(select(self.keys).where(self.keys.c.id==key)).mappings().first()
            if old:
                prior=c.execute(select(runs).where(runs.c.id==old['run_id'])).mappings().one()
                prior_context = prior['plan'].get('context') or {}
                context_matches = all(
                    prior_context.get(field) == getattr(external_context, field)
                    for field in ('workspace_id', 'session_id', 'parent_run_id')
                )
                previous_submissions = list(map(submission_identity, prior['plan'].get('submitted_programs', [])))
                if (prior['plan'].get('intents')!=intents or prior['plan'].get('workflow','scene')!=workflow
                        or previous_submissions != list(map(submission_identity, submitted_programs)) or not context_matches):
                    raise ValueError('request_key already belongs to a different request')
                return old['run_id']
            rid=uid('sf')
            run_context = external_context.for_run(rid)
            plan={'schema':'benchforge.pipeline/v1','intents':intents,'workflow':workflow,'created':time.time(),'code_version':'0.3.0'}
            if submitted_programs:plan['submitted_programs']=submitted_programs
            plan['context'] = run_context.to_dict()
            c.execute(runs.insert().values(id=rid,state='PENDING',plan=plan,created_at=str(time.time()),code_revision='benchforge-0.2.0'))
            for i,intent in enumerate(intents):
                tid=f'{rid}.scene{i}'
                unit={'intent':intent,'index':i,'workflow':workflow,'phase':workflow if workflow in {'asset','layout','generation'} else 'plan','revision':0}
                unit['run_context'] = run_context.to_dict()
                if submitted_programs and submitted_programs[i] is not None:unit['submitted_program']=submitted_programs[i]
                c.execute(tasks.insert().values(id=tid,run_id=rid,task_id=f'scene{i}',unit=unit,state='PENDING',attempt=0,ready_at=0))
            c.execute(self.keys.insert().values(id=key,run_id=rid))
            self.repo.event(c,rid,None,'benchforge.submitted',{'intents':intents})
            return rid

    def snapshot(self,rid):
        if isinstance(rid,str) and '.scene' in rid and rid.startswith('sf_'):
            raise ValueError(f'Expected run_id, received task_id {rid}; use run_id={rid.split(".")[0]} for status/wait/inspect/cancel, and the full task_id for evidence/retry')
        value=self.repo.status(rid)
        if canonical_schema(value['plan'].get('schema')) != 'benchforge.pipeline/v1':
            raise ValueError('not a BenchForge run')
        return value

    def update(self,tid,*,expected_state=None,expected_owner=None,**fields):
        with self.repo.transaction() as c:
            old=c.execute(select(tasks).where(tasks.c.id==tid).with_for_update()).mappings().one()
            run=c.execute(select(runs).where(runs.c.id==old['run_id'])).mappings().one()
            if expected_state is not None and old['state'] != expected_state:
                raise ValueError(f'task {tid} state changed before update')
            if expected_owner is not None and old['lease_owner'] != expected_owner:
                raise ValueError(f'task {tid} stage lease ownership changed')
            if run['state']=='CANCELED' and fields.get('state')!='CANCELED':return
            if fields.get('state')=='SUCCEEDED' and old['unit'].get('workflow','scene')=='scene':
                from .scene_acceptance import require_accepted
                require_accepted(
                    self.root,
                    self.directory(tid,old['unit']['revision']),
                    old['unit'].get('intent', {}).get('execution_mode'),
                )
            if 'unit' in fields:fields['unit']={**old['unit'],**fields['unit']}
            if fields.get('state') not in (None, 'RUNNING'):
                fields.setdefault('lease_owner', None)
                fields.setdefault('lease_expires_at', None)
            conditions = [tasks.c.id == tid, tasks.c.state == old['state']]
            if old['lease_owner'] is None:
                conditions.append(tasks.c.lease_owner.is_(None))
            else:
                conditions.append(tasks.c.lease_owner == old['lease_owner'])
            updated = c.execute(tasks.update().where(*conditions).values(**fields))
            if updated.rowcount != 1:
                raise ValueError(f'task {tid} changed before update')
            self.repo.event(c,old['run_id'],tid,'benchforge.transition',{'state':fields.get('state',old['state']),'phase':fields.get('unit',old['unit']).get('phase')})

    def claim_stage(self, tid, owner, lease_seconds=60):
        """Atomically claim or recover one non-capture stage for a single owner."""
        now = time.time()
        with self.repo.transaction() as c:
            task = c.execute(select(tasks).where(tasks.c.id == tid).with_for_update()).mappings().first()
            if not task or task['unit'].get('phase') == 'capture':
                return None
            run = c.execute(select(runs).where(runs.c.id == task['run_id']).with_for_update()).mappings().one()
            if run['state'] == 'CANCELED' or (task.get('ready_at') or 0) > now:
                return None
            available = task['state'] in {'PENDING', 'READY'}
            expired = task['state'] == 'RUNNING' and (
                task.get('lease_expires_at') is None or task['lease_expires_at'] <= now
            )
            if not (available or expired):
                return None
            unit = dict(task['unit'])
            base_context = RunContext.from_record(run['plan'].get('context')) or RunContext()
            if not base_context.run_id:
                base_context = base_context.for_run(run['id'])
            unit['run_context'] = base_context.for_stage(tid, owner).to_dict()
            conditions = [tasks.c.id == tid, tasks.c.state == task['state']]
            if task.get('lease_owner') is None:
                conditions.append(tasks.c.lease_owner.is_(None))
            else:
                conditions.append(tasks.c.lease_owner == task['lease_owner'])
            if expired and task.get('lease_expires_at') is not None:
                conditions.append(tasks.c.lease_expires_at <= now)
            result = c.execute(
                tasks.update()
                .where(*conditions)
                .values(
                    state='RUNNING',
                    unit=unit,
                    lease_owner=owner,
                    lease_expires_at=now + lease_seconds,
                    failure=None,
                )
            )
            if result.rowcount != 1:
                return None
            claimed = c.execute(select(tasks).where(tasks.c.id == tid)).mappings().one()
            self.repo.event(
                c,
                task['run_id'],
                tid,
                'benchforge.stage_claimed',
                {'phase': unit.get('phase'), 'attempt_id': owner},
            )
            return dict(claimed)

    def renew_stage(self, tid, owner, lease_seconds=60):
        now = time.time()
        with self.repo.transaction() as c:
            result = c.execute(
                tasks.update()
                .where(
                    tasks.c.id == tid,
                    tasks.c.state == 'RUNNING',
                    tasks.c.lease_owner == owner,
                )
                .values(lease_expires_at=now + lease_seconds)
            )
            return result.rowcount == 1

    def retry(self,tid,feedback=None,capture_mode='auto'):
        """Retain old attempts and retry the failed stage; never mutate successful products."""
        if capture_mode not in {'auto','resume_upload','restart_capture'}:
            raise ValueError('capture_mode must be auto, resume_upload or restart_capture')
        if feedback is not None and (not isinstance(feedback,str) or not 1<=len(feedback)<=12000):
            raise ValueError('retry feedback must be 1..12000 characters')
        with self.repo.transaction() as c:
            self.repo.lock_queue(c)
            task=c.execute(select(tasks).where(tasks.c.id==tid).with_for_update()).mappings().one()
            run=c.execute(select(runs).where(runs.c.id==task['run_id']).with_for_update()).mappings().one()
            if task['unit'].get('phase') == 'dataset':
                raise ValueError('Legacy dataset jobs are retired. Use data.capability or submit a scene with target_items.')
            if run['state'] in {'CANCELED','SUCCEEDED'}:raise ValueError('cannot retry a canceled or successful run')
            if task['state']!='FAILED_FINAL':raise ValueError('only failed tasks need retry')
            recovery_id=None
            from .scene_acceptance import policy_for
            if policy_for(self.root) and task['unit'].get('workflow','scene')=='scene':
                from .scene_acceptance import admit_program
                from .scene_design import capture_retry_directory,review_retry_directory
                mode = task['unit'].get('intent', {}).get('execution_mode')
                capture_failure=(task['unit']['phase']=='capture' and
                    (task.get('failure') or {}).get('stage') in {'capture_transport','capture_execution'} and feedback is None)
                review_failure=(task['unit']['phase']=='review' and feedback is None and
                    (task.get('failure') or {}).get('error') in {'TimeoutError','URLError','ConnectionError','OSError','RemoteDisconnected','ConnectionResetError','ConnectionAbortedError'})
                if not capture_failure and not review_failure:
                    raise ValueError('Only review transport or capture execution/transport failures can retry; repair scene quality through capture/refine')
                directory=(capture_retry_directory(self.root,tid,task['unit']['revision']) if capture_failure
                    else review_retry_directory(self.root,tid))
                admit_program(self.root,json.loads((directory/'program.json').read_text()),execution_mode=mode)
                if review_failure and task['unit'].get('review_transport_retries',0)>=2:
                    marker=self.root/'model_transport_recovery.json'
                    recovery=json.loads(marker.read_text()) if marker.is_file() and marker.stat().st_size<4096 else {}
                    recovery_id=recovery.get('recovery_id') if recovery.get('status')=='transport_verified' else None
                    if not isinstance(recovery_id,str) or not recovery_id or recovery_id==task['unit'].get('review_transport_recovery_id'):
                        raise ValueError('Review transport recovery budget exhausted')
            unit=dict(task['unit']);phase=unit['phase'];old=self.directory(tid,unit['revision'])
            if capture_mode!='auto' and not (phase=='capture' and (task.get('failure') or {}).get('stage') in {'capture_transport','capture_execution'}):
                raise ValueError('capture_mode applies only to capture execution/transport failures')
            if recovery_id:
                unit.update(review_transport_recovery_id=recovery_id,previous_review_transport_retries=unit.get('review_transport_retries',0),review_transport_retries=0)
            if policy_for(self.root) and phase=='review':unit['review_transport_retries']=unit.get('review_transport_retries',0)+1
            if phase=='capture' and (task.get('failure') or {}).get('stage') in {'capture_transport','capture_execution'}:
                # A crash needs a fresh executor attempt. A completed capture only needs upload.
                ended=unit.pop('worker_end',{})
                receipt=ended.get('capture_receipt')
                if receipt is not None:
                    from .capture_recovery import require_capture_receipt
                    require_capture_receipt(receipt,self._job(task,ended['token']))
                mode=capture_mode
                if mode=='auto':mode='resume_upload' if receipt is not None else 'restart_capture'
                unit.pop('resume_capture_token',None)
                unit.pop('capture_resume_receipt',None)
                if mode=='resume_upload':
                    if receipt is None:raise ValueError('resume_upload needs a validated native capture receipt; restart_capture recovers unfinished execution')
                    unit['resume_capture_token']=ended['token']
                    unit['capture_resume_receipt']=receipt
                unit['capture_recovery_mode']=mode
                unit['capture_attempt_history']=[*unit.get('capture_attempt_history',[]),{**ended,'recovery_mode':mode}]
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
            c.execute(tasks.update().where(tasks.c.id==tid).values(state='READY',unit=unit,failure=None,result=None,ready_at=0,lease_owner=None,lease_expires_at=None))
            self.repo.event(c,run['id'],tid,'benchforge.retry',{'phase':unit['phase'],'revision':unit['revision'],'operator_feedback':feedback})
        return {'task_id':tid,'revision':unit['revision'],'phase':unit['phase'],
                **({'capture_recovery_mode':unit['capture_recovery_mode']} if phase=='capture' and 'capture_recovery_mode' in unit else {})}

    def all_work(self, connection=None):
        query=select(tasks).join(runs,tasks.c.run_id==runs.c.id).where(runs.c.code_revision=='benchforge-0.2.0',runs.c.state.notin_(['CANCELED','SUCCEEDED','FAILED_FINAL']))
        if connection is not None:
            return [dict(r) for r in connection.execute(query).mappings()]
        with self.repo.engine.connect() as c:
            return [dict(r) for r in c.execute(query).mappings()]

    def directory(self,tid,revision):
        directory=safe_path(self.root,f'{tid}/revision_{revision}')
        directory.mkdir(parents=True,exist_ok=True)
        return directory

    def claim_desktop(self,worker):
        with self.repo.transaction() as c:
            self.repo.lock_queue(c)
            device=c.execute(select(self.device).where(self.device.c.id=='desktop-isaac')).mappings().first()
            if device and device['record'].get('active'):
                record=device['record']
                if record['worker']!=worker: return {'waiting':'device_owned_by_other_worker'}
                task=c.execute(select(tasks).where(tasks.c.id==record['task_id'])).mappings().one()
                return self._job(task,record['token'])
            for task in self.all_work(c):
                if task['state']=='READY' and task['unit']['phase']=='capture':
                    unit=dict(task['unit'])
                    token=unit.pop('resume_capture_token',None) or uid('attempt')
                    run=c.execute(select(runs).where(runs.c.id==task['run_id'])).mappings().one()
                    base_context=RunContext.from_record(run['plan'].get('context')) or RunContext()
                    if not base_context.run_id:
                        base_context=base_context.for_run(run['id'])
                    unit['run_context']=base_context.for_stage(task['id'],token).to_dict()
                    record={'active':True,'worker':worker,'task_id':task['id'],'token':token,'time':time.time()}
                    if device:c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record=record))
                    else:c.execute(self.device.insert().values(id='desktop-isaac',record=record))
                    claimed=c.execute(tasks.update().where(
                        tasks.c.id==task['id'],tasks.c.state=='READY',tasks.c.lease_owner.is_(None)
                    ).values(state='RUNNING',unit=unit,lease_owner=token,lease_expires_at=time.time()+1800))
                    if claimed.rowcount != 1:
                        raise ValueError('capture task ownership changed before claim')
                    self.repo.event(c,task['run_id'],task['id'],'benchforge.desktop_claim',{'token':token})
                    return self._job(task,token)
            return {'waiting':'no_jobs'}

    def _job(self,task,token):
        directory=self.directory(task['id'],task['unit']['revision'])
        program=normalize_native_asset_references(json.loads((directory/'program.json').read_text()))
        assets=sorted({o['asset_id'] for o in program['objects'] if o['kind']=='mesh'})
        return {'task_id':task['id'],'revision':task['unit']['revision'],'token':token,
                'program':program,'assets':assets,'transport_retry':task['unit'].get('transport_retry',0),
                'capture_options':task['unit']['intent'].get('capture_options',{}),
                'capture':{'width':960,'height':720,'steps':180,'dt':1/60},
                **{key:task['unit'][key] for key in ('capture_recovery_mode','capture_resume_receipt') if key in task['unit']}}

    def desktop_state(self):
        with self.repo.engine.connect() as c:
            row=c.execute(select(self.device).where(self.device.c.id=='desktop-isaac')).mappings().first()
            return row['record'] if row else {'active':False}

    def worker_update(self,job,progress=None,outcome=None,processes_stopped=False,error=None,capture_complete=None,capture_receipt=None):
        """A terminal acknowledgement releases only the matching device lease."""
        from .progress import record_progress
        with self.repo.transaction() as c:
            self.repo.lock_queue(c)
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
                if type(capture_complete) is bool:end['capture_complete']=capture_complete
                if capture_receipt is not None:
                    from .capture_recovery import require_capture_receipt
                    require_capture_receipt(capture_receipt,self._job(task,job['token']))
                    end.update(capture_complete=True,capture_receipt=capture_receipt)
                failure=None if canceled else {'stage':'capture_transport' if capture_receipt is not None else 'capture_execution',
                    'error':str(error or 'desktop attempt failed')[:1000],'local_capture_preserved':True}
                c.execute(tasks.update().where(tasks.c.id==task['id']).values(state=state,lease_owner=None,lease_expires_at=None,unit={**task['unit'],'worker_end':end},failure=failure))
                c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record={'active':False,'last_end':end}))
                self.repo.event(c,task['run_id'],task['id'],'benchforge.desktop_finished',{'end':end,'failure':failure})
                record_progress(self.directory(task['id'],job['revision']),'canceled' if canceled else 'failed',worker=end,error=failure)
                return {'finished':True,'state':state,'local_capture_preserved':True}
            if task['state']!='RUNNING':raise ValueError('desktop task is not running')
            if progress:
                if progress.get('stage') not in {'capture','upload','upload_retry','capture_transport_failed'}:raise ValueError('invalid desktop progress stage')
                record_progress(self.directory(task['id'],job['revision']),**progress)
            c.execute(tasks.update().where(
                tasks.c.id==task['id'],
                tasks.c.state=='RUNNING',
                tasks.c.lease_owner==job['token'],
            ).values(lease_expires_at=time.time()+1800))
            return {'cancel':canceled,'active':True}

    def commit_capture(self,job,upload):
        with self.repo.transaction() as c:
            self.repo.lock_queue(c)
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
            c.execute(tasks.update().where(
                tasks.c.id==task['id'],
                tasks.c.state=='RUNNING',
                tasks.c.lease_owner==job['token'],
            ).values(state='READY',unit=unit,lease_owner=None,lease_expires_at=None))
            c.execute(self.device.update().where(self.device.c.id=='desktop-isaac').values(record={'active':False}))
            self.repo.event(c,task['run_id'],task['id'],'benchforge.capture_committed',{'report':report})
            return {'committed':True}

    def settle_runs(self):
        with self.repo.transaction() as c:
            for r in c.execute(select(runs).where(runs.c.code_revision=='benchforge-0.2.0')).mappings():
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
            self.repo.event(c,rid,None,'benchforge.cancel_requested')
