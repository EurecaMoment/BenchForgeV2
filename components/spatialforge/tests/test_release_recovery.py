"""Focused recovery checks for immutable product publication."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from spatialforge import products


class ReleaseRecovery(unittest.TestCase):
    def test_interrupted_attempt_is_retained_when_retry_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            def interrupt(_directory, attempt, _split, _intent, *, stop, context):
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

            def finish(_directory, attempt, _split, _intent, *, stop, context):
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

            def finish(_directory, attempt, split, _intent, *, stop, context):
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
