import tempfile
import unittest
from pathlib import Path

from PIL import Image

from benchforge_core.artifact_io import read_jsonl, write_jsonl
from benchforge_core.pipelines.answer_contracts import (
    AnswerContractError,
    scorer_for,
    validate_answer,
)
from benchforge_core.pipelines.catalog import all_templates
from benchforge_core.pipelines.evaluation import evaluate
from benchforge_core.pipelines.production import packaged_public_media, validate_public_media


class PipelineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = {template['id']: template for template in all_templates()}

    def test_numeric_answer_contract_rejects_wrong_shape_and_non_finite_values(self):
        template = self.templates['C01-T01']
        for answer in (
            'this-is-not-a-numeric-answer',
            {'value': float('nan'), 'unit': 'm'},
            {'value': 2, 'unit': 'm', 'answer': 'extra'},
            {'value': 2},
        ):
            with self.subTest(answer=answer), self.assertRaises(AnswerContractError):
                validate_answer(template, answer)

    def test_unknown_scorer_is_not_replaced_by_exact_equality(self):
        with self.assertRaisesRegex(AnswerContractError, 'No deterministic scorer'):
            scorer_for('text')

    def test_optional_schema_suffix_describes_presence_not_the_answer_field_name(self):
        contract = {
            'output_kind': 'label_map',
            'output_schema': {
                'point_optional': '[u,v] pixels',
                'label': 'declared label',
            },
        }
        validate_answer(contract, {'point': [1.0, 2.0], 'label': 'target'})
        validate_answer(contract, {'label': 'target'})
        with self.assertRaisesRegex(AnswerContractError, 'more than once'):
            validate_answer({
                'output_kind': 'label_map',
                'output_schema': {'point': '[u,v]', 'point_optional': '[u,v]'},
            }, {'point': [1.0, 2.0]})

    def test_malformed_prediction_is_recorded_and_later_items_are_scored(self):
        numeric = self.templates['C01-T01']
        grouped = self.templates['C04-T03']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / 'dataset'
            dataset.mkdir()
            authority = [
                {
                    'item_id': 'grouped',
                    'template_id': grouped['id'],
                    'protocol_id': grouped['protocol_id'],
                    'output_kind': grouped['output_kind'],
                    'output_schema': grouped['output_schema'],
                    'scorer_id': 'ordered_groups',
                    'answer': {'groups': [['A', 'B']]},
                },
                {
                    'item_id': 'numeric',
                    'template_id': numeric['id'],
                    'protocol_id': numeric['protocol_id'],
                    'output_kind': numeric['output_kind'],
                    'output_schema': numeric['output_schema'],
                    'scorer_id': 'numeric_tolerance',
                    'answer': {'value': 2.0, 'unit': 'm'},
                    'tolerance': {'absolute': 0.01, 'relative': 0.01},
                },
            ]
            predictions = [
                {'item_id': 'grouped', 'answer': {'groups': None}},
                {'item_id': 'numeric', 'answer': {'value': 2.0, 'unit': 'm'}},
            ]
            write_jsonl(dataset / 'authority.jsonl', authority)
            write_jsonl(root / 'predictions.jsonl', predictions)

            result = evaluate({'dataset': str(dataset), 'predictions': str(root / 'predictions.jsonl')}, root / 'scores')

            scored = {row['item_id']: row for row in read_jsonl(root / 'scores' / 'scores.jsonl')}
            self.assertTrue(scored['grouped']['format_error'])
            self.assertFalse(scored['grouped']['success'])
            self.assertTrue(scored['numeric']['success'])
            self.assertEqual(result['submission']['format_errors'], 1)

    def test_media_is_decoded_whitelisted_and_rechecked_at_package_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / 'media' / 'item_1' / 'observation.png'
            media.parent.mkdir(parents=True)
            Image.new('RGB', (4, 4), (20, 40, 60)).save(media)
            self.assertEqual(validate_public_media([media]), [media.resolve()])
            with self.assertRaisesRegex(ValueError, 'supported image or video'):
                validate_public_media([media.with_suffix('.json')])

            questions = [{'media': ['media/item_1/observation.png']}]
            self.assertEqual(packaged_public_media(questions, root), [media.resolve()])
            questions[0]['media'] = ['media/../authority/source.json']
            with self.assertRaises(ValueError):
                packaged_public_media(questions, root)

    def test_unreadable_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / 'broken.png'
            image.write_bytes(b'not a png')
            with self.assertRaisesRegex(ValueError, 'cannot be decoded'):
                validate_public_media([image])


if __name__ == '__main__':
    unittest.main()
