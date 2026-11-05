"""Read durable authoring inputs without making the agent retranscribe them."""
import json
from copy import deepcopy
from pathlib import Path

FIELDS = {
    'assessment', 'assessment_path', 'objective', 'pipeline_id', 'capability',
    'capabilities', 'template_ids', 'task_ids', 'target_items', 'selections',
    'steps', 'inputs', 'evidence', 'seed', 'split', 'service_config',
    'applies_edit', 'user_markdown', 'markdown_resolution',
}


def _document(source, workspace, field):
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f'{field} must name an existing JSON file')
    path = Path(source)
    if not path.is_absolute():
        path = Path(workspace) / path
    path = path.resolve()
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError(f'{field} must be an existing JSON file no larger than 2 MB: {path}')
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'{field} contains invalid JSON: {path}: {error}') from error
    if not isinstance(value, dict):
        raise ValueError(f'{field} must contain a JSON object: {path}')
    return value, str(path)


def resolve_request(args, workspace):
    """File fields never override inline fields or the host's trusted context."""
    request = deepcopy(args)
    sources = {}
    if 'request_path' in request:
        value, sources['request_path'] = _document(request.pop('request_path'), workspace, 'request_path')
        unknown = set(value) - FIELDS
        if unknown:
            raise ValueError('request_path contains unsupported fields: ' + ', '.join(sorted(unknown)))
        inline = set(request) & FIELDS
        if inline:
            raise ValueError('Use request_path or inline plan fields, not both: ' + ', '.join(sorted(inline)))
        request.update(value)
    if 'assessment_path' in request:
        if 'assessment' in request:
            raise ValueError('Use assessment_path or assessment, not both')
        request['assessment'], sources['assessment_path'] = _document(
            request.pop('assessment_path'), workspace, 'assessment_path')
    return request, sources
