import os
import unittest
from unittest.mock import patch

from benchforge_core.annotation import annotation_environment


class AnnotationConfig(unittest.TestCase):
    def test_annotation_role_can_select_a_model_from_the_shared_registry(self):
        config = {'services': {'sam3': {'url': 'http://sam3'}, 'yoloe': {'url': 'http://yoloe'},
                               'depthanything3': {'url': 'http://depth'}},
                  'model_roles': {'annotation': 'review-vlm'},
                  'models': {'review-vlm': {'url': 'https://review/v1', 'model': 'review-model'}}}
        env = annotation_environment(config)
        self.assertEqual(env['LLM_MODEL_ID'], 'review-model')
        self.assertEqual(env['LLM_BASE_URL'], 'https://review')

    def setUp(self):
        self.services = {
            'yoloe': {'url': 'http://127.0.0.1:8766'},
            'sam3': {'url': 'http://127.0.0.1:8765'},
            'depthanything3': {'url': 'http://127.0.0.1:8008'},
        }

    def test_qwen_model_is_the_single_annotation_endpoint_and_model_source(self):
        config = {'services': self.services, 'models': {'qwen': {
            'url': 'http://127.0.0.1:9001/v1', 'model': 'fixture-model',
        }}}
        env = annotation_environment(config)
        self.assertEqual(env['LLM_BASE_URL'], 'http://127.0.0.1:9001')
        self.assertEqual(env['LLM_MODEL_ID'], 'fixture-model')

    def test_legacy_annotation_configuration_remains_supported(self):
        config = {'services': {**self.services, 'llm_local': {
            'url': 'http://127.0.0.1:9001', 'model': 'fixture-model',
        }}}
        self.assertEqual(annotation_environment(config)['LLM_MODEL_ID'], 'fixture-model')

    def test_matching_legacy_alias_is_accepted_but_endpoint_conflict_is_rejected(self):
        model = {'url': 'http://127.0.0.1:9001/v1', 'model': 'fixture-model'}
        legacy = {'url': 'http://127.0.0.1:9001', 'model': 'fixture-model'}
        config = {'services': {**self.services, 'llm_local': legacy}, 'models': {'qwen': model}}
        self.assertEqual(annotation_environment(config)['LLM_BASE_URL'], 'http://127.0.0.1:9001')
        legacy['url'] = 'http://127.0.0.1:9002'
        with self.assertRaisesRegex(ValueError, 'Conflicting annotation model endpoints'):
            annotation_environment(config)

    def test_explicit_token_environment_overrides_inline_value(self):
        config = {'services': self.services, 'models': {'qwen': {
            'url': 'http://127.0.0.1:9001/v1', 'model': 'fixture-model',
            'token': 'stale-inline', 'token_env': 'ANNOTATION_TOKEN',
        }}}
        with patch.dict(os.environ, {'ANNOTATION_TOKEN': 'environment-value'}):
            env = annotation_environment(config)
        self.assertEqual(env['BENCHFORGE_ANNOTATION_TOKEN'], 'environment-value')

    def test_ambiguous_explicit_token_environment_is_rejected(self):
        config = {'services': {**self.services, 'llm_local': {
            'url': 'http://127.0.0.1:9001', 'model': 'fixture-model', 'token_env': 'OLD_TOKEN',
        }}, 'models': {'qwen': {
            'url': 'http://127.0.0.1:9001/v1', 'model': 'fixture-model', 'token_env': 'NEW_TOKEN',
        }}}
        with self.assertRaisesRegex(ValueError, 'Conflicting annotation token_env'):
            annotation_environment(config)


if __name__ == '__main__':
    unittest.main()
