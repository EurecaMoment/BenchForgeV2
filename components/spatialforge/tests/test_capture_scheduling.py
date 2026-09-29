import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event,Thread
import unittest
from unittest.mock import patch
from spatialforge import engine


class CaptureScheduling(unittest.TestCase):
    def test_capture_preparation_and_receipt_progress_while_three_generators_block(self):
        stop=Event();release=Event();prepared=Event();finished=Event();started=[]
        jobs=[{'id':f'asset{i}','run_id':f'run{i}','state':'PENDING','unit':{
            'phase':'asset','revision':0,'intent':{'name':f'asset{i}','description':'test'}}} for i in range(4)]
        direct={'phase':'plan','revision':0,'intent':{'capture_only':True},
                'submitted_program':{'program':{'objects':[{'kind':'box'}]}}}
        jobs.append({'id':'capture','run_id':'capture-run','state':'PENDING','unit':direct})
        jobs.append({'id':'receipt','run_id':'receipt-run','state':'PENDING',
                     'unit':{'phase':'review','revision':0,'intent':{'capture_only':True}}})
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            capture=root/'receipt/capture';capture.mkdir(parents=True)
            (capture/'report.json').write_text(json.dumps({'status':'captured'}))
            class Store:
                def __init__(self):self.root=root
                def all_work(self):return deepcopy(jobs)
                def directory(self,task_id,revision):return root/task_id
                def snapshot(self,*args):return {'state':'RUNNING'}
                def settle_runs(self):pass
                def update(self,task_id,**fields):
                    row=next(t for t in jobs if t['id']==task_id);row.update(fields)
                    if task_id=='receipt' and fields.get('state')=='SUCCEEDED':finished.set()
            class Tools:
                def __init__(self,*args):pass
                def generate_asset(self,spec,*args):
                    started.append(spec['label']);release.wait(10);return {'asset_id':'fixture'}
            def prepare(store,task,signal):
                prepared.set();store.update(task['id'],state='READY',unit={**task['unit'],'phase':'capture'})
            with patch.object(engine,'GenerationTools',Tools),patch.object(engine,'plan_scene',prepare), \
                 patch.object(engine,'review_generated_asset',side_effect=lambda tools,spec,result,*a,**k:result):
                thread=Thread(target=engine.coordinate,args=(Store(),stop));thread.start()
                try:
                    self.assertTrue(prepared.wait(4),'capture starved behind generators')
                    self.assertTrue(finished.wait(5),'capture receipt starved behind generators')
                    self.assertEqual(len(started),3,'generation concurrency must remain three')
                    self.assertEqual(jobs[3]['state'],'PENDING')
                finally:
                    stop.set();release.set();thread.join(5)
                self.assertFalse(thread.is_alive())

    def test_generation_and_planner_work_stays_on_production_pool(self):
        base={'phase':'plan','intent':{},'submitted_program':{'program':{'objects':[{'kind':'mesh'}]}}}
        self.assertTrue(engine._capture_handoff(base))
        for change in [dict(quality_repairs=1),dict(operator_feedback='repair'),
                       dict(intent={'layout':{'mode':'diffusion'}}),
                       dict(submitted_program={'program':{'objects':[{'kind':'generated'}]}})]:
            self.assertFalse(engine._capture_handoff({**base,**change}))
        self.assertFalse(engine._capture_handoff({'phase':'review','intent':{}}))


if __name__=='__main__':unittest.main()
