"""Read session-owned BenchForgeV2 jobs; never construct Store or start work."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
import re
from pathlib import Path
import time
import urllib.request
from urllib.error import HTTPError
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, text


def load_workbench_config(path):
    """Read the service configuration and resolve values needed by read-only helpers."""
    path = Path(path).expanduser().resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    if config.get('service_config'):
        path = (path.parent / Path(os.path.expandvars(config.pop('service_config'))).expanduser()).resolve()
        config = {**json.loads(path.read_text(encoding='utf-8')), **config}
    for key in ('harness', 'artifacts'):
        if config.get(key):
            config[key] = str((path.parent / Path(os.path.expandvars(config[key])).expanduser()).resolve())
    if config.get('operator_token_env'):
        name = os.path.expandvars(config['operator_token_env'])
        config['operator_token'] = os.environ.get(name, '')
    elif not config.get('operator_token'):
        config['operator_token'] = os.environ.get('SPATIALFORGE_OPERATOR_TOKEN', '')
    if config.get('database_url_env'):
        name = os.path.expandvars(config['database_url_env'])
        database = os.environ.get(name)
        env_file = path.with_name('database.env')
        if not database and env_file.is_file():
            prefix = name + '='
            database = next((line[len(prefix):] for line in env_file.read_text(encoding='utf-8').splitlines()
                             if line.startswith(prefix)), None)
        config['database_url'] = database
    elif config.get('database_url'):
        config['database_url'] = os.path.expandvars(config['database_url'])
    return config


def workbench_database_url(config):
    database = config.get('database_url')
    if database:
        return database
    if config.get('harness'):
        deployment = Path(config['harness']) / 'deployment.local.json'
        if deployment.is_file():
            return json.loads(deployment.read_text(encoding='utf-8'))['database_url']
    raise ValueError('Configure database_url or database_url_env for the workbench service')


def session_runs(config, session, sessions=()):
    engine = create_engine(workbench_database_url(config), hide_parameters=True)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == 'postgresql':
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                connection.exec_driver_sql("SET LOCAL statement_timeout = '2000ms'")
            ids = list(dict.fromkeys([session, *sessions]))[:9]
            prefixes = {'prefix' + str(i): 'dsh:' + value + ':' for i, value in enumerate(ids)}
            conditions = ' OR '.join('substr(k.id,1,length(:'+key+'))=:'+key for key in prefixes)
            rows = connection.execute(text(
                "SELECT DISTINCT r.id,r.created_at,r.plan->>'workflow' AS workflow,CASE WHEN r.state IN ('SUCCEEDED','FAILED_FINAL','CANCELED') THEN 1 ELSE 0 END AS priority "
                'FROM spatialforge_request_keys k JOIN runs r ON r.id=k.run_id '
                'WHERE ('+conditions+') ORDER BY priority,r.created_at DESC LIMIT 12'),
                prefixes).mappings().all()
    finally:
        engine.dispose()
    return rows


def service_read(config, route, value):
    url = config.get('service_url') or f"http://{config.get('service_host', '127.0.0.1')}:{config.get('port', 3841)}"
    request = urllib.request.Request(url.rstrip('/') + route, data=json.dumps(value).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['operator_token']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        return json.load(response)


def production_observation(config, run_id):
    try:
        return service_read(config, '/observe', {'run_id':run_id})
    except HTTPError as error:
        # A running older service can retain the pre-fix Python module. Recover
        # this exact projection error from its read-only snapshot and saved files.
        try:detail=json.loads(error.read())
        except (ValueError,TypeError):raise error
        if error.code!=400 or detail.get('error')!='KeyError' or detail.get('detail')!="'report'":raise error
        snapshot=service_read(config, '/inspect', {'run_id':run_id})
        source=Path(__file__).resolve().parents[3]/'components/spatialforge/src/spatialforge/observation.py'
        spec=importlib.util.spec_from_file_location('workbench_native_observation',source)
        native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
        class SnapshotStore:
            root=Path(config['artifacts'])
            def snapshot(self,requested):return snapshot
        value=native.observe(SnapshotStore(),run_id)
        value.pop('cursor',None)
        return value


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
        from scene_library import native_identity, registration_metadata
        from benchforge_core.pipelines.plan_versions import current
        active = current(root, session)
        if not active or not active.get('plan'):
            return {}
        if active.get('pending'):
            return {'current_collection': {'status': 'pending', 'session_id': session}, 'generation': None}
        path = workspace_file(root, active['plan'])
        version = file_version(path)
        plan = bounded_json(path)
        if plan.get('schema') != 'spatialforge.pipeline/v1' or plan.get('version') != 1:
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
    try:
        rows = session_runs(config, session, sessions)
    except Exception as error:
        return {**local, 'status': 'unavailable', 'error': type(error).__name__, 'runs': []}
    registered = [row['run_id'] for row in local.get('current_collection', {}).get('rows', []) if row.get('run_id')]
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
    return {**local, 'status': 'partial' if any('error' in row for row in runs) else 'connected',
            'scope': 'session_request_keys_and_persisted_pipeline_refs', 'limit': 12, 'runs': runs}


def saved_scene_identity(config, task):
    """Group retries by the frozen scene program, without guessing from run names."""
    if not config.get('artifacts') or not re.fullmatch(r'sf_[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', task.get('id', '')):
        return {}
    revision = task.get('revision')
    if type(revision) is not int or revision < 0:
        return {}
    folder = Path(config['artifacts']) / task['id'] / ('revision_' + str(revision))
    file = folder / 'program.json'
    if not file.is_file():
        return {}
    program = json.loads(file.read_text(encoding='utf8'))
    identity = {}
    for key, source in (('scene_id', 'scene_id'), ('name', 'title')):
        value = program.get(source)
        if isinstance(value, str) and value:
            identity[key] = value
    # Files are written at admission, before execution; a reread does not turn
    # failed capture/review into success. This timestamp orders distinct retries.
    identity['created_at'] = file.stat().st_mtime
    return identity


def preview_kind(name):
    """Only produced scene imagery and operator-visible annotation summaries."""
    if name == 'preview/scene.mp4':
        return 'S2', 'video', 'video/mp4'
    if re.fullmatch(r'capture/(?:view_\d+|interaction_\d+_(?:before|after))\.png', name):
        return 'S2', 'image', 'image/png'
    if re.fullmatch(r'capture/interaction_\d+\.mp4', name):
        return 'S2', 'video', 'video/mp4'
    if re.fullmatch(r'capture/view_\d+\.json', name):
        return 'S3', 'json', 'application/json'
    if name in {'scene_review.json', 'capture/report.json', 'release/complete.json', 'release/collection_report.json'}:
        return 'S5', 'json', 'application/json'
    return None


def public_preview(name, value):
    if re.fullmatch(r'capture/view_\d+\.json', name):
        return {**{key: value[key] for key in ('frame_id', 'image_size', 'camera', 'depth_kind', 'depth_unit') if key in value},
                'visible_objects': [{key: row[key] for key in ('object_id', 'label', 'bbox_2d', 'mask') if key in row}
                                    for row in value.get('objects', [])[:200]],
                'scope': 'visible frame annotations; authority answers excluded'}
    fields = ('status', 'frames', 'renderable', 'errors', 'capture_scope', 'render_qa', 'passed',
              'issues', 'repair_suggestions', 'visual_realism', 'interaction_passed', 'interaction_requested',
              'scene_quality_passed', 'interaction_validated', 'publication_status', 'accepted',
              'target_items', 'shortfall', 'split', 'benchmark_approved', 'human_approved', 'summary')
    return {key: value[key] for key in fields if key in value}


def optional_evidence(config, arguments):
    try:
        return service_read(config, '/evidence', arguments)
    except HTTPError as error:
        if error.code != 404:
            raise
        return {}
    except FileNotFoundError:
        return {}


def stage_artifacts(config, session, scene, task_id=None, revision=None, file=None, run_ids=(), sessions=()):
    # A caller-supplied run ID never grants cross-session access to scene artifacts.
    # run_ids are extracted server-side from the resolved workspace pipeline state.
    # They are never accepted as an arbitrary browser query parameter.
    if scene not in run_ids and scene not in {row['id'] for row in session_runs(config, session, sessions)}:
        return {'error': 'Scene is not registered to this session', 'status_code': 403}
    if file:
        if not task_id or not task_id.startswith(scene + '.') or not preview_kind(file):
            return {'error': 'File is not a public stage preview', 'status_code': 403}
        if file == 'preview/scene.mp4':
            from scene_preview_video import cached_preview
            observed = service_read(config, '/inspect', {'run_id': scene})
            task = next((row for row in observed['tasks'] if row['id'] == task_id), None)
            if not task or task['unit']['revision'] != revision:
                return {'error': 'This preview is from an earlier revision; refresh the stage', 'status_code': 409}
            saved = cached_preview(task_id, revision)
            return {'source_path': saved['source_path'], 'content_type': 'video/mp4'} if saved else {
                'error': 'The scene movie has not been exported', 'status_code': 404}
        value = service_read(config, '/evidence', {'task_id': task_id, 'revision': revision, 'file': file})
        if revision != value['latest_revision']:
            return {'error': 'This preview is from an earlier revision; refresh the stage', 'status_code': 409}
        _, kind, content_type = preview_kind(file)
        result = {'source_path': value['source_path'], 'content_type': content_type}
        if kind == 'json':
            result['data'] = public_preview(file, value.get('data', {}))
        return result
    observed = service_read(config, '/inspect', {'run_id': scene})
    items = []
    tasks = observed['tasks'][:8]
    truncated = len(observed['tasks']) > len(tasks)
    briefs = [{**{key: task['unit'].get('intent', {}).get(key) for key in ('name', 'description', 'split', 'target_items')},
               'task_id': task['id'], 'workflow': task['unit'].get('workflow', 'scene')} for task in tasks]
    for task in tasks:
        if task_id and task['id'] != task_id:
            continue
        rev = task['unit']['revision']
        if revision is not None and revision != rev:
            return {'error': 'This preview is from an earlier revision; refresh the stage', 'status_code': 409}
        # Capture listing is requested on demand, never in the frequent progress poll.
        listing = optional_evidence(config, {'task_id': task['id'], 'revision': rev, 'file': 'capture'})
        names = [{**row} for row in listing.get('files', []) if preview_kind(row['file'])]
        # Only the selected revision's capture/release directories are listed;
        # do not request the evidence endpoint's all-revision historical scan.
        listing = optional_evidence(config, {'task_id': task['id'], 'revision': rev, 'file': 'release'})
        names.extend(row for row in listing.get('files', [])
                     if row['file'] in {'release/complete.json', 'release/collection_report.json'})
        if task['unit'].get('phase') in {'review', 'dataset'} or task['state'] in {'SUCCEEDED', 'FAILED_FINAL'}:
            if (task.get('result') or {}).get('scene_review') or (task.get('failure') or {}).get('scene_review'):
                review = optional_evidence(config, {'task_id': task['id'], 'revision': rev, 'file': 'scene_review.json'})
                if review:
                    names.append({'file': 'scene_review.json', 'bytes': review['bytes']})
        for row in names:
            if len(items) >= 96:
                truncated = True
                break
            stage, kind, _ = preview_kind(row['file'])
            items.append({**row, 'stage': stage, 'kind': kind, 'title': Path(row['file']).name,
                          'task_id': task['id'], 'revision': rev})
        from scene_preview_video import cached_preview
        saved = cached_preview(task['id'], rev)
        if saved:
            items.append({key: saved[key] for key in ('file', 'task_id', 'revision', 'bytes', 'frame_count', 'purpose', 'source_path', 'content_type')})
            items[-1].update(stage='S2', kind='video', title='scene.mp4', scene_name=task['unit'].get('intent', {}).get('name'))
    return {'scene': scene, 'state': observed['state'], 'items': items, 'truncated': truncated,
            'plan': {'title': '场景生产计划', 'objective': '\n'.join(row['description'] or row['name'] or '' for row in briefs),
                     'scenes': briefs, 'source': 'saved_scene_intents'},
            'config': {'scenes': [{key: row[key] for key in ('task_id', 'split', 'target_items')} for row in briefs],
                       'source': 'saved_scene_intents'},
            'scope': 'session-owned scene media and annotation summaries; authority excluded'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--sessions', default='[]', help='Additional child scopes verified by the server')
    parser.add_argument('--run-ids', default='[]')
    parser.add_argument('--workspace', help='Registered workspace for current-plan progress only')
    parser.add_argument('--action', choices=('observe', 'artifacts', 'file'), default='observe')
    parser.add_argument('--scene')
    parser.add_argument('--task')
    parser.add_argument('--revision', type=int)
    parser.add_argument('--file')
    args = parser.parse_args()
    try:
        config = load_workbench_config(args.config)
        if args.action == 'observe':
            result = observe(config, args.session, json.loads(args.run_ids), json.loads(args.sessions), args.workspace)
        else:
            result = stage_artifacts(config, args.session, args.scene, args.task, args.revision, args.file,
                                     json.loads(args.run_ids), json.loads(args.sessions))
    except Exception as error:
        # Never serialize connection strings, tokens, or exception text from database drivers.
        result = {'status': 'unavailable', 'error': type(error).__name__, 'runs': []}
    print(json.dumps(result, ensure_ascii=False))
