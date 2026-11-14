"""Workspace scene catalog and versioned per-conversation source selections."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time

from production_observer import (
    PIPELINE_SCHEMAS, load_workbench_config, service_read, stage_artifacts,
)
from benchforge_core.pipelines.scene_policy import load_policy, check_source, classify_planned, CLASSIFIER_VERSION, scene_design_parser

SCHEMA = 'benchforge.scene-library/v1'
SELECTION_SCHEMA = 'benchforge.scene-selection/v1'


class LibraryError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def library_folder(workspace):
    workspace = Path(workspace)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise LibraryError('A registered workspace is required', 403)
    folder = workspace / 'scene-library'
    if folder.is_symlink():
        raise LibraryError('The scene library must stay inside the workspace', 403)
    folder.mkdir(exist_ok=True)
    return folder


def selection_file(folder, session):
    if not re.fullmatch(r'session-[a-zA-Z0-9-]+', session):
        raise LibraryError('A conversation is required', 403)
    directory = folder / 'selections'
    if directory.is_symlink():
        raise LibraryError('Invalid selection directory', 403)
    directory.mkdir(exist_ok=True)
    return directory / (session + '.json')


def read_json(path, fallback):
    if path.is_symlink():
        raise LibraryError('Invalid library file', 403)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else fallback


def write_json(path, value):
    pending = path.with_suffix('.pending.json')
    if pending.is_symlink() or path.is_symlink():
        raise LibraryError('Invalid library file', 403)
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(path)


@contextmanager
def locked(folder):
    path = folder / '.write.lock'
    deadline = time.monotonic() + 5
    while True:
        try:
            with path.open('x') as handle:
                handle.write(str(time.time()))
            break
        except FileExistsError:
            try:
                if path.is_file() and not path.is_symlink() and time.time() - path.stat().st_mtime > 60:
                    path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise LibraryError('Scene library is busy; retry the change', 409)
            time.sleep(0.025)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def completed_tasks(config):
    """Read shared scene metadata in pages before checking the saved evidence."""
    rows = []
    value = {}
    while True:
        page = service_read(config, '/workbench/scene-catalog', value)
        if page is None:
            raise ValueError('The service does not provide the shared scene catalog')
        rows.extend(page['items'])
        cursor = page['next']
        if cursor is None:
            return rows
        if cursor == value.get('after'):
            raise ValueError('The scene catalog cursor did not advance')
        value = {'after': cursor}


@contextmanager
def catalog_locked(folder):
    """Share the finalizer's OS lock; .write.lock only protects UI selections."""
    path = folder / 'catalog.json.lock'
    if path.is_symlink():
        raise LibraryError('Invalid library lock', 403)
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def native_identity(row, source_root):
    task = row.get('task_id')
    revision = row.get('revision')
    if not isinstance(task, str) or not re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.scene\d+', task):
        return None
    if type(revision) is not int or revision < 0 or row.get('id') != task:
        return None
    try:
        source = Path(row['source_directory'])
        if not source.is_absolute() or source.is_symlink():
            return None
        canonical = source.resolve()
        canonical.relative_to(source_root)
        if canonical != (source_root / task / ('revision_' + str(revision))).resolve():
            return None
        return task, revision, str(canonical)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def registration_metadata(previous, fresh, folder, source_root):
    """Retain finalizer metadata, never its cached eligibility or admission."""
    identity = native_identity(fresh, source_root)
    if not identity or native_identity(previous, source_root) != identity:
        return {}
    if previous.get('source_role') != 'accepted_native_revision':
        return {}
    try:
        path = Path(previous['native_contract_path'])
        if not path.is_absolute() or path.is_symlink():
            return {}
        path.resolve().relative_to(folder.parent.resolve())
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            return {}
        receipt = read_json(path, {})
        contract = receipt.get('native_contract', {})
        if (receipt.get('source_task_id') != identity[0] or receipt.get('revision') != identity[1] or
            str(Path(receipt['runtime_revision']).resolve()) != identity[2] or
            str(Path(contract['source_directory']).resolve()) != identity[2] or
            receipt.get('capture_origin') != 'isaac_native' or
            receipt.get('acceptance_passed') is not True or receipt.get('acceptance_enforced') is not True or
            receipt.get('scene_design_id') != previous.get('scene_design_id') or
            receipt.get('scene_id') != previous.get('logical_scene_id') or
            not isinstance(previous.get('applied_plan'), dict) or
            receipt.get('applied_plan') != previous['applied_plan']):
            return {}
        fields = ('origin_session', 'scene_family', 'logical_scene_id', 'scene_design_id', 'split',
                  'applied_plan', 'source_role', 'native_contract_path', 'captured_view_count',
                  'program_path', 'scene_brief_provenance', 'source_history')
        saved = {key: previous[key] for key in fields if key in previous}
        acceptance = Path(identity[2]) / 'scene_acceptance.json'
        stat = acceptance.stat()
        version = {'path': str(acceptance.resolve()), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        if fresh.get('production_eligible') is True and contract.get('acceptance') == version:
            if isinstance(receipt.get('name'), str):
                saved['name'] = receipt['name']
            if isinstance(receipt.get('summary'), str):
                saved['description'] = receipt['summary']
        return saved
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def current_production_status(previous, items, folder):
    """Recompute optional progress from the live applied ledger, not old 3/3."""
    status = previous.get('production_status')
    if not isinstance(status, dict) or not isinstance(status.get('session'), str):
        return None
    try:
        from benchforge_core.pipelines.plan_versions import current
        active = current(folder.parent, status['session'])
        if not active or active.get('pending') or not active.get('plan'):
            return None
        path = Path(active['plan']).resolve()
        stat = path.stat()
        if not path.is_file() or stat.st_size > 2 * 1024 * 1024:
            return None
        version = {'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        plan = read_json(path, {})
        if plan.get('schema') not in PIPELINE_SCHEMAS or plan.get('version') != 1:
            return None
        scenes = plan['assessment']['scenes']
        target = scenes['target_scene_count']
        selected = {row['id'] for row in scenes['designs']}
        if type(target) is not int or target < 1 or len(selected) < target:
            return None
        reference = {'path': str(path), 'ledger_version': active['version'], 'pending': False,
                     'file_version': version, 'previous_plan': active.get('previous')}
        after = current(folder.parent, status['session'])
        stat = path.stat()
        if (not after or after.get('pending') or after.get('plan') != active['plan'] or
            after.get('version') != active['version'] or after.get('previous') != active.get('previous') or
            [stat.st_size, stat.st_mtime_ns] != [version['bytes'], version['mtime_ns']]):
            return None
        completed = {row.get('scene_design_id') for row in items
                     if row.get('origin_session') == status['session'] and
                     row.get('scene_family') == status.get('scene_family') and
                     row.get('production_eligible') is True and row.get('available') is True and
                     row.get('source_role') == 'accepted_native_revision' and row.get('applied_plan') == reference} & selected
        return {'scene_family': status.get('scene_family'), 'session': status['session'], 'plan': str(path),
                'accepted': len(completed), 'target': target, 'complete': len(completed) >= target,
                'remaining_design_ids': sorted(selected - completed)}
    except Exception:
        # Progress is optional; an unverifiable ledger must not leave a stale pass.
        return None


def scanned_items(config, folder, previous, tasks=None):
    source_root = Path(config['artifacts']).resolve()
    policy = load_policy(folder.parent)
    prior = {row['id']: row for row in previous['items']}
    repaired = read_json(folder / 'repairs.json', {})
    repaired_from = {value['task_id']: key for key, value in repaired.items()}
    items = []
    for task in completed_tasks(config) if tasks is None else tasks:
        if task['id'] in repaired:continue
        if not re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.scene\d+', task['id']):
            continue
        unit = json.loads(task['unit']) if isinstance(task['unit'], str) else task['unit']
        try:
            check_source(policy, task_id=task['id'], run_id=task['run_id'])
        except ValueError:
            continue
        revision = unit['revision']
        source = source_root / task['id'] / ('revision_' + str(revision))
        if source.is_symlink() or not source.resolve().is_relative_to(source_root):
            continue
        intent = unit.get('intent', {})
        admission = None
        if policy.get('enabled'):
            program = source / 'program.json'
            if not program.is_file():
                program = source / 'capture/program.json'
            if not program.is_file():
                continue
            stat = program.stat()
            version = [stat.st_size, stat.st_mtime_ns]
            prior_item = prior.get(task['id'], {})
            identity = {'id': task['id'], 'task_id': task['id'], 'revision': revision,
                        'source_directory': str(source)}
            current_identity = native_identity(identity, source_root)
            cached = (prior_item.get('scene_admission', {})
                      if current_identity and native_identity(prior_item, source_root) == current_identity else {})
            declaration = cached.get('geometry_exception')
            plan_current = not declaration or scene_design_parser().plan_declaration_current(declaration)
            try:
                admission = cached if cached.get('program_version') == version and cached.get('classifier_version') == CLASSIFIER_VERSION and plan_current else {**classify_planned(read_json(program, {}), policy), 'program_version': version}
            except (ValueError, OSError, KeyError, TypeError):
                continue
            if not admission['allowed']:
                continue
        receipt=read_json(source/'scene_acceptance.json',{})
        accepted=receipt.get('passed') is True and receipt.get('enforced') is True
        if accepted:
            accepted=all((source/relative).is_file() and receipt.get('evidence_versions',{}).get(relative)==[(source/relative).stat().st_size,(source/relative).stat().st_mtime_ns]
                for relative in ('program.json','capture/report.json','capture/evidence.json'))
        if (policy.get('require_scene_brief') or policy.get('enforce_realism')) and not receipt.get('scene_brief'):accepted=False
        for declaration in (receipt.get('geometry_exception'), receipt.get('scene_brief')):
            if not accepted or not declaration:continue
            accepted = scene_design_parser().plan_declaration_current(declaration)
        for name,version in receipt.get('mesh_versions',{}).items():
            mesh=Path(name)
            if not mesh.is_file() or [mesh.stat().st_size,mesh.stat().st_mtime_ns]!=version:accepted=False
        brief = receipt.get('scene_brief') or {}
        items.append({'id': task['id'], 'task_id': task['id'], 'run_id': task['run_id'], 'revision': revision,
                      'name': brief.get('name') or intent.get('name') or task['id'],
                      'description': (brief.get('summary') or intent.get('description') or '')[:1200],
                      'split': intent.get('split'), 'scene_family': intent.get('scene_family'),
                      'origin_session': task.get('origin_session'), 'created_at': task['created_at'],
                      'source_directory': str(source), 'available': (source / 'capture').is_dir(),
                      'scene_style': (admission or {}).get('scene_style', 'realistic_assets'),
                      'geometry_purpose': ((admission or {}).get('geometry_exception') or {}).get('purpose'),
                      'production_eligible':accepted if policy.get('enforce_realism') else True})
        if task['id'] in repaired_from:
            items[-1]['repaired_from'] = repaired_from[task['id']]
        if admission is not None:
            items[-1]['scene_admission'] = admission
    return items


def sync_catalog(config, folder):
    path = folder / 'catalog.json'
    previous = read_json(path, {'schema': SCHEMA, 'items': []})
    if previous.get('schema') != SCHEMA:
        raise LibraryError('This scene catalog uses an unsupported format', 409)
    items = scanned_items(config, folder, previous)
    source_root = Path(config['artifacts']).resolve()
    before = {row['id']: row for row in previous['items']}
    with catalog_locked(folder):
        # A finalizer can commit while the metadata query/native scan is running.
        latest = read_json(path, {'schema': SCHEMA, 'items': []})
        if latest.get('schema') != SCHEMA:
            raise LibraryError('This scene catalog uses an unsupported format', 409)
        registered = {row['id']: row for row in latest['items']}
        fresh = {row['id']: row for row in items}
        for task_id, row in registered.items():
            if (task_id in fresh and native_identity(row, source_root) == native_identity(fresh[task_id], source_root)):
                continue
            earlier = before.get(task_id, {})
            changed = (native_identity(row, source_root) != native_identity(earlier, source_root) or
                       row.get('native_contract_path') != earlier.get('native_contract_path') or
                       row.get('applied_plan') != earlier.get('applied_plan'))
            if not changed or not registration_metadata(row, row, folder, source_root):
                continue
            # Recheck only a newly committed native source missed by the query.
            # Ownership comes from its verified registration, never program provenance.
            task = {'id': row['task_id'], 'run_id': row['run_id'], 'unit': {'revision': row['revision']},
                    'created_at': row.get('created_at')}
            current = scanned_items(config, folder, latest, tasks=[task])
            if current:
                fresh[task_id] = current[0]
            else:
                fresh.pop(task_id, None)
        policy = load_policy(folder.parent)
        items = []
        for row in fresh.values():
            try:
                check_source(policy, task_id=row['task_id'], run_id=row['run_id'])
            except ValueError:
                continue
            row.update(registration_metadata(registered.get(row['id'], {}), row, folder, source_root))
            items.append(row)
        catalog = {**latest, 'schema': SCHEMA, 'items': items,
                   'scope': 'shared captured scenes from this operator service; original files retained'}
        status = current_production_status(latest, items, folder)
        if status is None:
            catalog.pop('production_status', None)
        else:
            catalog['production_status'] = status
        if catalog != latest:
            catalog['updated_at'] = time.time()
            write_json(path, catalog)
        return catalog


def public_media(row):
    source = Path(row['source_directory'])
    capture = source / 'capture'
    frames = []
    if capture.is_dir() and not capture.is_symlink():
        for frame in sorted(capture.glob('view_*.png'), key=lambda path: path.name):
            if len(frames) >= 40:
                break
            if re.fullmatch(r'view_\d+\.png', frame.name) and frame.is_file() and not frame.is_symlink():
                frames.append({'file': 'capture/' + frame.name, 'bytes': frame.stat().st_size,
                               'kind': 'image', 'task_id': row['task_id'], 'revision': row['revision'], 'scene_name': row['name']})
    from scene_preview_video import cached_preview
    saved = cached_preview(row['task_id'], row['revision'])
    video = {key: saved[key] for key in ('file', 'bytes', 'purpose', 'frame_count', 'source_path')} if saved else None
    if video:
        video.update(kind='video', task_id=row['task_id'], revision=row['revision'], scene_name=row['name'])
    programs = [source / 'program.json', source / 'capture/program.json']
    program = next((str(path) for path in programs if path.is_file() and not path.is_symlink()), None)
    return {**row, 'available': bool(frames or video), 'frames': frames, 'video': video,
            'frame_count': len(frames), 'program_path': program}


def selected_sources(catalog, selected):
    by_id = {row['id']: row for row in catalog['items']}
    result = []
    for reference in selected:
        row = by_id.get(reference['id'])
        if not row or row['revision'] != reference['revision']:
            raise LibraryError('A selected scene changed or is unavailable; select its current version again', 409)
        if row.get('production_eligible') is False:
            raise LibraryError('场景尚未通过物理与生活合理性验收，请重新采集验收后使用。',409)
        media = public_media(row)
        if not media['available']:
            raise LibraryError('A selected scene has no available captured media', 409)
        result.append({key: media[key] for key in ('id', 'run_id', 'task_id', 'revision', 'name', 'split',
                                                  'source_directory', 'program_path')})
    return result


def load_selection(folder, session, catalog):
    path = selection_file(folder, session)
    saved = read_json(path, None)
    if saved is not None and (saved.get('schema') != SELECTION_SCHEMA or saved.get('session_id') != session):
        raise LibraryError('Invalid saved scene selection', 409)
    if saved is None:
        selected = [{'id': row['id'], 'revision': row['revision']} for row in catalog['items']
                    if row['origin_session'] == session and row['available'] and row.get('production_eligible') is not False]
        saved = {'schema': SELECTION_SCHEMA, 'session_id': session, 'version': 1, 'selected': selected,
                 'allow_new_scenes': not bool(selected), 'updated_at': time.time()}
        write_json(path, saved)
    else:
        removed = set(load_policy(folder.parent).get('excluded_tasks', []))
        eligible={row['id'] for row in catalog['items'] if row.get('production_eligible') is not False}
        selected = [row for row in saved['selected'] if row['id'] not in removed and row['id'] in eligible]
        if selected != saved['selected']:
            saved = {**saved, 'selected': selected, 'version': saved['version'] + 1, 'updated_at': time.time(),
                     'notice': '已移除不符合场景要求的历史选择，请重新选择。'}
            write_json(path, saved)
    return {**saved, 'selection_path': str(path), 'catalog_path': str(folder / 'catalog.json')}


def save_selection(folder, session, catalog, value):
    current = load_selection(folder, session, catalog)
    if type(value.get('version')) is not int or value['version'] != current['version']:
        raise LibraryError('Scene selection changed in another window; refresh and retry', 409)
    selected = value.get('selected')
    if not isinstance(selected, list) or len(selected) > 1000 or type(value.get('allow_new_scenes')) is not bool:
        raise LibraryError('Invalid scene selection')
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or type(row.get('revision')) is not int
           for row in selected) or len({row['id'] for row in selected}) != len(selected):
        raise LibraryError('Invalid scene references')
    selected_sources(catalog, selected)
    saved = {'schema': SELECTION_SCHEMA, 'session_id': session, 'version': current['version'] + 1,
             'selected': [{key: row[key] for key in ('id', 'revision')} for row in selected],
             'allow_new_scenes': value['allow_new_scenes'], 'updated_at': time.time()}
    write_json(selection_file(folder, session), saved)
    return load_selection(folder, session, catalog)


def operate(config, workspace, session, action='list', value=None, page=1, size=12, query='', origin='all',
            task_id=None, revision=None, file=None):
    folder = library_folder(workspace)
    if action in {'file', 'artifacts'}:
        catalog = read_json(folder / 'catalog.json', {'items': []})
        row = next((row for row in catalog['items'] if row['id'] == task_id), None)
        try:
            check_source(load_policy(workspace), task_id=task_id)
        except ValueError as error:
            raise LibraryError(str(error), 410) from error
        if not row or not row['available']:
            raise LibraryError('The scene is not in this workspace library', 403)
        if revision is not None and row['revision'] != revision:
            raise LibraryError('This scene version changed; refresh the library', 409)
        return stage_artifacts(config, session, row['run_id'], row['task_id'], row['revision'], file,
                               run_ids=[row['run_id']])
    with locked(folder):
        catalog = sync_catalog(config, folder)
        selection = load_selection(folder, session, catalog)
        if action == 'save':
            return save_selection(folder, session, catalog, value)
        if action == 'selection':
            return {**selection, 'sources': selected_sources(catalog, selection['selected'])}
        selected_ids={(row['id'],row['revision']) for row in selection['selected']}
        rows = [row for row in catalog['items'] if
                (origin == 'all' or origin=='selected' and (row['id'],row['revision']) in selected_ids or
                 origin in ('current','history') and (row['origin_session'] == session) == (origin == 'current')) and
                (not query or query.casefold() in (row['name'] + ' ' + row['id'] + ' ' + row['description']).casefold())]
        pages = max(1, (len(rows) + size - 1) // size)
        page = max(1, min(page, pages))
        return {'schema': SCHEMA, 'items': [public_media(row) for row in rows[(page - 1) * size:page * size]],
                'total': len(rows), 'all': len(catalog['items']), 'page': page, 'pages': pages,
                'selection': selection, 'catalog_path': str(folder / 'catalog.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--action', choices=('list', 'save', 'selection', 'file', 'artifacts'), default='list')
    parser.add_argument('--value', default='{}')
    parser.add_argument('--page', type=int, default=1)
    parser.add_argument('--size', type=int, default=12)
    parser.add_argument('--query', default='')
    parser.add_argument('--origin', choices=('all', 'current', 'history', 'selected'), default='all')
    parser.add_argument('--task')
    parser.add_argument('--revision', type=int)
    parser.add_argument('--file')
    args = parser.parse_args()
    try:
        result = operate(load_workbench_config(args.config), args.workspace, args.session, args.action,
                         json.loads(args.value), max(1, args.page), max(1, min(24, args.size)), args.query,
                         args.origin, args.task, args.revision, args.file)
    except LibraryError as error:
        result = {'error': str(error), 'status_code': error.status}
    except Exception as error:
        result = {'error': 'Scene library unavailable (' + type(error).__name__ + ')', 'status_code': 503}
    print(json.dumps(result, ensure_ascii=False))
