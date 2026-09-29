"""The database is authoritative. Manifests and reports are exports."""
from __future__ import annotations

import time
from contextlib import contextmanager

from sqlalchemy import JSON, Column, Float, Integer, MetaData, String, Table, create_engine, select, update

from .domain import ArtifactRef, Plan, State, TERMINAL, HarnessError, WorkResult, now, uid

schema = MetaData()
runs = Table('runs', schema, Column('id', String, primary_key=True), Column('state', String, nullable=False),
             Column('plan', JSON, nullable=False), Column('created_at', String), Column('code_revision', String))
tasks = Table('work_items', schema, Column('id', String, primary_key=True), Column('run_id', String, nullable=False, index=True),
              Column('task_id', String), Column('unit', JSON), Column('state', String), Column('attempt', Integer),
              Column('lease_owner', String), Column('lease_expires_at', Float), Column('ready_at', Float),
              Column('result', JSON), Column('artifact', JSON), Column('failure', JSON))
events = Table('events', schema, Column('id', Integer, primary_key=True, autoincrement=True),
               Column('run_id', String, index=True), Column('work_item_id', String), Column('event', String),
               Column('at', String), Column('payload', JSON))
artifacts = Table('artifacts', schema, Column('id', String, primary_key=True), Column('run_id', String),
                  Column('work_item_id', String), Column('record', JSON))
releases = Table('releases', schema, Column('id', String, primary_key=True), Column('run_id', String, unique=True),
                 Column('state', String), Column('record', JSON))
visible_items = Table('visible_items', schema, Column('id', String, primary_key=True), Column('release_id', String), Column('record', JSON))
answers = Table('answer_records', schema, Column('id', String, primary_key=True), Column('release_id', String), Column('record', JSON))
evaluations = Table('evaluations', schema, Column('id', String, primary_key=True), Column('release_id', String),
                    Column('record', JSON), Column('predictions', JSON))
agent_sessions = Table('local_agent_sessions', schema, Column('id', String, primary_key=True),
                       Column('state', String, nullable=False), Column('run_id', String, unique=True),
                       Column('record', JSON, nullable=False))


