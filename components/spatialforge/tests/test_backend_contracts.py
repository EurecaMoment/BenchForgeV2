import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatialforge.quantity_contract import delivery_status
from spatialforge.run_context import RunContext
from spatialforge.scene_policy import policy_for, resolve_execution_mode
from spatialforge.scene_acceptance import check_request


class BackendContracts(unittest.TestCase):
    def test_quantity_contract_distinguishes_computation_from_delivery(self):
        exact_short = delivery_status(9, 10, 'exact')
        self.assertFalse(exact_short['delivery_satisfied'])
        self.assertEqual(exact_short['delivery_status'], 'partial')
        self.assertEqual(exact_short['shortfall'], 1)

        exact_extra = delivery_status(11, 10, 'exact')
        self.assertFalse(exact_extra['delivery_satisfied'])
        self.assertEqual(exact_extra['target_reached'], True)
        self.assertEqual(exact_extra['delivery_status'], 'partial')

        minimum = delivery_status(10, 10, 'minimum')
        self.assertTrue(minimum['delivery_satisfied'])
        self.assertEqual(minimum['delivery_status'], 'complete')

        partial = delivery_status(4, 10, 'best_effort')
        self.assertTrue(partial['delivery_satisfied'])
        self.assertEqual(partial['delivery_status'], 'partial')

        empty = delivery_status(0, 10, 'best_effort')
        self.assertFalse(empty['delivery_satisfied'])
        self.assertEqual(empty['delivery_status'], 'unsatisfied')

    def test_request_context_cannot_override_service_owned_ids(self):
        context = RunContext.from_request({
            'workspace_id': 'workspace-a',
            'session_id': 'session-a',
            'parent_run_id': 'sf_parent',
        })
        bound = context.for_run('sf_child').for_stage('sf_child.scene0', 'stage_attempt')
        self.assertEqual(bound.to_dict(), {
            'workspace_id': 'workspace-a',
            'session_id': 'session-a',
            'run_id': 'sf_child',
            'parent_run_id': 'sf_parent',
            'stage_id': 'sf_child.scene0',
            'attempt_id': 'stage_attempt',
        })
        with self.assertRaisesRegex(ValueError, 'service-owned'):
            RunContext.from_request({'workspace_id': 'workspace-a', 'run_id': 'caller-run'})

    def test_production_requires_enabled_policy_and_exploration_is_unassessed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'artifacts'
            root.mkdir()
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, 'requires an enabled scene policy'):
                    policy_for(root, 'production')
                self.assertEqual(policy_for(root, 'exploration'), {})

                policy = Path(temporary) / 'policy.json'
                policy.write_text('{"enabled":true,"enforce_realism":true}', encoding='utf-8')
                os.environ['SPATIALFORGE_SCENE_POLICY'] = str(policy)
                self.assertTrue(policy_for(root, 'production')['require_scene_brief'])

    def test_request_cannot_override_configured_execution_mode(self):
        with patch.dict(os.environ, {'SPATIALFORGE_EXECUTION_MODE': 'production'}, clear=True):
            self.assertEqual(resolve_execution_mode(), 'production')
            with self.assertRaisesRegex(ValueError, 'conflicts with configured mode'):
                resolve_execution_mode('exploration')
            self.assertEqual(resolve_execution_mode('production'), 'production')
            with self.assertRaisesRegex(ValueError, 'conflicts with configured mode'):
                check_request(Path.cwd(), '/dataset', {'execution_mode': 'exploration'})


if __name__ == '__main__':
    unittest.main()
