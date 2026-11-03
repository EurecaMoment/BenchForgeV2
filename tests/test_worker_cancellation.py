import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

spec=importlib.util.spec_from_file_location('worker_cancellation',Path(__file__).resolve().parents[1]/'integrations/spatialforge/worker_cancellation.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CancellationTests(unittest.TestCase):
    def test_successful_remote_capture_can_acknowledge_late_cancel(self):
        client=Mock();client.call.side_effect=[{'status':'succeeded'},{'state':{'active_job':None}}]
        api=Mock(return_value={'finished':True})
        job={'task_id':'scene.scene0','revision':0,'token':'attempt-one','transport_retry':2}
        self.assertTrue(module.finish_canceled_capture(job,'job-one',client,api)['finished'])
        self.assertEqual(api.call_args.args[0],'/worker/finish')
        self.assertEqual(api.call_args.args[1]['job'],job)
        self.assertEqual(api.call_args.args[1]['outcome'],'canceled')

    def test_active_remote_executor_never_releases_device(self):
        for replies in ([{'status':'running'}],[{'status':'succeeded'},{'state':{'active_job':'job-one'}}]):
            client=Mock();client.call.side_effect=replies;api=Mock()
            with self.assertRaises(RuntimeError):
                module.finish_canceled_capture({'task_id':'scene.scene0','revision':0,'token':'one'},'job-one',client,api)
            api.assert_not_called()
