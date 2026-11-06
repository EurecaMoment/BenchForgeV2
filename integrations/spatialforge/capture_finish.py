"""Acknowledge owned capture processes with current native validation, without a restart."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--config',required=True)
parser.add_argument('--operation',choices=('finish','context'),default='finish')
options=parser.parse_args()
source=Path(options.config).resolve().parent/'src'
if (source/'spatialforge/storage.py').is_file():sys.path.insert(0,str(source))
from spatialforge.runtime_config import load_service_config
configuration=load_service_config(options.config)
# Dispatchers use the render environment; acknowledgements need the backend runtime.
if any(importlib.util.find_spec(name) is None for name in ('sqlalchemy', 'benchclaw')):
    interpreter=Path(configuration['harness'])/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not interpreter.is_file() or interpreter.absolute()==Path(sys.executable).absolute():
        raise RuntimeError('Native capture acknowledgement requires the configured harness Python')
    os.execv(str(interpreter),[str(interpreter),'-B',str(Path(__file__).resolve()),*sys.argv[1:]])
from spatialforge.storage import Store
arguments=json.load(sys.stdin)
allowed={'job'} if options.operation=='context' else {'job','outcome','processes_stopped','error','capture_complete','capture_receipt','transport_retry'}
if set(arguments)-allowed:
    raise ValueError('Unsupported capture acknowledgement arguments')
store=Store(configuration['artifacts'],configuration['harness'],
            **({'database_url':configuration['database_url']} if configuration.get('database_url') else {}))
try:
    if options.operation=='context':
        job=arguments['job']
        value=store.worker_update(job)
        if not value.get('committed') and not value.get('finished'):
            snapshot=store.snapshot(job['task_id'].split('.')[0])
            task=next(row for row in snapshot['tasks'] if row['id']==job['task_id'])
            unit=task['unit']
            if (task['lease_owner']!=job['token'] or unit['revision']!=job['revision'] or
                    unit.get('transport_retry',0)!=job.get('transport_retry',0)):
                raise ValueError('capture recovery changed while claiming the frozen job')
            value={**value,'capture_context':{key:unit[key] for key in
                ('capture_recovery_mode','capture_resume_receipt') if key in unit}}
    else:
        value=store.worker_update(arguments['job'],outcome=arguments['outcome'],
            processes_stopped=arguments.get('processes_stopped'),error=arguments.get('error'),
            capture_complete=arguments.get('capture_complete'),capture_receipt=arguments.get('capture_receipt'))
    print(json.dumps({**value,'acknowledgement_adapter':'canonical-store-without-service-restart'}))
finally:store.repo.engine.dispose()
