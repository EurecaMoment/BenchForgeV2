"""Check the pipeline-to-service execution contract."""

import unittest

from benchforge_core.pipelines.service_client import _bind_execution_mode


class PipelineServiceClientTests(unittest.TestCase):
    def test_start_binds_mode_to_each_scene_intent(self):
        request = {'intents': [{'name': 'scene'}, {'name': 'another'}]}
        result = _bind_execution_mode('/start', request, 'production')
        self.assertEqual(
            [intent['execution_mode'] for intent in result['intents']],
            ['production', 'production'],
        )
        self.assertEqual(request['intents'][0], {'name': 'scene'})

    def test_non_start_route_binds_top_level_and_nested_intent(self):
        result = _bind_execution_mode(
            '/dataset', {'intent': {'task': 'room'}}, 'exploration'
        )
        self.assertEqual(result['execution_mode'], 'exploration')
        self.assertEqual(result['intent']['execution_mode'], 'exploration')

    def test_request_cannot_override_configured_production_mode(self):
        with self.assertRaisesRegex(ValueError, 'conflicts with configured production'):
            _bind_execution_mode(
                '/capture', {'execution_mode': 'exploration'}, 'production'
            )


if __name__ == '__main__':
    unittest.main()
