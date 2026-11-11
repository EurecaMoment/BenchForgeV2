"""Resolve explicit pipeline input and prior-step references."""

class MissingBinding(ValueError):
    pass

def bind(value, environment):
    if isinstance(value, str) and value.startswith('$'):
        current = environment
        for key in value[1:].split('.'):
            if isinstance(current, list):
                current = current[int(key)]
                continue
            if key not in current:
                raise MissingBinding(value)
            current = current[key]
        return current
    if isinstance(value, list):
        return [bind(v, environment) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            try:
                result[key] = bind(child, environment)
            except MissingBinding:
                if key not in ('evidence', 'capture_options', 'preserve_source_splits'):
                    raise
        return result
    return value
