"""Read-only metadata projections for the workbench."""

from contextlib import contextmanager
import re

from sqlalchemy import text


SESSION_ID = re.compile(r'session-[A-Za-z0-9-]+')
SCENE_PAGE_SIZE = 200


@contextmanager
def read_connection(engine):
    with engine.connect() as connection:
        if engine.dialect.name == 'postgresql':
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            connection.exec_driver_sql("SET LOCAL statement_timeout = '2000ms'")
        yield connection


def recent_session_runs(connection, request):
    """Find recent runs for the supplied DSH session IDs."""
    if not isinstance(request, dict) or set(request) - {'session_id', 'related_session_ids'}:
        raise ValueError('Expected session_id and optional related_session_ids')
    related = request.get('related_session_ids', [])
    if not isinstance(related, list) or len(related) > 8:
        raise ValueError('Expected at most eight related session IDs')
    ids = [request.get('session_id'), *related]
    if any(not isinstance(value, str) or not SESSION_ID.fullmatch(value) for value in ids):
        raise ValueError('Invalid DSH session ID')
    prefixes = {f'prefix{i}': f'dsh:{value}:' for i, value in enumerate(dict.fromkeys(ids))}
    conditions = ' OR '.join(f'substr(k.id,1,length(:{key}))=:{key}' for key in prefixes)
    rows = connection.execute(text(
        "SELECT DISTINCT r.id,r.created_at,r.plan->>'workflow' AS workflow,"
        "CASE WHEN r.state IN ('SUCCEEDED','FAILED_FINAL','CANCELED') THEN 1 ELSE 0 END AS priority "
        'FROM benchforge_request_keys k JOIN runs r ON r.id=k.run_id '
        f'WHERE ({conditions}) ORDER BY priority,r.created_at DESC,r.id LIMIT 12'),
        prefixes).mappings()
    return {'runs': [dict(row) for row in rows]}


def completed_scene_page(connection, request):
    """Page through the shared scene library using stable task and time keys."""
    if not isinstance(request, dict) or set(request) - {'after'}:
        raise ValueError('Expected an optional scene page cursor')
    after = request.get('after')
    if after is None:
        after = {'created_at': '', 'task_id': ''}
    elif (not isinstance(after, dict) or set(after) != {'created_at', 'task_id'}
          or not isinstance(after['created_at'], str) or len(after['created_at']) > 64
          or not isinstance(after['task_id'], str)
          or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', after['task_id'])):
        raise ValueError('Invalid scene page cursor')
    rows = connection.execute(text(
        "SELECT t.id,t.run_id,r.created_at,t.unit->>'revision' AS revision,"
        "t.unit->'intent'->>'name' AS name,t.unit->'intent'->>'split' AS split,"
        "t.unit->'intent'->>'scene_family' AS scene_family,t.unit->'intent'->>'description' AS description,"
        "(SELECT k.id FROM benchforge_request_keys k WHERE k.run_id=r.id ORDER BY k.id LIMIT 1) AS request_key "
        "FROM work_items t JOIN runs r ON r.id=t.run_id "
        "WHERE r.plan->>'schema' IN ('benchforge.pipeline/v1','spatialforge.pipeline/v1') "
        "AND COALESCE(t.unit->>'workflow','scene')='scene' AND t.state='SUCCEEDED' "
        "AND (:task_id = '' OR COALESCE(r.created_at,'') < :created_at "
        "OR (COALESCE(r.created_at,'') = :created_at AND t.id > :task_id)) "
        "ORDER BY COALESCE(r.created_at,'') DESC,t.id LIMIT :limit"),
        {**after, 'limit': SCENE_PAGE_SIZE + 1}).mappings().all()
    records = []
    for row in rows[:SCENE_PAGE_SIZE]:
        revision = row['revision']
        if isinstance(revision, str) and revision.isascii() and revision.isdecimal() and len(revision) <= 10:
            revision = int(revision)
        if type(revision) is not int or revision < 0:
            continue
        origin = re.match(r'dsh:(session-[a-zA-Z0-9-]+):', row['request_key'] or '')
        description = row['description']
        records.append({
            'id': row['id'], 'run_id': row['run_id'], 'created_at': row['created_at'],
            'origin_session': origin.group(1) if origin else None,
            'unit': {
                'revision': revision,
                'intent': {**{key: row[key] for key in ('name', 'split', 'scene_family') if row[key] is not None},
                           'description': description[:1200] if isinstance(description, str) else ''},
            },
        })
    cursor = None
    if len(rows) > SCENE_PAGE_SIZE:
        last = rows[SCENE_PAGE_SIZE - 1]
        cursor = {'created_at': last['created_at'] or '', 'task_id': last['id']}
    return {'items': records, 'next': cursor}


WORKBENCH_QUERIES = {
    '/workbench/session-runs': recent_session_runs,
    '/workbench/scene-catalog': completed_scene_page,
}
