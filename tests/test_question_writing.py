import unittest
import importlib.util
from pathlib import Path
from copy import deepcopy
from benchforge_core.pipelines.question_writing import SCHEMA, public_value, question_text, validate_spec

adapter_spec=importlib.util.spec_from_file_location('question_revision',Path(__file__).resolve().parents[1]/'integrations/spatialforge/rewrite_question_set.py')
revision=importlib.util.module_from_spec(adapter_spec)
adapter_spec.loader.exec_module(revision)


class QuestionWritingTests(unittest.TestCase):
    def setUp(self):
        self.parameters = {'A': 'OBJ05', 'B': 'OBJ10', 'frame': 'image', 'threshold': 0.15}
        self.spec = {'schema': SCHEMA, 'stem': '看图1，05号物体在10号物体的哪一侧？',
                     'context': ['图中编号用于识别物体。'],
                     'conditions': ['以画面为参照，按中心标记判断方向；容差为0.15。'],
                     'options': ['左侧', '右侧'], 'response': '提交一个方向标签。',
                     'media_labels': ['图1：物体中心标记'], 'parameter_bindings': deepcopy(self.parameters)}

    def test_keeps_rules_and_choices_in_full_export_but_excludes_private_extra_fields(self):
        self.spec['answer'] = 'private must not be projected'
        result = validate_spec(self.spec, self.parameters, 1)
        self.assertNotIn('answer', result)
        self.assertNotIn('parameter_bindings', result)
        exported = question_text(result)
        self.assertTrue(exported.startswith(self.spec['stem']))
        self.assertIn('容差为0.15', exported)
        self.assertIn('左侧', exported)
        self.assertIn('作答方式', exported)

    def test_rejects_parameter_drift_missing_rules_and_unmatched_media(self):
        changed = deepcopy(self.spec)
        changed['parameter_bindings']['threshold'] = 0.2
        with self.assertRaisesRegex(ValueError, 'exact source parameters'):
            validate_spec(changed, self.parameters, 1)
        changed = deepcopy(self.spec)
        changed['conditions'] = []
        with self.assertRaisesRegex(ValueError, 'measurement rules'):
            validate_spec(changed, self.parameters, 1)
        with self.assertRaisesRegex(ValueError, 'every public media'):
            validate_spec(self.spec, self.parameters, 2)

    def test_normalizes_complete_legacy_spec_without_mutating_its_source(self):
        legacy = deepcopy(self.spec)
        legacy.pop('schema')
        self.assertEqual(validate_spec(legacy, self.parameters, 1),
                         validate_spec(self.spec, self.parameters, 1))
        self.assertNotIn('schema', legacy)
        with self.assertRaisesRegex(ValueError, 'exact source parameters'):
            validate_spec(legacy, {**self.parameters, 'threshold': 0.2}, 1)
        with self.assertRaisesRegex(ValueError, 'measurement rules'):
            validate_spec({**legacy, 'conditions': []}, self.parameters, 1)
        with self.assertRaisesRegex(ValueError, 'every public media'):
            validate_spec(legacy, self.parameters, 2)

    def test_rejects_explicit_unsupported_question_schema(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported question_spec.schema'):
            validate_spec({**self.spec, 'schema': 'unknown/v2'}, self.parameters, 1)

    def test_rejects_internal_codes_serialized_payloads_and_malformed_stems(self):
        for stem in ['根据cam_main判断方向？', '在sf_e103_study中判断方向？',
                     '根据{"A": "OBJ05"}判断方向？', '根据{unbound}判断方向？', '在哪侧？。']:
            with self.subTest(stem=stem), self.assertRaises(ValueError):
                validate_spec({**self.spec, 'stem': stem}, self.parameters, 1)
        self.assertEqual(public_value(['甲', '乙']), '甲、乙')
        self.assertEqual(public_value({'视图': '图1', '方向': '向北'}), '视图：图1；方向：向北')

    def test_visibility_writing_preserves_strict_and_inclusive_thresholds_and_sample_count(self):
        source={'private':{'oracle_trace':{'eye':[0,0,1.55],'fracs':{'E1':0.3},'n':192}}}
        common={'parameters':{'target':'OBJ02','viewpoints':'E1=(0,0)米眼高1.55米','object':'OBJ02'}}
        strict=revision.make_spec({**common,'template_id':'C63-T01'},source,[])
        inclusive=revision.make_spec({**common,'template_id':'C63-T03'},source,[])
        samples=revision.make_spec({**common,'template_id':'C28-T02'},source,[])
        self.assertIn('超过30%',question_text(strict))
        self.assertIn('达到30%',question_text(inclusive))
        self.assertIn('1.55米',question_text(strict))
        self.assertIn('6×6',question_text(strict))
        self.assertIn('192个点',question_text(samples))
        self.assertNotIn('96个点',question_text(samples))

    def test_projected_outline_keeps_rotated_extents_and_discards_interior_points(self):
        hull=revision.outline([(0,2),(2,0),(0,-2),(-2,0),(0,0),(0,2)])
        self.assertEqual(len(hull),4)
        area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(hull,hull[1:]+hull[:1])))/2
        self.assertEqual(area,8)


if __name__ == '__main__':
    unittest.main()
