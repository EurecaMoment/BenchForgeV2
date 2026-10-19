import copy
import unittest

from spatialforge.contracts import validate_program
from test_contracts import sample


def recording_scene():
    program = sample()
    program['objects'][0].update(dynamic=True, mass_kg=0.2)
    program['cameras'][0]['id'] = 'view'
    program['interactions'] = [{
        'id': 'push',
        'action': 'apply_force',
        'object_id': 'unknown_object',
        'force_newtons': [1, 0, 0],
        'recording': {
            'every_steps': 4,
            'spatialtree': {
                'scenario_id': 'camera_motion_001',
                'split': 'train',
            },
        },
    }]
    return program


class SpatialTreeRecordingContractTests(unittest.TestCase):
    def test_valid_recording_is_accepted_without_rewriting(self):
        program = recording_scene()
        before = copy.deepcopy(program)
        self.assertEqual(validate_program(program), before)

    def test_camera_path_can_be_combined_with_an_object_interaction(self):
        program = recording_scene()
        program['interactions'][0]['recording']['camera_path'] = [
            {'step': 0, 'position': [0, -2, 1], 'target': [0, 0, 0]},
            {'step': 90, 'position': [2, 0, 1], 'target': [0, 0, 0]},
        ]
        validate_program(program)

    def test_standalone_trajectory_requires_camera_and_duration(self):
        program = recording_scene()
        program['interactions'][0] = {
            'id': 'walk_camera', 'action': 'record_trajectory', 'camera_id': 'view',
            'duration_steps': 120, 'recording': {'every_steps': 4, 'spatialtree': {}},
        }
        validate_program(program)
        for field in ('camera_id', 'duration_steps'):
            invalid = copy.deepcopy(program)
            invalid['interactions'][0].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_program(invalid)

    def test_split_camera_path_and_scenario_are_checked(self):
        for field, value in (('split', 'validation'), ('scenario_id', ''), ('camera_path', [{'step': 1, 'position': [0, 0, 1], 'target': [0, 0, 0]}])):
            invalid = recording_scene()
            if field == 'camera_path':
                invalid['interactions'][0]['recording'][field] = value
            else:
                invalid['interactions'][0]['recording']['spatialtree'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_program(invalid)


if __name__ == '__main__':
    unittest.main()
