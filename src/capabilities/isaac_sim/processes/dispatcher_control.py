"""Acknowledge owned capture processes through the scene production Store."""
import argparse
import json
from pathlib import Path
import sys


def capture_context(store, job):
    value = store.worker_update(job)
    if value.get('committed') or value.get('finished'):
        return value
    snapshot = store.snapshot(job['task_id'].split('.')[0])
    task = next(row for row in snapshot['tasks'] if row['id'] == job['task_id'])
    unit = task['unit']
    if (task['lease_owner'] != job['token'] or unit['revision'] != job['revision'] or
            unit.get('transport_retry', 0) != job.get('transport_retry', 0)):
        raise ValueError('capture recovery changed while claiming the frozen job')
    return {**value, 'capture_context': {key: unit[key] for key in (
        'capture_recovery_mode', 'capture_resume_receipt'
    ) if key in unit}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--operation', choices=('finish', 'context'), default='finish')
    options = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from service_access.runtime_config import load_service_config

    configuration = load_service_config(options.config)
    harness = configuration.get('harness')
    from storage.scene_jobs.store import Store

    arguments = json.load(sys.stdin)
    allowed = {'job'}
    if options.operation == 'finish':
        allowed.update(('outcome', 'processes_stopped', 'error', 'capture_complete', 'capture_receipt', 'transport_retry'))
    if set(arguments) - allowed:
        raise ValueError('Unsupported capture acknowledgement arguments')
    store = Store(configuration['artifacts'], harness=harness, database_url=configuration.get('database_url'))
    try:
        job = arguments['job']
        if options.operation == 'context':
            value = capture_context(store, job)
        else:
            value = store.worker_update(
                job, outcome=arguments['outcome'], processes_stopped=arguments.get('processes_stopped'),
                error=arguments.get('error'), capture_complete=arguments.get('capture_complete'),
                capture_receipt=arguments.get('capture_receipt'),
            )
        print(json.dumps({**value, 'acknowledgement_adapter': 'canonical-store-without-service-restart'}))
    finally:
        store.repo.engine.dispose()


if __name__ == '__main__':
    main()
