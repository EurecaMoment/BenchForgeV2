"""Focused recovery checks for immutable product publication."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

try:
    from spatialforge import products
except ModuleNotFoundError as exc:
    if exc.name != 'benchclaw':
        raise
    # Product publication can be tested without the optional Harness runtime.
    benchclaw = types.ModuleType('benchclaw')
    benchclaw.__path__ = []
    spatial_tasks = types.ModuleType('benchclaw.spatial_tasks')
    spatial_tasks.generate_spatial = lambda *args, **kwargs: ()
    spatial_tasks.select_diverse = lambda pairs, target: []
    spatial_tasks.render = lambda *args, **kwargs: None
    store = types.ModuleType('benchclaw.store')

    def write_json(path, value):
        Path(path).write_text(json.dumps(value), encoding='utf-8')

    store.write_json = write_json
    sys.modules.update({
        'benchclaw': benchclaw,
        'benchclaw.spatial_tasks': spatial_tasks,
        'benchclaw.store': store,
    })
    from spatialforge import products


class ReleaseRecovery(unittest.TestCase):
    def test_interrupted_attempt_is_retained_when_retry_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            def interrupt(_directory, attempt, _split, _intent):
                (attempt/'authority_bundle.json').write_text('partial GT', encoding='utf-8')
                raise RuntimeError('injected export interruption')

            with patch.object(products, '_produce', side_effect=interrupt):
                with self.assertRaisesRegex(RuntimeError, 'injected export interruption'):
                    products.produce(directory)

            attempts = list((directory/'product_attempts').glob('export_*'))
            self.assertEqual(len(attempts), 1)
            self.assertEqual((attempts[0]/'authority_bundle.json').read_text(encoding='utf-8'), 'partial GT')
            self.assertFalse((directory/'release').exists())

            summary = {'accepted': 1, 'split': 'dev'}

            def finish(_directory, attempt, _split, _intent):
                (attempt/'authority_bundle.json').write_text('committed GT', encoding='utf-8')
                return summary

            with patch.object(products, '_produce', side_effect=finish):
                self.assertEqual(products.produce(directory), summary)

            self.assertTrue((attempts[0]/'authority_bundle.json').is_file())
            self.assertEqual((directory/'release'/'authority_bundle.json').read_text(encoding='utf-8'), 'committed GT')
            self.assertEqual(json.loads((directory/'release'/'complete.json').read_text()), summary)

    def test_completed_release_is_reused_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            summary = {'accepted': 1, 'split': 'dev'}
            calls = []

            def finish(_directory, attempt, split, _intent):
                calls.append(split)
                (attempt/'authority_bundle.json').write_text('original GT', encoding='utf-8')
                return summary

            with patch.object(products, '_produce', side_effect=finish):
                self.assertEqual(products.produce(directory, 'dev'), summary)
                self.assertEqual(products.produce(directory, 'dev'), summary)
                with self.assertRaisesRegex(ValueError, 'split is immutable'):
                    products.produce(directory, 'train')

            self.assertEqual(calls, ['dev'])
            self.assertEqual((directory/'release'/'authority_bundle.json').read_text(encoding='utf-8'), 'original GT')
            self.assertEqual(len(list((directory/'product_attempts').glob('export_*'))), 0)


if __name__ == '__main__':
    unittest.main()
