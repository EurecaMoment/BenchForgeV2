import threading
import unittest
from unittest.mock import Mock,patch
from sqlalchemy.exc import TimeoutError
from benchforge_backend.engine import coordinate


class QueueRecoveryTests(unittest.TestCase):
    def test_database_timeout_does_not_end_coordinator(self):
        store=Mock();stop=threading.Event()
        store.all_work.side_effect=[TimeoutError('pool busy'),[]]
        store.settle_runs.side_effect=stop.set
        with patch.object(stop,'wait',return_value=False),patch('benchforge_backend.engine.traceback.print_exc'):
            coordinate(store,stop)
        self.assertEqual(store.all_work.call_count,2)
        store.settle_runs.assert_called_once()
        store.update.assert_not_called()


if __name__=='__main__':unittest.main()
