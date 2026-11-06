"""File-based plan transport for native sessions retaining an older tool schema."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from benchforge_core.runtime import Runtime, read
from benchforge_core.pipelines.plan_input import resolve_request
from benchforge_core.pipelines.plan_versions import current
from benchforge_core.stage_review import review

def submit(workspace, session, request_path):
    if not re.fullmatch(r'[\w-]{1,160}', session):
        raise ValueError('A valid native session is required')
    source, _ = resolve_request({'request_path': request_path}, workspace)
    active = current(workspace, session)
    if source.get('applies_edit') and not active:
        raise ValueError('The edited plan does not belong to this native session')
    if active and not active['pending'] and source.get('applies_edit'):
        applied = read(active['plan'])
        if applied.get('applies_edit') == source['applies_edit']:
            fields = ('objective', 'pipeline_id', 'assessment', 'selections', 'inputs', 'steps', 'user_markdown')
            if any(source.get(key) != applied.get(key) for key in fields):
                raise ValueError('This edit has already been applied; save a new revision before changing its request')
            return {'state': 'already_applied', 'plan': active['plan'],
                    'stage_review': review(workspace, session)}
        raise ValueError('This edit is no longer the current production plan')
    runtime = Runtime(workspace)
    runtime.dsh_context = {'session_id': session, 'call_id': 'native-file-plan-request'}
    try:
        return runtime.call('pipeline_plan', {'request_path': request_path})
    finally:
        runtime.close()


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(submit(args.workspace, args.session, args.request), ensure_ascii=False))
    except (ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error), 'status_code': 400}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
