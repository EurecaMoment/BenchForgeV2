"""Acknowledge owned capture processes through the backend Store."""
import argparse
import importlib.util
import json
import os
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
    source = Path(options.config).resolve().parent / 'src'
    if not (source / 'benchforge_backend/storage.py').is_file():
        source = Path(__file__).resolve().parent.parent
    if (source / 'benchforge_backend/storage.py').is_file():
        sys.path.insert(0, str(source))
    from benchforge_backend.runtime_config import load_service_config

    configuration = load_service_config(options.config)
    # Older dispatchers may specify a historical backend virtual environment.
    harness = configuration.get('harness')
    if importlib.util.find_spec('sqlalchemy') is None:
        executable = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
        interpreter = Path(harness) / '.venv' / executable if harness else None
        if interpreter is None or not interpreter.is_file() or interpreter.absolute() == Path(sys.executable).absolute():
            raise RuntimeError('Run capture acknowledgement with the configured BenchForge backend Python')
        os.execv(str(interpreter), [str(interpreter), '-B', str(Path(__file__).resolve()), *sys.argv[1:]])
    from benchforge_backend.storage import Store

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