class Repository:
    def __init__(self, url: str):
        if not url.startswith(('sqlite:', 'postgresql+psycopg:')):
            raise HarnessError('DATABASE_BACKEND', 'Use SQLite locally or PostgreSQL with psycopg')
        self.engine = create_engine(url, connect_args={'timeout': 30} if url.startswith('sqlite:') else {}, hide_parameters=True)
        schema.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            if self.engine.dialect.name == 'sqlite':
                conn.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                conn.begin()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def event(conn, run_id, task_id, event, payload=None):
        conn.execute(events.insert().values(run_id=run_id, work_item_id=task_id, event=event, at=now(), payload=payload or {}))

    def submit(self, plan: Plan, code_revision='0.1.0', agent_session_id=None):
        run_id = uid('run')
        with self.transaction() as conn:
            if agent_session_id:
                session=conn.execute(select(agent_sessions).where(agent_sessions.c.id==agent_session_id).with_for_update()).mappings().one()
                if session['run_id']:
                    return session['run_id']
            conn.execute(runs.insert().values(id=run_id, state='PENDING', plan=plan.model_dump(mode='json'), created_at=now(), code_revision=code_revision))
            for unit in plan.tasks:
                conn.execute(tasks.insert().values(id=f'{run_id}.{unit.task_id}', run_id=run_id, task_id=unit.task_id,
                             unit=unit.model_dump(mode='json'), state=State.PENDING, attempt=0, ready_at=0))
            self.event(conn, run_id, None, 'run.submitted')
            if agent_session_id:
                conn.execute(update(agent_sessions).where(agent_sessions.c.id==agent_session_id).values(run_id=run_id))
                self.event(conn,run_id,None,'agent.run_linked',{'session_id':agent_session_id})
        return run_id

    def status(self, run_id):
        with self.engine.connect() as conn:
            run = conn.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
            if run is None:
                raise HarnessError('RUN_NOT_FOUND', run_id)
            work = conn.execute(select(tasks).where(tasks.c.run_id == run_id).order_by(tasks.c.id)).mappings().all()
            return {**dict(run), 'tasks': [dict(row) for row in work]}

    def revise_agent_run(self,sid,expected_run,plan,decision):
        """Atomically link an upstream revision; terminal evidence is immutable."""
        run_id=uid('run')
        with self.transaction() as conn:
            session=conn.execute(select(agent_sessions).where(agent_sessions.c.id==sid).with_for_update()).mappings().one()
            old=conn.execute(select(runs).where(runs.c.id==expected_run).with_for_update()).mappings().one()
            if session['run_id']!=expected_run or old['state'] not in {'QUARANTINED','FAILED_FINAL'}:
                raise HarnessError('REPAIR_STATE','Only the current failed or quarantined run can be revised')
            conn.execute(runs.insert().values(id=run_id,state='PENDING',plan=plan.model_dump(mode='json'),created_at=now(),code_revision='0.1.0'))
            for unit in plan.tasks:
                conn.execute(tasks.insert().values(id=f'{run_id}.{unit.task_id}',run_id=run_id,task_id=unit.task_id,
                    unit=unit.model_dump(mode='json'),state=State.PENDING,attempt=0,ready_at=0))
            record=dict(session['record']);history=list(record.get('quality_repairs',[]))
            if 'diagnosis' in record:
                record.setdefault('diagnosis_history',[]).append({'run_id':expected_run,'diagnosis':record.pop('diagnosis')})
            history.append({'previous_run':expected_run,'new_run':run_id,**decision})
            record.update(spec=plan.spec.model_dump(mode='json'),phase='upstream_repair',quality_repairs=history)
            record['compiled_tasks']=[{'task_id':t.task_id,'plugin_id':t.plugin_id,'depends_on':t.depends_on} for t in plan.tasks]
            conn.execute(update(agent_sessions).where(agent_sessions.c.id==sid).values(run_id=run_id,state='RUNNING',record=record))
            self.event(conn,run_id,None,'agent.upstream_revision',history[-1])
        return run_id

    def claim(self, run_id):
        with self.transaction() as conn:
            run = conn.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().one()
            if run['state'] in {'CANCELED', 'SUCCEEDED'}:
                return None
            rows = conn.execute(select(tasks).where(tasks.c.run_id == run_id)).mappings().all()
            by_name = {row['task_id']: row for row in rows}
            running = [row for row in rows if row['state'] == State.RUNNING]
            used = {key: sum(r['unit']['resources'][key] for r in running) for key in ('cpu', 'gpu', 'memory_gb')}
            capacity = run['plan']['spec']['capacity']
            for row in rows:
                if row['state'] not in {State.PENDING, State.READY, State.FAILED_RETRYABLE} or row['ready_at'] > time.time():
                    continue
                if any(by_name[d]['state'] != State.SUCCEEDED for d in row['unit']['depends_on']):
                    continue
                if any(used[k] + row['unit']['resources'][k] > capacity[k] for k in used):
                    continue
                token = uid('attempt')
                expiry = time.time() + row['unit']['retry']['timeout_seconds'] + 10
                values = dict(state=State.RUNNING, attempt=row['attempt']+1, lease_owner=token,
                              lease_expires_at=expiry, failure=None)
                conn.execute(update(tasks).where(tasks.c.id == row['id']).values(**values))
                conn.execute(update(runs).where(runs.c.id == run_id).values(state=State.RUNNING))
                self.event(conn, run_id, row['id'], 'task.claimed', {'attempt':values['attempt'], 'token':token})
                return {**dict(row), **values}
        return None

    def finish(self, work_id, token, state, result=None, artifact=None, failure=None, allow_expired=False):
        with self.transaction() as conn:
            row = conn.execute(select(tasks).where(tasks.c.id == work_id).with_for_update()).mappings().one()
            if row['state'] != State.RUNNING or row['lease_owner'] != token:
                raise HarnessError('LEASE_LOST', work_id)
            if not allow_expired and row['lease_expires_at'] < time.time():
                raise HarnessError('LEASE_EXPIRED', work_id)
            if state not in {State.SUCCEEDED, State.FAILED_RETRYABLE, State.FAILED_FINAL, State.QUARANTINED, State.BLOCKED_DEPENDENCY}:
                raise HarnessError('INVALID_TRANSITION',str(state))
            if state == State.SUCCEEDED:
                completed=WorkResult.model_validate(result)
                reference=ArtifactRef.model_validate(artifact)
                if completed.status!='succeeded' or (reference.run_id,reference.work_item_id,reference.artifact_id)!=(row['run_id'],row['task_id'],token):
                    raise HarnessError('RESULT_IDENTITY','Successful commit must match the claimed work item')
            if state == State.FAILED_RETRYABLE and row['attempt'] >= row['unit']['retry']['max_attempts']:
                state = State.FAILED_FINAL
            values = dict(state=state, result=result, artifact=artifact, failure=failure,
                          lease_owner=None, lease_expires_at=None,
                          ready_at=time.time()+row['unit']['retry']['backoff_seconds']*(2**max(0,row['attempt']-1)))
            conn.execute(update(tasks).where(tasks.c.id == work_id).values(**values))
            if artifact:
                conn.execute(artifacts.insert().values(id=artifact['artifact_id'], run_id=row['run_id'], work_item_id=work_id, record=artifact))
            self.event(conn, row['run_id'], work_id, 'task.'+str(state).lower(), {'failure':failure, 'artifact_id':artifact['artifact_id'] if artifact else None})

    def refresh(self, run_id):
        with self.transaction() as conn:
            run = conn.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().one()
            if run['state'] == 'CANCELED':
                return 'CANCELED'
            states = conn.execute(select(tasks.c.state).where(tasks.c.run_id == run_id)).scalars().all()
            if all(s == State.SUCCEEDED for s in states):
                state = 'SUCCEEDED'
            elif State.RUNNING in states:
                state = 'RUNNING'
            elif any(s in {State.FAILED_FINAL, State.QUARANTINED} for s in states):
                state = 'FAILED_FINAL'
            elif State.BLOCKED_DEPENDENCY in states:
                state = 'BLOCKED_DEPENDENCY'
            else:
                state = 'PENDING'
            conn.execute(update(runs).where(runs.c.id == run_id).values(state=state))
            return state

    def retry(self, run_id, task_id=None):
        with self.transaction() as conn:
            run = conn.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
            if not run or run['state'] == 'CANCELED':
                raise HarnessError('RUN_NOT_RETRYABLE', run_id)
            condition = (tasks.c.run_id == run_id) & tasks.c.state.in_([State.BLOCKED_DEPENDENCY, State.FAILED_FINAL, State.FAILED_RETRYABLE, State.QUARANTINED])
            if task_id:
                condition &= tasks.c.task_id == task_id
            conn.execute(update(tasks).where(condition).values(state=State.READY, attempt=0, ready_at=0, failure=None))
            conn.execute(update(runs).where(runs.c.id == run_id).values(state='PENDING'))
            self.event(conn, run_id, task_id, 'run.retry_requested')

    def cancel(self, run_id):
        with self.transaction() as conn:
            run = conn.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
            if not run:
                raise HarnessError('RUN_NOT_FOUND', run_id)
            if run['state'] == State.SUCCEEDED:
                raise HarnessError('RUN_ALREADY_COMPLETE', run_id)
            conn.execute(update(runs).where(runs.c.id == run_id).values(state='CANCELED'))
            conn.execute(update(tasks).where((tasks.c.run_id == run_id) & ~tasks.c.state.in_(list(TERMINAL))).values(state=State.CANCELED, lease_owner=None))
            self.event(conn, run_id, None, 'run.canceled')

    def logs(self, run_id):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(events).where(events.c.run_id == run_id).order_by(events.c.id)).mappings()]
