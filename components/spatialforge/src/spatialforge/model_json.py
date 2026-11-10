"""Strict JSON decoding for saved and streamed model responses."""
import json


def json_text(value):
    value = value.strip()
    if value.startswith('```'):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        value = '\n'.join(lines).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find('{')
        if start < 0:
            raise
        depth = 0
        quoted = False
        escape = False
        for index in range(start, len(value)):
            char = value[index]
            if quoted:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(value[start:index + 1])
        raise


def parse_saved(saved, path):
    try:
        return json_text(saved['content'])
    except json.JSONDecodeError as error:
        path.parent.joinpath('parse_error.json').write_text(
            json.dumps(
                {
                    'error': 'JSONDecodeError',
                    'detail': str(error),
                    'response_file': path.name,
                },
                indent=2,
            ),
            encoding='utf8',
        )
        raise
