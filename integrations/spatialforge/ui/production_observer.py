"""Read session-owned SpatialForge jobs; never construct Store or start work."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
from pathlib import Path
import urllib.request
from urllib.error import HTTPError

from sqlalchemy import create_engine, text


def session_runs(config, session):
    database = json.loads((Path(config['harness']) / 'deployment.local.json').read_text())['database_url']
    engine = create_engine(database, hide_parameters=True)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == 'postgresql':
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                connection.exec_driver_sql("SET LOCAL statement_timeout = '2000ms'")
            prefix = 'dsh:' + session + ':'
            rows = connection.execute(text(
                "SELECT DISTINCT r.id,r.created_at,r.plan->>'workflow' AS workflow,CASE WHEN r.state IN ('SUCCEEDED','FAILED_FINAL','CANCELED') THEN 1 ELSE 0 END AS priority "
                'FROM spatialforge_request_keys k JOIN runs r ON r.id=k.run_id '
                'WHERE substr(k.id,1,:length)=:prefix ORDER BY priority,r.created_at DESC LIMIT 12'),
                {'prefix': prefix, 'length': len(prefix)}).mappings().all()
    finally:
        engine.dispose()
    return rows


def service_read(config, route, value):
    url = config.get('service_url') or f"http://127.0.0.1:{config.get('port', 3841)}"
    request = urllib.request.Request(url.rstrip('/') + route, data=json.dumps(value).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['operator_token']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        return json.load(response)


def observe(config, session, run_ids):
    rows = session_runs(config, session)
    ids = list(dict.fromkeys([row['id'] for row in rows] + run_ids))[:12]
    workflows = {row['id']: row['workflow'] or 'scene' for row in rows}

    def read(run_id):
        try:
            value = service_read(config, '/observe', {'run_id': run_id})
            # Results may contain private answers. Return only lifecycle/production observations.
            fields = ('id', 'state', 'phase', 'revision', 'progress', 'failure', 'queue', 'quality', 'summary', 'workflow', 'next_action', 'evidence', 'downloads')
            return {'run_id': run_id, 'state': value['state'], 'terminal': value['terminal'],
                    'tasks': [{**{key: row[key] for key in fields if key in row},
                               'workflow': row.get('workflow', workflows.get(run_id, 'scene'))} for row in value['tasks']]}
        except Exception as error:
            return {'run_id': run_id, 'error': type(error).__name__, 'tasks': []}

    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(read, ids))
    return {'status': 'partial' if any('error' in row for row in runs) else 'connected',
            'scope': 'session_request_keys_and_persisted_pipeline_refs', 'limit': 12, 'runs': runs}


def preview_kind(name):
    """Only produced scene imagery and operator-visible annotation summaries."""
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


def stage_artifacts(config, session, scene, task_id=None, revision=None, file=None, run_ids=()):
    # A caller-supplied run ID never grants cross-session access to scene artifacts.
    # run_ids are extracted server-side from the resolved workspace pipeline state.
    # They are never accepted as an arbitrary browser query parameter.
    if scene not in run_ids and scene not in {row['id'] for row in session_runs(config, session)}:
        return {'error': 'Scene is not registered to this session', 'status_code': 403}
    if file:
        if not task_id or not task_id.startswith(scene + '.') or not preview_kind(file):
            return {'error': 'File is not a public stage preview', 'status_code': 403}
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
    parser.add_argument('--run-ids', default='[]')
    parser.add_argument('--action', choices=('observe', 'artifacts', 'file'), default='observe')
    parser.add_argument('--scene')
    parser.add_argument('--task')
    parser.add_argument('--revision', type=int)
    parser.add_argument('--file')
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text())
        if args.action == 'observe':
            result = observe(config, args.session, json.loads(args.run_ids))
        else:
            result = stage_artifacts(config, args.session, args.scene, args.task, args.revision, args.file, json.loads(args.run_ids))
    except Exception as error:
        # Never serialize connection strings, tokens, or exception text from database drivers.
        result = {'status': 'unavailable', 'error': type(error).__name__, 'runs': []}
    print(json.dumps(result, ensure_ascii=False))
