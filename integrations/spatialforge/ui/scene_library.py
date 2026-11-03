"""Workspace scene catalog and versioned per-conversation source selections."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import time

from production_observer import service_read, stage_artifacts

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
    """One metadata query; no Store construction, historical evidence scan or image hashing."""
    from sqlalchemy import create_engine, text
    database = json.loads((Path(config['harness']) / 'deployment.local.json').read_text())['database_url']
    engine = create_engine(database, hide_parameters=True)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == 'postgresql':
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                connection.exec_driver_sql("SET LOCAL statement_timeout = '2000ms'")
            return [dict(row) for row in connection.execute(text(
                "SELECT t.id,t.run_id,t.unit,r.created_at,"
                "(SELECT k.id FROM spatialforge_request_keys k WHERE k.run_id=r.id ORDER BY k.id LIMIT 1) AS request_key "
                "FROM work_items t JOIN runs r ON r.id=t.run_id "
                "WHERE r.plan->>'schema'='spatialforge.pipeline/v1' "
                "AND COALESCE(t.unit->>'workflow','scene')='scene' AND t.state='SUCCEEDED' "
                "ORDER BY r.created_at DESC,t.id")).mappings()]
    finally:
        engine.dispose()


def sync_catalog(config, folder):
    previous = read_json(folder / 'catalog.json', {'schema': SCHEMA, 'items': []})
    if previous.get('schema') != SCHEMA:
        raise LibraryError('This scene catalog uses an unsupported format', 409)
    source_root = Path(config['artifacts']).resolve()
    items = []
    for task in completed_tasks(config):
        if not re.fullmatch(r'sf_[a-zA-Z0-9_-]+\.scene\d+', task['id']):
            continue
        unit = json.loads(task['unit']) if isinstance(task['unit'], str) else task['unit']
        revision = unit['revision']
        source = source_root / task['id'] / ('revision_' + str(revision))
        if source.is_symlink() or not source.resolve().is_relative_to(source_root):
            continue
        intent = unit.get('intent', {})
        origin = re.match(r'dsh:(session-[a-zA-Z0-9-]+):', task['request_key'] or '')
        items.append({'id': task['id'], 'task_id': task['id'], 'run_id': task['run_id'], 'revision': revision,
                      'name': intent.get('name') or task['id'], 'description': (intent.get('description') or '')[:1200],
                      'split': intent.get('split'), 'scene_family': intent.get('scene_family'),
                      'origin_session': origin.group(1) if origin else None, 'created_at': task['created_at'],
                      'source_directory': str(source), 'available': (source / 'capture').is_dir()})
    if previous.get('items') != items:
        previous = {'schema': SCHEMA, 'updated_at': time.time(), 'items': items,
                    'scope': 'shared captured scenes from this operator service; original files retained'}
        write_json(folder / 'catalog.json', previous)
    return previous


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
                    if row['origin_session'] == session and row['available']]
        saved = {'schema': SELECTION_SCHEMA, 'session_id': session, 'version': 1, 'selected': selected,
                 'allow_new_scenes': not bool(selected), 'updated_at': time.time()}
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
        result = operate(json.loads(Path(args.config).read_text()), args.workspace, args.session, args.action,
                         json.loads(args.value), max(1, args.page), max(1, min(24, args.size)), args.query,
                         args.origin, args.task, args.revision, args.file)
    except LibraryError as error:
        result = {'error': str(error), 'status_code': error.status}
    except Exception as error:
        result = {'error': 'Scene library unavailable (' + type(error).__name__ + ')', 'status_code': 503}
    print(json.dumps(result, ensure_ascii=False))
