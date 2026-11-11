"""Protect immutable results and reject concurrent advancement of one run."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchforge_core.artifact_io import read_json, write_json, write_jsonl
from benchforge_core.pipelines.execution_lock import RunBusyError, exclusive_run
from benchforge_core.pipelines.runner import run


class PipelineRecoveryTests(unittest.TestCase):
    def test_serialization_failure_preserves_previous_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'state.json'
            write_json(path, {'state': 'waiting', 'receipt': 'retained'})
            with self.assertRaises(TypeError):
                write_json(path, {'state': {'not-json'}})
            self.assertEqual(read_json(path)['receipt'], 'retained')
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['state.json'])

    def test_failed_jsonl_generator_keeps_previous_complete_file(self):
        def failing_rows():
            yield {'item_id': 'partial'}
            raise RuntimeError('source interrupted')

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'questions.jsonl'
            write_jsonl(path, [{'item_id': 'accepted'}])
            previous = path.read_text(encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'source interrupted'):
                write_jsonl(path, failing_rows())
            self.assertEqual(path.read_text(encoding='utf-8'), previous)

    def test_running_pipeline_is_rejected_before_plan_or_state_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / 'plan.json'
            write_json(plan, {'steps': [], 'inputs': {}})
            execution = root / 'execution'
            with exclusive_run(execution):
                with self.assertRaises(RunBusyError):
                    run({'plan': str(plan), 'run': str(execution), '_workspace': str(root)}, root)
            self.assertFalse((execution / 'plan.json').exists())
            self.assertFalse((execution / 'state.json').exists())
            result = run({'plan': str(plan), 'run': str(execution), '_workspace': str(root)}, root)
            self.assertEqual(result['state'], 'completed')

    def test_another_process_cannot_acquire_an_owned_run(self):
        script = (
            'import sys\n'
            'from benchforge_core.pipelines.execution_lock import exclusive_run, RunBusyError\n'
            'try:\n'
            '    with exclusive_run(sys.argv[1]): pass\n'
            'except RunBusyError:\n'
            '    sys.exit(23)\n'
        )
        with tempfile.TemporaryDirectory() as temporary:
            with exclusive_run(temporary):
                result = subprocess.run(
                    [sys.executable, '-c', script, temporary],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 23, result.stderr)
            result = subprocess.run(
                [sys.executable, '-c', script, temporary],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
