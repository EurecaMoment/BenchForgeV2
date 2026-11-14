"""Lifecycle regressions for reuse, incompatible boots and interrupted dispatch."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import isaac_capture
import isaac_resident
import worker


class Settings:
    def __init__(self):self.values={key:0 for key in isaac_capture.RENDER_SETTING_KEYS}
    def get(self,key):return self.values.get(key)
    def set(self,key,value):self.values[key]=value
    def destroy_item(self,key):self.values.pop(key,None)


class Process:
    pid=42
    def active(self):return True
    def close(self):pass


class ResidentTests(unittest.TestCase):
    def test_next_task_restores_default_exposure_and_sampling(self):
        settings=Settings();defaults=dict(settings.values)
        isaac_capture.apply_render_settings(settings,defaults,{'renderer':'PathTracing','samples_per_pixel':64,'exposure':2})
        self.assertEqual(settings.get('/rtx/post/tonemap/filmIso'),400.)
        isaac_capture.apply_render_settings(settings,defaults,{'renderer':'RaytracedLighting'})
        self.assertEqual(settings.values,defaults)

    def exercise_engine(self,compatible):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'resident';state.mkdir()
            calls=[];apps=[];settings=Settings()
            class App:
                def __init__(self,config):apps.append(self)
                def update(self):pass
                def close(self):pass
            def command(index):
                directory=Path(temp)/str(index);directory.mkdir()
                request=directory/'request.json';request.write_text(json.dumps({'token':str(index),'profile':index if not compatible else 1}))
                isaac_resident.write_json(state/'command.json',{'action':'capture','request':str(request),'output':str(directory/'capture')})
            def capture(job,output,app,**kwargs):
                calls.append((job['token'],app,kwargs['app_reused']))
                self.assertFalse((output.parent/'resident_result.json').exists())
                if job['token']=='1':command(2)
                else:isaac_resident.write_json(state/'command.json',{'action':'shutdown'})
                return 0
            command(1)
            with patch.dict(sys.modules,{'isaacsim':types.SimpleNamespace(SimulationApp=App),'carb':types.SimpleNamespace(settings=types.SimpleNamespace(get_settings=lambda:settings))}),patch.object(isaac_resident,'application_config',side_effect=lambda j:{'renderer':j['profile']}),patch.object(isaac_resident,'run_capture',side_effect=capture):
                isaac_resident.serve(state,1)
            self.assertEqual(len(apps),1)
            if compatible:
                self.assertEqual([c[2] for c in calls],[False,True]);self.assertIs(calls[0][1],calls[1][1])
                self.assertEqual(json.loads((Path(temp)/'2/resident_result.json').read_text())['state'],'complete')
            else:
                self.assertEqual(len(calls),1)
                self.assertEqual(json.loads((Path(temp)/'2/resident_result.json').read_text())['state'],'restart_required')

    def test_compatible_tasks_share_one_app(self):self.exercise_engine(True)
    def test_incompatible_boot_never_executes_in_old_app(self):self.exercise_engine(False)

    def test_report_is_not_completion_and_restart_adopts_same_job(self):
        with tempfile.TemporaryDirectory() as temp:
            worker.state_root=Path(temp);worker.config={}
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            directory=Path(temp)/job['token'];output=directory/'capture';output.mkdir(parents=True)
            (directory/'resident.json').write_text(json.dumps({'started_at':worker.time.time()}))
            (output/'report.json').write_text('{"status":"captured"}')
            def complete(_):worker.write_json(directory/'resident_result.json',{'token':job['token'],'state':'complete'})
            with patch.object(worker,'resident_processes',return_value=[Process()]),patch.object(worker,'api',return_value={}),patch.object(worker.time,'sleep',side_effect=complete),patch.object(worker.subprocess,'Popen',side_effect=AssertionError('duplicate Isaac launch')):
                self.assertEqual(worker.run_resident(job,directory,[])['state'],'complete')

    def test_cancel_stops_owned_engine_before_returning(self):
        with tempfile.TemporaryDirectory() as temp:
            worker.state_root=Path(temp);worker.config={}
            job={'token':'attempt_0123456789abcdef','task_id':'test.scene0','revision':0}
            directory=Path(temp)/job['token'];directory.mkdir()
            (directory/'resident.json').write_text(json.dumps({'started_at':worker.time.time()}))
            with patch.object(worker,'resident_processes',return_value=[Process()]),patch.object(worker,'api',return_value={'cancel':True}),patch.object(worker,'stop_resident') as stop:
                self.assertEqual(worker.run_resident(job,directory,[])['error'],'canceled')
            stop.assert_called_once()


if __name__=='__main__':unittest.main()
