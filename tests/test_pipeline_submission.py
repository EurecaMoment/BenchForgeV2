"""Submission validity is checked before protocol scoring writes a result."""

from pathlib import Path
import tempfile
import unittest

from benchforge_core.artifact_io import write_jsonl
from benchforge_core.pipelines.evaluation import evaluate


class PipelineSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.authority = self.root / 'authority.jsonl'
        self.predictions = self.root / 'predictions.jsonl'
        self.output = self.root / 'scores'
        write_jsonl(self.authority, [
            {'item_id': 'one', 'template_id': 'C01-T01', 'answer': 'correct'},
            {'item_id': 'two', 'template_id': 'C01-T01', 'answer': 'other'},
        ])

    def evaluate(self, predictions):
        write_jsonl(self.predictions, predictions)
        return evaluate(
            {'dataset': str(self.root), 'predictions': str(self.predictions)},
            self.output,
        )

    def test_duplicate_predictions_cannot_replace_a_wrong_answer(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate prediction item_id: one'):
            self.evaluate([
                {'item_id': 'one', 'answer': 'wrong'},
                {'item_id': 'one', 'answer': 'correct'},
            ])
        self.assertFalse(self.output.exists())

    def test_unknown_predictions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown prediction item_id'):
            self.evaluate([{'item_id': 'not-in-dataset', 'answer': 'correct'}])
        self.assertFalse(self.output.exists())

    def test_duplicate_authority_is_rejected(self):
        write_jsonl(self.authority, [
            {'item_id': 'one', 'template_id': 'C01-T01', 'answer': 'correct'},
            {'item_id': 'one', 'template_id': 'C01-T01', 'answer': 'different'},
        ])
        with self.assertRaisesRegex(ValueError, 'Duplicate authority item_id'):
            self.evaluate([])

    def test_missing_predictions_remain_in_denominator(self):
        result = self.evaluate([{'item_id': 'one', 'answer': 'correct'}])
        summary = result['per_template']['C01-T01']
        self.assertEqual(summary['count'], 2)
        self.assertEqual(summary['success_rate'], .5)
        self.assertEqual(summary['missing'], 1)
        self.assertEqual(result['submission']['missing_items'], 1)

    def test_malformed_predictions_do_not_write_scores(self):
        for prediction in ({'item_id': 'one'}, {'item_id': '', 'answer': 'x'}, []):
            with self.subTest(prediction=prediction), self.assertRaises(ValueError):
                self.evaluate([prediction])
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
