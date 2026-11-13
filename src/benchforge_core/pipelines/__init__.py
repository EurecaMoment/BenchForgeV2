"""Discoverable, composable production recipes and protocol-bound task templates."""


def canonical_identifier(value):
    if isinstance(value, str) and value.startswith('spatialforge.'):
        return 'benchforge.' + value.removeprefix('spatialforge.')
    return value


def canonical_steps(steps):
    if not isinstance(steps, list):
        return steps
    return [
        {**step, 'uses': canonical_identifier(step['uses'])}
        if isinstance(step, dict) and 'uses' in step else step
        for step in steps
    ]
