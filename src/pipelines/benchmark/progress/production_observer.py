"""Read session-owned BenchForge jobs; never construct Store or start work."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
from pathlib import Path
import time
from urllib.error import HTTPError
import sys


from capabilities.benchmark_design.contracts import PIPELINE_SCHEMAS
from service_access.scene_service import load_workbench_config
from service_access.scene_service import service_read
from service_access.scene_service import session_runs
from service_access.scene_service import production_observation
from capabilities.scene_library.observations import saved_scene_identity


def bounded_json(path, limit=2 * 1024 * 1024):
    with Path(path).open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Progress input is outside its bounded read limit')
    return json.loads(data)


def file_version(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def workspace_file(workspace, value):
    workspace = Path(workspace).resolve()
    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    if path.is_symlink():
        raise ValueError('Progress input cannot be a symbolic link')
    path = path.resolve()
    path.relative_to(workspace)
    return path


def process_alive(pid):
    if type(pid) is not int or pid < 1:
        return False
    if sys.platform.startswith('linux'):
        try:
            state = (Path('/proc') / str(pid) / 'stat').read_text()[:4096].rsplit(') ', 1)[1].split()[0]
            return state not in {'Z', 'X'}
        except (OSError, IndexError):
            return False
    if os.name == 'posix':
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False
    # The production host is Linux; avoid sending signals on other platforms.
    return None


def generation_progress(workspace, session, plan, reference, family=None):
    expected = plan.get('inputs', {}).get('target_items')
    if type(expected) is not int or expected < 1:
        return None
    evidence = plan.get('inputs', {}).get('evidence')
    folders = []
    if isinstance(evidence, str):
        try:
            source = workspace_file(workspace, evidence)
            if source.parent.name == 'evidence':
                folders.append(source.parent.parent / 'questions')
        except (OSError, ValueError):
            pass
    if isinstance(family, str) and re.fullmatch(r'[a-zA-Z0-9_-]+', family):
        folders.append(workspace / family / 'questions')
    count_keys = ('candidate_count', 'written_count', 'verified_count', 'published_count')
    for folder in dict.fromkeys(folders):
        try:
            path = workspace_file(workspace, folder / 'generation_progress.json')
            saved = bounded_json(path, 256 * 1024)
        except FileNotFoundError:
            saved = None
        except (OSError, ValueError, TypeError):
            continue
        if saved is not None:
            if (saved.get('schema') != 'bench-office100-generation-progress-v1' or
                    saved.get('session_id') != session or saved.get('plan_path') != reference['path'] or
                    saved.get('plan_version') != reference['file_version'] or
                    saved.get('target_items') != expected or
                    saved.get('state') not in {'running', 'complete', 'failed', 'incomplete'} or
                    any(type(saved.get(key)) is not int or saved[key] < 0 for key in count_keys) or
                    any(saved[key] > expected for key in count_keys[1:])):
                continue
            now = time.time()
            heartbeat = saved.get('heartbeat_at', saved.get('updated_at'))
            fresh = (type(heartbeat) in (int, float) and 0 <= now - heartbeat <= 30)
            alive = process_alive(saved.get('pid')) if saved['state'] == 'running' else False
            state = saved['state']
            if state == 'running' and (not fresh or alive is False):
                state = 'incomplete'
            if state == 'complete' and (saved['written_count'] != expected or saved['verified_count'] != expected):
                state = 'incomplete'
            eligible = saved.get('contract_eligible_count')
            if eligible is not None and (type(eligible) is not int or not 0 <= eligible <= saved['verified_count']):
                continue
            if state == 'complete' and eligible is not None and eligible != expected:
                state = 'incomplete'
            fields = ('schema', 'run_id', 'session_id', 'pid', 'seed', 'target_items', 'phase',
                      'started_at', 'updated_at', 'heartbeat_at', 'last_progress_at',
                      'plan_path', 'plan_version', *count_keys,
                      'surface_attempts_started', 'surface_attempts_completed', 'surface_certificates_completed')
            result = {key: saved[key] for key in fields if key in saved}
            if eligible is not None:
                result['contract_eligible_count'] = eligible
            repair_target = saved.get('repair_target_count', saved.get('repair_candidate_target'))
            if repair_target is not None and (type(repair_target) is not int or not 0 <= repair_target <= expected):
                continue
            if repair_target is not None:
                result['repair_target_count'] = repair_target
            repair_limit = repair_target if repair_target is not None else expected
            repair_count = saved.get('repair_candidate_verified_count')
            if type(repair_count) is int and 0 <= repair_count <= repair_limit:
                result['repair_candidate_verified_count'] = repair_count
            repair_written = saved.get('repair_candidate_written_count')
            if type(repair_written) is int and 0 <= repair_written <= repair_limit:
                result['repair_candidate_written_count'] = repair_written
            for key in ('by_template', 'by_scene'):
                rows = saved.get(key)
                if isinstance(rows, dict) and len(rows) <= 128:
                    result[key] = {name: {field: row[field] for field in ('target', *count_keys)
                                         if type(row.get(field)) is int and row[field] >= 0}
                                   for name, row in rows.items() if isinstance(row, dict)}
            return {**result, 'state': state, 'reported_state': saved['state'], 'fresh': fresh,
                    'process_alive': alive, 'source': 'generation_progress', 'association': 'current_applied_plan'}
        # The first real run predates heartbeats. Its final summary is evidence of
        # written/verified counts only, never evidence of a running process or S4 admission.
        try:
            path = workspace_file(workspace, folder / 'gen_summary.json')
            version = file_version(path)
            saved = bounded_json(path, 256 * 1024)
            written, verified = saved.get('total'), saved.get('public_verified_total')
            if (saved.get('plan') != reference['path'] or
                    version['mtime_ns'] < reference['file_version']['mtime_ns'] or
                    evidence and saved.get('evidence') != evidence or
                    type(written) is not int or type(verified) is not int or
                    not 0 <= verified <= written <= expected):
                continue
            return {'source': 'legacy_summary', 'association': 'current_plan_path_after_save',
                    'session_id': session, 'plan_path': reference['path'],
                    'plan_version': reference['file_version'], 'target_items': expected,
                    'candidate_count': None, 'written_count': written, 'verified_count': verified,
                    'published_count': None, 'fresh': False, 'process_alive': False,
                    'state': 'complete' if written == verified == expected and not saved.get('problems') else 'incomplete',
                    'phase': 'complete', 'updated_at': version['mtime_ns'] / 1e9}
        except (OSError, ValueError, TypeError):
            continue
    return None


def current_production_progress(config, workspace, session):
    """Read bounded current-plan registrations and counters without scanning captures."""
    if not workspace or not re.fullmatch(r'session-[a-zA-Z0-9-]+', session):
        return {}
    fallback = {'current_collection': {'status': 'unavailable', 'session_id': session}, 'generation': None}
    try:
        root = Path(workspace).resolve(strict=True)
        from capabilities.scene_library.scene_library import native_identity
        from capabilities.scene_library.scene_library import registration_metadata
        from pipelines.benchmark.design.plan_versions import current
        active = current(root, session)
        if not active or not active.get('plan'):
            return {}
        if active.get('pending'):
            return {'current_collection': {'status': 'pending', 'session_id': session}, 'generation': None}
        path = workspace_file(root, active['plan'])
        version = file_version(path)
        plan = bounded_json(path)
        if plan.get('schema') not in PIPELINE_SCHEMAS or plan.get('version') != 1:
            return fallback
        design = plan.get('assessment', {}).get('scenes', {})
        targets = design.get('designs', [])
        total = design.get('target_scene_count')
        if (type(total) is not int or total < 1 or not isinstance(targets, list) or len(targets) != total or
                any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in targets) or
                len({row['id'] for row in targets}) != total):
            return fallback
        reference = {'path': str(path), 'ledger_version': active['version'], 'pending': False,
                     'file_version': version, 'previous_plan': active.get('previous')}
        folder = root / 'scene-library'
        try:
            catalog = bounded_json(workspace_file(root, folder / 'catalog.json'))
        except FileNotFoundError:
            catalog = {'items': []}
        family = (catalog.get('production_status') or {}).get('scene_family')
        source_root = Path(config['artifacts']).resolve()
        accepted = {}
        target_ids = {row['id'] for row in targets}
        for row in catalog.get('items', []):
            if (not isinstance(row, dict) or row.get('scene_design_id') not in target_ids or
                    row.get('origin_session') != session or row.get('applied_plan') != reference or
                    row.get('source_role') != 'accepted_native_revision' or
                    family and row.get('scene_family') != family or
                    row.get('production_eligible') is not True or row.get('available') is not True):
                continue
            try:
                identity = native_identity(row, source_root)
                if not identity or row.get('run_id') != identity[0].split('.')[0] or not registration_metadata(row, row, folder, source_root):
                    continue
                receipt = bounded_json(workspace_file(root, row['native_contract_path']))
                if receipt.get('native_contract', {}).get('acceptance') != file_version(Path(identity[2]) / 'scene_acceptance.json'):
                    continue
            except (OSError, ValueError, TypeError, KeyError):
                continue
            accepted.setdefault(row['scene_design_id'], row)
        rows = []
        for target in targets:
            row = accepted.get(target['id'])
            scene_id = row.get('logical_scene_id') if row else target.get('scene_id')
            if not scene_id:
                match = re.search(r'([^/\\\s]+)\.scene_program\.json\b', str(target.get('program_path') or target.get('artifact') or ''))
                scene_id = match[1] if match else None
            name = re.sub(r'[（(]sf_[^）)]+[）)]', '', str((row or {}).get('name') or target.get('name') or '场景')).strip()
            rows.append({'design_id': target['id'], 'scene_id': scene_id, 'name': name,
                         'state': 'completed' if row else 'waiting',
                         **({'task_id': row['task_id'], 'run_id': row['run_id'], 'revision': row['revision'],
                             'captured_view_count': row.get('captured_view_count')} if row else {})})
        generation = generation_progress(root, session, plan, reference, family)
        after = current(root, session)
        if (not after or after.get('pending') or after.get('plan') != active['plan'] or
                after.get('version') != active['version'] or after.get('previous') != active.get('previous') or
                file_version(path) != version):
            return fallback
        return {'current_collection': {'status': 'current', 'session_id': session,
                    'plan_path': str(path), 'plan_version': version, 'ledger_version': active['version'],
                    'target': total, 'accepted': len(accepted), 'complete': len(accepted) == total, 'rows': rows},
                'generation': generation}
    except Exception:
        # An unverifiable registration is not a pass. Do not expose local paths or secrets in errors.
        return fallback


def observe(config, session, run_ids, sessions=(), workspace=None):
    local = current_production_progress(config, workspace, session)
    registered = [row['run_id'] for row in local.get('current_collection', {}).get('rows', []) if row.get('run_id')]
    warning = None
    try:
        rows = session_runs(config, session, sessions)
    except Exception as error:
        if not (registered or run_ids):
            return {**local, 'status': 'unavailable', 'error': type(error).__name__, 'runs': []}
        rows = []
        warning = type(error).__name__
    ids = list(dict.fromkeys(registered + [row['id'] for row in rows] + run_ids))[:12]
    workflows = {row['id']: row['workflow'] or 'scene' for row in rows}

    def read(run_id):
        try:
            value = production_observation(config, run_id)
            # Results may contain private answers. Return only lifecycle/production observations.
            fields = ('id', 'state', 'phase', 'revision', 'progress', 'failure', 'queue', 'quality', 'summary', 'workflow', 'next_action', 'evidence', 'downloads')
            return {'run_id': run_id, 'state': value['state'], 'terminal': value['terminal'],
                    'tasks': [{**{key: row[key] for key in fields if key in row},
                               **saved_scene_identity(config, row),
                               'workflow': row.get('workflow', workflows.get(run_id, 'scene'))} for row in value['tasks']]}
        except Exception as error:
            return {'run_id': run_id, 'error': type(error).__name__, 'tasks': []}

    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(read, ids))
    return {**local, **({'error': warning} if warning else {}),
            'status': 'partial' if warning or any('error' in row for row in runs) else 'connected',
            'scope': 'session_request_keys_and_persisted_pipeline_refs', 'limit': 12, 'runs': runs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--sessions', default='[]', help='Additional child scopes verified by the server')
    parser.add_argument('--run-ids', default='[]')
    parser.add_argument('--workspace', help='Registered workspace for current-plan progress only')
    args = parser.parse_args()
    try:
        config = load_workbench_config(args.config)
        result = observe(config, args.session, json.loads(args.run_ids), json.loads(args.sessions), args.workspace)
    except Exception as error:
        # Never serialize connection strings, tokens, or exception text from database drivers.
        result = {'status': 'unavailable', 'error': type(error).__name__, 'runs': []}
    print(json.dumps(result, ensure_ascii=False))
