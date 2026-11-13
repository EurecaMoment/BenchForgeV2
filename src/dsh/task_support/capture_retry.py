"""Use current canonical retry validation while an older service stays running.

This adapter shares Store's transaction and admissions; it never marks capture
or review successful and cannot alter a canceled, active or successful task.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--config',required=True)
options=parser.parse_args()
# The long-lived native service may use a PYTHONPATH that the Node Host does
# not inherit. Resolve its adjacent source without importing any DSH code.
if importlib.util.find_spec('benchforge_backend') is None:
    for source in (Path(__file__).resolve().parents[2] / 'backend', Path(options.config).resolve().parent / 'src'):
        if (source / 'benchforge_backend/storage.py').is_file():
            sys.path.insert(0, str(source))
            break
from benchforge_backend.runtime_config import load_service_config
from benchforge_backend.storage import Store
from benchforge_backend.scene_policy import check_request
configuration=load_service_config(options.config)
arguments=json.load(sys.stdin)
if set(arguments)-{'task_id','feedback','capture_mode'}:raise ValueError('Unsupported retry arguments')
store=Store(configuration['artifacts'],harness=configuration.get('harness'),
            database_url=configuration.get('database_url'))
try:
    check_request(store.root,'/retry',arguments)
    value=store.retry(arguments['task_id'],arguments.get('feedback'),arguments.get('capture_mode','auto'))
    print(json.dumps({**value,'recovery_adapter':'canonical-store-without-service-restart'}))
finally:store.repo.engine.dispose()
