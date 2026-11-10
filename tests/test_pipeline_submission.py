"""Submission validity is checked before protocol scoring writes a result."""

from pathlib import Path
import tempfile
import unittest

from benchforge_core.artifact_io import write_jsonl
from benchforge_core.pipelines.catalog import all_templates
from benchforge_core.pipelines.evaluation import evaluate


class PipelineSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.authority = self.root / 'authority.jsonl'
        self.predictions = self.root / 'predictions.jsonl'
        self.output = self.root / 'scores'
        template = next(template for template in all_templates() if template['id'] == 'C01-T01')
        contract = {
            'protocol_id': template['protocol_id'],
            'output_kind': template['output_kind'],
            'output_schema': template['output_schema'],
            'scorer_id': 'numeric_tolerance',
        }
        write_jsonl(self.authority, [
            {'item_id': 'one', 'template_id': 'C01-T01',
             'answer': {'value': 1.0, 'unit': 'm'},
             'tolerance': {'absolute': 0.01, 'relative': 0.01}, **contract},
            {'item_id': 'two', 'template_id': 'C01-T01',
             'answer': {'value': 2.0, 'unit': 'm'},
             'tolerance': {'absolute': 0.01, 'relative': 0.01}, **contract},
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
                {'item_id': 'one', 'answer': {'value': 99, 'unit': 'm'}},
                {'item_id': 'one', 'answer': {'value': 1, 'unit': 'm'}},
            ])
        self.assertFalse(self.output.exists())

    def test_unknown_predictions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown prediction item_id'):
            self.evaluate([{'item_id': 'not-in-dataset', 'answer': {'value': 1, 'unit': 'm'}}])
        self.assertFalse(self.output.exists())

    def test_duplicate_authority_is_rejected(self):
        write_jsonl(self.authority, [
            {'item_id': 'one', 'template_id': 'C01-T01', 'answer': {'value': 1, 'unit': 'm'},
             'protocol_id': 'D89-C01-v1', 'output_kind': 'numeric',
             'output_schema': {'unit': 'declared unit', 'value': 'finite number'},
             'scorer_id': 'numeric_tolerance'},
            {'item_id': 'one', 'template_id': 'C01-T01', 'answer': {'value': 2, 'unit': 'm'},
             'protocol_id': 'D89-C01-v1', 'output_kind': 'numeric',
             'output_schema': {'unit': 'declared unit', 'value': 'finite number'},
             'scorer_id': 'numeric_tolerance'},
        ])
        with self.assertRaisesRegex(ValueError, 'Duplicate authority item_id'):
            self.evaluate([])

    def test_authority_requires_a_frozen_scoring_contract(self):
        write_jsonl(self.authority, [
            {'item_id': 'one', 'template_id': 'C01-T01',
             'answer': {'value': 1, 'unit': 'm'}},
        ])
        with self.assertRaisesRegex(ValueError, 'missing fields:'):
            self.evaluate([])
        self.assertFalse(self.output.exists())

    def test_missing_predictions_remain_in_denominator(self):
        result = self.evaluate([{'item_id': 'one', 'answer': {'value': 1, 'unit': 'm'}}])
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
