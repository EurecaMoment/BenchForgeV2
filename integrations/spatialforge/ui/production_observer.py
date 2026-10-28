"""Read session-owned SpatialForge jobs; never construct Store or start work."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import urllib.request

from sqlalchemy import create_engine, text


def observe(config, session, run_ids):
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
    ids = list(dict.fromkeys([row['id'] for row in rows] + run_ids))[:12]
    workflows = {row['id']: row['workflow'] or 'scene' for row in rows}

    def read(run_id):
        url = config.get('service_url') or f"http://127.0.0.1:{config.get('port', 3841)}"
        request = urllib.request.Request(url.rstrip('/') + '/observe',
            data=json.dumps({'run_id': run_id}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['operator_token']})
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=3) as response:
                value = json.load(response)
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--run-ids', default='[]')
    args = parser.parse_args()
    try:
        result = observe(json.loads(Path(args.config).read_text()), args.session, json.loads(args.run_ids))
    except Exception as error:
        # Never serialize connection strings, tokens, or exception text from database drivers.
        result = {'status': 'unavailable', 'error': type(error).__name__, 'runs': []}
    print(json.dumps(result, ensure_ascii=False))
