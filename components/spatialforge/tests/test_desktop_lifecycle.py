"""Exercise real SQL state transitions on isolated SQLite; no live jobs."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from sqlalchemy import select
from spatialforge.storage import Store, runs, tasks

JOB={'task_id':'sf_test.scene0','revision':0,'token':'attempt_0123456789abcdef'}


class LifecycleTests(unittest.TestCase):
    def test_task_id_used_as_run_id_has_actionable_feedback(self):
        with self.assertRaisesRegex(ValueError,'use run_id=sf_test'):
            self.store.snapshot('sf_test.scene0')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        (self.folder/'deployment.local.json').write_text(json.dumps({'database_url':'sqlite:///'+str(self.folder/'test.db')}))
        self.store=Store(self.folder/'artifacts',self.folder)
        transaction=self.store.repo.transaction
        @contextmanager
        def sqlite_transaction():
            with transaction() as connection:
                class Connection:
                    def exec_driver_sql(self,sql):
                        if sql.startswith('SELECT pg_advisory_xact_lock'):return
                        return connection.exec_driver_sql(sql)
                    def execute(self,*args,**kwargs):return connection.execute(*args,**kwargs)
                yield Connection()
        self.store.repo.transaction=sqlite_transaction
        with self.store.repo.transaction() as c:
            c.execute(runs.insert().values(id='sf_test',state='CANCELED',plan={'schema':'spatialforge.pipeline/v1'},code_revision='spatialforge-0.2.0'))
            c.execute(tasks.insert().values(id=JOB['task_id'],run_id='sf_test',unit={'revision':0,'phase':'capture'},state='RUNNING',lease_owner=JOB['token']))
            c.execute(self.store.device.insert().values(id='desktop-isaac',record={'active':True,'task_id':JOB['task_id'],'token':JOB['token']}))

    def tearDown(self):
        self.store.repo.engine.dispose();self.temp.cleanup()

    def test_cancel_requires_process_ack_and_duplicate_cannot_release_new_owner(self):
        with self.assertRaisesRegex(ValueError,'stopped'):self.store.worker_update(JOB,outcome='canceled')
        self.assertTrue(self.store.desktop_state()['active'])
        result=self.store.worker_update(JOB,outcome='canceled',processes_stopped=True)
        self.assertEqual(result['state'],'CANCELED');self.assertFalse(self.store.desktop_state()['active'])
        new={'active':True,'task_id':'another.scene0','token':'attempt_1111111111111111'}
        with self.store.repo.transaction() as c:c.execute(self.store.device.update().values(record=new))
        self.assertTrue(self.store.worker_update(JOB,outcome='canceled',processes_stopped=True)['duplicate'])
        self.assertEqual(self.store.desktop_state(),new)
        with self.assertRaisesRegex(ValueError,'stale'):self.store.worker_update({**JOB,'token':'attempt_2222222222222222'},outcome='failed',processes_stopped=True)
        self.assertEqual(self.store.desktop_state(),new)

    def test_transport_failure_visible_and_explicit_retry_reuses_capture_token(self):
        with self.store.repo.transaction() as c:c.execute(runs.update().values(state='RUNNING'))
        self.store.worker_update(JOB,progress={'stage':'upload_retry','errors':5,'error':'disconnected'})
        self.store.worker_update(JOB,outcome='failed',processes_stopped=True,error='five network failures')
        self.store.settle_runs()
        snap=self.store.snapshot('sf_test')
        self.assertEqual(snap['state'],'FAILED_FINAL')
        self.assertIn('five network failures',snap['tasks'][0]['failure']['error'])
        self.store.retry(JOB['task_id'])
        snap=self.store.snapshot('sf_test')
        self.assertEqual(snap['tasks'][0]['unit']['resume_capture_token'],JOB['token'])
        self.assertEqual(snap['tasks'][0]['unit']['transport_retry'],1)
        self.assertNotIn('worker_end',snap['tasks'][0]['unit'])
        with self.assertRaisesRegex(ValueError,'retry generation'):self.store.worker_update(JOB,outcome='failed',processes_stopped=True)


if __name__=='__main__':unittest.main()
