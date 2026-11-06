"""Exercise real SQL state transitions on isolated SQLite; no live jobs."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import select
from spatialforge.storage import Store, runs, tasks
from spatialforge.capture_recovery import local_capture_receipt

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

    def captured_attempt(self):
        directory=self.store.directory(JOB['task_id'],0)
        program={'scene_id':'frozen_fixture','objects':[],'cameras':[{}]}
        (directory/'program.json').write_text(json.dumps(program))
        (directory/'scene_admission.json').write_text('{"enforced":true,"passed":true}')
        with self.store.repo.transaction() as c:
            c.execute(tasks.update().values(unit={'revision':0,'phase':'capture',
                'intent':{'capture_options':{'view_indices':[0],'export_scene':False}}}))
        task=self.store.snapshot('sf_test')['tasks'][0]
        job=self.store._job(task,JOB['token'])
        desktop=self.folder/'desktop'/JOB['token'];capture=desktop/'capture';capture.mkdir(parents=True)
        (desktop/'request.json').write_text(json.dumps(job))
        (capture/'report.json').write_text(json.dumps({'status':'captured','token':JOB['token']}))
        (capture/'evidence.json').write_text(json.dumps({'origin':'isaac_native','token':JOB['token']}))
        for suffix in ('.png','.json','_depth.npy','_semantic.npy','_instance.npy'):
            (capture/('view_0'+suffix)).write_bytes(b'isolated fixture')
        return local_capture_receipt(job,desktop)

    def test_idle_claim_uses_only_its_transaction_connection(self):
        with self.store.repo.transaction() as c:
            c.execute(self.store.device.update().values(record={'active':False}))
        connect=self.store.repo.engine.connect
        calls=[]
        def single_connection(*args,**kwargs):
            calls.append(True)
            if len(calls)>1:raise AssertionError('Claim acquired another connection while holding the queue lock')
            return connect(*args,**kwargs)
        with patch.object(self.store.repo.engine,'connect',side_effect=single_connection):
            self.assertEqual(self.store.claim_desktop('test-worker'),{'waiting':'no_jobs'})
        self.assertEqual(len(calls),1)

    def test_verified_transport_recovery_restores_bounded_retries_without_admitting_quality_failures(self):
        directory=self.store.directory(JOB['task_id'],0);(directory/'program.json').write_text('{}')
        (directory/'capture').mkdir();(directory/'capture/report.json').write_text('{"status":"captured"}')
        unit={'revision':0,'phase':'review','review_transport_retries':2}
        def fail(error,record=unit):
            with self.store.repo.transaction() as c:
                c.execute(runs.update().values(state='FAILED_FINAL'))
                c.execute(tasks.update().values(state='FAILED_FINAL',unit=record,failure={'error':error}))
        fail('RemoteDisconnected')
        with patch('spatialforge.scene_acceptance.policy_for',return_value={'enabled':True}), \
             patch('spatialforge.scene_acceptance.admit_program'), \
             patch('spatialforge.scene_design.review_retry_directory',return_value=directory):
            with self.assertRaisesRegex(ValueError,'budget exhausted'):self.store.retry(JOB['task_id'])
            (self.store.root/'model_transport_recovery.json').write_text(json.dumps({'status':'transport_verified','recovery_id':'restored-tunnel'}))
            self.store.retry(JOB['task_id'])
            restored=self.store.snapshot('sf_test')['tasks'][0]['unit']
            self.assertEqual(restored['review_transport_retries'],1)
            self.assertEqual(restored['review_transport_recovery_id'],'restored-tunnel')
            fail('TimeoutError',{**restored,'review_transport_retries':2})
            with self.assertRaisesRegex(ValueError,'budget exhausted'):self.store.retry(JOB['task_id'])
            fail('SceneQualityError')
            with self.assertRaisesRegex(ValueError,'Only review transport'):self.store.retry(JOB['task_id'])

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
        receipt=self.captured_attempt()
        with self.store.repo.transaction() as c:c.execute(runs.update().values(state='RUNNING'))
        self.store.worker_update(JOB,progress={'stage':'upload_retry','errors':5,'error':'disconnected'})
        self.store.worker_update(JOB,outcome='failed',processes_stopped=True,error='five network failures',capture_receipt=receipt)
        self.store.settle_runs()
        snap=self.store.snapshot('sf_test')
        self.assertEqual(snap['state'],'FAILED_FINAL')
        self.assertIn('five network failures',snap['tasks'][0]['failure']['error'])
        with patch('spatialforge.scene_acceptance.policy_for',return_value={'enabled':True}), \
             patch('spatialforge.scene_acceptance.admit_program'):
            self.store.retry(JOB['task_id'])
        snap=self.store.snapshot('sf_test')
        self.assertEqual(snap['tasks'][0]['unit']['resume_capture_token'],JOB['token'])
        self.assertEqual(snap['tasks'][0]['unit']['transport_retry'],1)
        self.assertEqual(snap['tasks'][0]['unit']['capture_resume_receipt'],receipt)
        self.assertNotIn('worker_end',snap['tasks'][0]['unit'])
        with self.assertRaisesRegex(ValueError,'retry generation'):self.store.worker_update(JOB,outcome='failed',processes_stopped=True)

    def test_capture_boolean_or_changed_frozen_program_cannot_resume_old_capture(self):
        receipt=self.captured_attempt()
        with self.store.repo.transaction() as c:c.execute(runs.update().values(state='RUNNING'))
        foreign=json.loads(json.dumps(receipt));foreign['job']['revision']=1
        with self.assertRaisesRegex(ValueError,'another frozen job'):
            self.store.worker_update(JOB,outcome='failed',processes_stopped=True,capture_receipt=foreign)
        self.assertTrue(self.store.desktop_state()['active'])
        self.store.worker_update(JOB,outcome='failed',processes_stopped=True,capture_complete=True)
        with self.assertRaisesRegex(ValueError,'validated native capture receipt'):
            self.store.retry(JOB['task_id'],capture_mode='resume_upload')
        with self.store.repo.transaction() as c:
            task=self.store.snapshot('sf_test')['tasks'][0]
            c.execute(tasks.update().values(unit={**task['unit'],
                'worker_end':{**task['unit']['worker_end'],'capture_receipt':receipt}}))
        directory=self.store.directory(JOB['task_id'],0)
        changed={**receipt['program'],'scene_id':'another_program'}
        (directory/'program.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'frozen program'):
            self.store.retry(JOB['task_id'])
        self.assertEqual(self.store.snapshot('sf_test')['tasks'][0]['state'],'FAILED_FINAL')

    def test_admitted_executor_crash_retries_same_revision_with_fresh_attempt(self):
        directory=self.store.directory(JOB['task_id'],0)
        (directory/'program.json').write_text('{}')
        (directory/'scene_admission.json').write_text('{"enforced":true,"passed":true}')
        with self.store.repo.transaction() as c:c.execute(runs.update().values(state='RUNNING'))
        self.store.worker_update(JOB,outcome='failed',processes_stopped=True,error='Isaac worker exited')
        with patch('spatialforge.scene_acceptance.policy_for',return_value={'enabled':True}), \
             patch('spatialforge.scene_acceptance.admit_program'):
            result=self.store.retry(JOB['task_id'])
        self.assertEqual(result['revision'],0)
        self.assertEqual(result['capture_recovery_mode'],'restart_capture')
        unit=self.store.snapshot('sf_test')['tasks'][0]['unit']
        self.assertNotIn('resume_capture_token',unit)
        self.assertEqual(unit['capture_attempt_history'][0]['token'],JOB['token'])
        self.assertFalse((directory/'capture/report.json').exists())
        self.assertEqual((directory/'program.json').read_text(),'{}')
        with patch.object(self.store,'_job',side_effect=lambda task,token:{'token':token}):
            claimed=self.store.claim_desktop('recovered-worker')
        self.assertNotEqual(claimed['token'],JOB['token'])
        with self.assertRaisesRegex(ValueError,'retry generation'):
            self.store.worker_update(JOB,outcome='failed',processes_stopped=True)

    def test_capture_retry_admission_does_not_waive_missing_input_or_quality_failure(self):
        from spatialforge.scene_acceptance import check_request
        directory=self.store.directory(JOB['task_id'],0)
        (directory/'program.json').write_text('{}')
        with patch('spatialforge.scene_acceptance.policy_for',return_value={'enabled':True}), \
             patch('spatialforge.scene_acceptance.admit_program'):
            with self.assertRaisesRegex(ValueError,'admitted frozen'):
                check_request(self.store.root,'/retry',{'task_id':JOB['task_id']})
            (directory/'scene_admission.json').write_text('{"passed":true}')
            check_request(self.store.root,'/retry',{'task_id':JOB['task_id']})
            with self.store.repo.transaction() as c:
                c.execute(runs.update().values(state='FAILED_FINAL'))
                c.execute(tasks.update().values(state='FAILED_FINAL',unit={'revision':0,'phase':'review'},failure={'error':'SceneQualityError'}))
            with self.assertRaisesRegex(ValueError,'Only review transport'):
                self.store.retry(JOB['task_id'])


if __name__=='__main__':unittest.main()
