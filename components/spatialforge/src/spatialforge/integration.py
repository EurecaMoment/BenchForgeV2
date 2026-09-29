"""Reuse BenchClaw's data engine; SpatialForge owns the production request.

The linked run shares PostgreSQL with SpatialForge and keeps the original
plugin receipts. This adapter never imports or invokes target-model evaluation.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import threading
import time


DEFAULT_HARNESS = Path(__file__).resolve().parents[3] / 'benchclaw'
DEFAULT_BENCHCLAW = DEFAULT_HARNESS / 'BenchClaw'
DEFAULT_BENCHFORGE = Path(__file__).resolve().parents[2]
EXCLUDED_SOURCES = {'source.libero_hdf5'}
SECRET_FIELDS = {'api_key', 'password', 'access_token', 'authorization', 'bearer_token'}


def _harness(root=None):
    if root is not None:
        return Path(root).resolve()
    configured = os.environ.get('SPATIALFORGE_LEGACY_HARNESS')
    if configured:
        return Path(configured).resolve()
    try:
        import benchclaw
        return Path(benchclaw.__file__).resolve().parents[2]
    except ImportError:
        return DEFAULT_HARNESS


def _excluded(plugin):
    return plugin.startswith('simulator.') or plugin in EXCLUDED_SOURCES


def _check_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in SECRET_FIELDS and child:
                raise ValueError('Use an environment variable for credentials; dataset intents are recorded')
            _check_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _check_secrets(child)


def _recipe_files(root):
    # Only the explicit examples tree, never a recursive scan of runtime data.
    folder = root / 'examples'
    return sorted(folder.glob('*/*.json')) if folder.is_dir() else []


def _knowledge(root):
    entries = []
    for category in ('skills', 'realDataCards', 'benchmarkDatasetCards', 'simulatorCards', 'annotation-tool'):
        for path in sorted((root / category).glob('*/SKILL.md')):
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()[:40]
            title = next((line.lstrip('# ').strip() for line in lines if line.startswith('# ')), path.parent.name)
            description = next((line.split(':', 1)[1].strip() for line in lines if line.startswith('description:')), '')
            entries.append({'id':path.parent.name, 'category':category, 'title':title,
                            'description':description, 'path':str(path), 'role':'reference_knowledge'})
    for name in ('templates', 'data-juicer_card', 'modelNeedMeasured'):
        path = root / name / 'SKILL.md'
        if path.is_file():
            entries.append({'id':name, 'category':'capability', 'path':str(path), 'role':'reference_knowledge'})
    return entries


def catalog(harness=None):
    """Report real registered capabilities, separately from deployment readiness."""
    root = _harness(harness)
    from benchclaw.plugins import Registry
    from benchclaw.template_engine import catalogue
    registry = Registry()
    descriptors = [p.describe().model_dump(mode='json') for p in registry.plugins.values()]
    sources = []
    for desc in descriptors:
        if desc['kind'] != 'source':
            continue
        excluded = _excluded(desc['plugin_id'])
        sources.append({**desc, 'enabled_in_spatialforge':not excluded,
                        'readiness':'checked_per_request',
                        **({'reason':'New simulation runs use desktop Isaac only; legacy capture workers are not launched'} if excluded else {})})
    recipes = []
    for path in _recipe_files(root):
        try:
            spec = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if spec.get('contract_version') != 'benchclaw.dataset-spec/v1':
            continue
        inputs = spec.get('sources', [])
        enabled = not any(_excluded(source.get('plugin', '')) for source in inputs)
        recipes.append({'id':path.relative_to(root).as_posix(), 'name':spec['name'],
                        'objective':spec['objective'], 'purpose':spec.get('purpose', 'evaluation'),
                        'target_items':spec['target_items'], 'enabled':enabled,
                        'sources':[{'plugin':s['plugin'], 'path':s['parameters'].get('path'),
                                    'local_path_exists':Path(s['parameters']['path']).exists() if s['parameters'].get('path') else None}
                                   for s in inputs]})
    return {'schema':'spatialforge.legacy-catalog/v1', 'harness':str(root),
            'sources':sources, 'templates':catalogue(), 'recipes':recipes,
            'processing_plugins':[d for d in descriptors if d['kind'] != 'source' and d['kind'] != 'evaluator'],
            'legacy_knowledge':_knowledge(DEFAULT_BENCHCLAW),
            'benchforge':{'path':str(DEFAULT_BENCHFORGE), 'integration':'generation_tools_and_scene_asset_bridge',
                         'scope':'diffusion, segmentation, SAM3D assets; full source-reconstruction acceptance remains separate',
                         'end_to_end_validation':'see task receipts; registration is not execution evidence'},
            'dataset_intent':{'recipe':'relative examples path OR provide spec',
                              'spec':'complete benchclaw.dataset-spec/v1 object OR provide recipe',
                              'overrides':'DatasetSpec fields, applied before validation',
                              'review':'true by default; false exports an explicitly unreviewed benchmark candidate',
                              'split':'dev or train; never reassign existing source scenes'},
            'operating_limits':{'reviewed_candidates_per_dataset_task':100,
                                'scale':'submit independent source-disjoint dataset intents in a batch',
                                'target_model_api_evaluation':False,
                                'gt_authority':'source labels, annotations or simulator state; never reviewer answers'}}


def _model_settings():
    base = os.environ.get('SPATIALFORGE_MODEL_URL', 'http://127.0.0.1:29002/v1').rstrip('/')
    endpoint = base if base.endswith('/chat/completions') else base + '/chat/completions'
    return {'model_id':os.environ['SPATIALFORGE_MODEL_ID'], 'endpoint':endpoint,
            'api_key_env':os.environ.get('SPATIALFORGE_MODEL_API_KEY_ENV','QWEN_RELAY_API_KEY'),
            'timeout_seconds':600, 'max_tokens':12288, 'enable_thinking':True,
            'preserve_thinking':True, 'reasoning_effort':'xhigh', 'thinking_token_budget':4096,
            'temperature':0.7, 'top_p':0.95, 'top_k':20, 'min_p':0.0,
            'presence_penalty':0.0, 'repetition_penalty':1.0, 'stream':True}


def prepare_spec(intent, harness=None):
    """Resolve an immutable data request without executing a model or a source."""
    from benchclaw.domain import DatasetSpec
    root = _harness(harness)
    if not isinstance(intent, dict) or bool(intent.get('recipe')) == bool(intent.get('spec')):
        raise ValueError('Provide exactly one recipe or complete DatasetSpec')
    _check_secrets(intent)
    if intent.get('recipe'):
        path = (root / intent['recipe']).resolve()
        if path not in [p.resolve() for p in _recipe_files(root)]:
            raise ValueError('Recipe must be an explicit JSON entry under the Harness examples directory')
        raw = json.loads(path.read_text(encoding='utf-8'))
        # Recipe research is unrelated to reproducing its data pipeline. It may
        # still be explicitly requested through overrides.
        raw['research'] = {}
    else:
        raw = copy.deepcopy(intent['spec'])
    overrides = intent.get('overrides', {})
    if not isinstance(overrides, dict):
        raise ValueError('overrides must be DatasetSpec fields')
    raw.update(copy.deepcopy(overrides))
    split = intent.get('split')
    if split not in {None, 'train', 'dev'}:
        raise ValueError('split must be train or dev')
    if split is not None:
        raw['purpose'] = 'training' if split == 'train' else 'evaluation'
    for source in raw.get('sources', []):
        if _excluded(source.get('plugin', '')):
            raise ValueError('This legacy capture worker is not used: create a desktop Isaac scene or import already materialized observations')
        params = source.get('parameters', {})
        source_split = params.get('annotation', {}).get('split', params.get('split', 'test'))
        if raw.get('purpose') == 'training' and source_split != 'train':
            raise ValueError('Training requires source scenes already assigned to train; this adapter never relabels test/dev sources')
        annotation = params if source.get('plugin') == 'source.default_annotation' else params.get('annotation')
        if annotation is not None:
            model = _model_settings()
            annotation.update(vlm_model=model['model_id'], vlm_base_url=model['endpoint'].removesuffix('/v1/chat/completions'),
                              vlm_generation={k:v for k,v in model.items() if k not in {'model_id','endpoint','api_key_env'}},
                              annotation_producer='qwen38-flash-next+yoloe+sam3+da3')
    review = intent.get('review', True)
    if not isinstance(review, (bool, dict)):
        raise ValueError('review must be a boolean or review settings object')
    if review is not False:
        target = int(raw.get('target_items', 15))
        if target > 100:
            raise ValueError('The inherited review worker accepts 100 candidates per task; submit source-disjoint intents to produce a larger batch')
        existing = raw.get('semantic_review', {})
        settings = {k:existing[k] for k in ('item_ids','rubric_version','max_revisions') if k in existing}
        if isinstance(review, dict):
            settings.update(review)
        raw['semantic_review'] = {**_model_settings(), 'rubric_version':'v4', 'max_revisions':0,
                                  **settings, 'max_items':target, 'dataset_objective':raw['objective']}
        raw.setdefault('collection_policy', {'min_items':1, 'min_source_records':1})
        if raw['collection_policy'] is None:
            raw['collection_policy'] = {'min_items':1, 'min_source_records':1}
    else:
        raw['semantic_review'] = {}
        raw['collection_policy'] = None
    spec = DatasetSpec.model_validate(raw)
    return spec


def _link_run(store, task, plan):
    """Bind parent and compiled child in one transaction, including crash recovery."""
    from sqlalchemy import select
    from benchclaw.domain import now, uid
    from benchclaw.metadata import runs, tasks
    with store.repo.transaction() as conn:
        parent = conn.execute(select(tasks).where(tasks.c.id == task['id']).with_for_update()).mappings().one()
        linked = parent['unit'].get('harness_run_id')
        if linked:
            return linked
        child = uid('run')
        conn.execute(runs.insert().values(id=child, state='PENDING', plan=plan.model_dump(mode='json'),
                                         created_at=now(), code_revision='spatialforge-data-adapter/v1'))
        for unit in plan.tasks:
            conn.execute(tasks.insert().values(id=f'{child}.{unit.task_id}', run_id=child,
                                               task_id=unit.task_id, unit=unit.model_dump(mode='json'),
                                               state='PENDING', attempt=0, ready_at=0))
        conn.execute(tasks.update().where(tasks.c.id == task['id']).values(
            unit={**parent['unit'], 'harness_run_id':child}))
        store.repo.event(conn, child, None, 'run.submitted', {'spatialforge_parent_task':task['id']})
        store.repo.event(conn, task['run_id'], task['id'], 'spatialforge.dataset_linked', {'harness_run_id':child})
        return child


def _execution_control(store, task, child, row, backend, stop, done):
    """Revoke only this task's lease; the inherited worker then stops its process."""
    from sqlalchemy import select
    from benchclaw.metadata import tasks
    while not done.wait(0.5):
        canceled = store.snapshot(task['run_id'])['state'] == 'CANCELED'
        if canceled:
            if backend.status(child)['state'] != 'SUCCEEDED':
                backend.cancel(child)
            return
        if stop is not None and stop.is_set():
            with store.repo.transaction() as conn:
                current = conn.execute(select(tasks).where(tasks.c.id == row['id']).with_for_update()).mappings().one()
                if current['state'] == 'RUNNING' and current['lease_owner'] == row['lease_owner']:
                    conn.execute(tasks.update().where(tasks.c.id == row['id']).values(
                        state='READY', lease_owner=None, lease_expires_at=None,
                        attempt=max(0, current['attempt']-1), ready_at=time.time(),
                        failure={'code':'SPATIALFORGE_SERVICE_STOP', 'message':'Service stopped; partial attempt retained and task is resumable'}))
                    store.repo.event(conn, child, row['id'], 'spatialforge.worker_yielded')
            return


def _brief(snapshot):
    return {'harness_run_id':snapshot['id'], 'state':snapshot['state'],
            'tasks':[{'task_id':t['task_id'], 'state':t['state'], 'attempt':t['attempt'],
                      'failure':t.get('failure'),
                      # Quarantine is a completed gate result, often without an
                      # exception/failure object. Retain its actual gate reasons.
                      'issues':(t.get('result') or {}).get('issues', []),
                      'metrics':(t.get('result') or {}).get('metrics', {}),
                      'artifact':t.get('artifact', {}).get('uri') if t.get('artifact') else None}
                     for t in snapshot['tasks']]}


def run_dataset(store, task, stop=None):
    """Execute acquisition → GT/synthesis → critique → collection → export.

    The caller may resume the same SpatialForge task after a service restart.
    The linked child and successful plugin artifacts are reused, never reset.
    """
    from benchclaw.compiler import compile_spec
    from benchclaw.domain import DatasetSpec
    from benchclaw.plugins import Registry
    from benchclaw.release import build_release
    from benchclaw.training import build_training_release
    from benchclaw.store import ArtifactStore, write_json
    from benchclaw.workflow import LocalWorkflowBackend
    from .generation import ResourceWait
    root = _harness(getattr(store, 'harness', None))
    registry = Registry()
    current = next(t for t in store.snapshot(task['run_id'])['tasks'] if t['id'] == task['id'])
    child = current['unit'].get('harness_run_id')
    if child:
        spec = DatasetSpec.model_validate(store.repo.status(child)['plan']['spec'])
    else:
        spec = prepare_spec(task['unit']['intent'], root)
        plan = compile_spec(spec, registry)
        for unit in plan.tasks:
            if _excluded(unit.plugin_id) or registry.get(unit.plugin_id).describe().kind == 'evaluator':
                raise ValueError('The compiled data plan contains a simulator or target-model evaluation outside this production scope')
        child = _link_run(store, task, plan)
    directory = store.directory(task['id'], task['unit']['revision'])
    artifacts = ArtifactStore(Path(store.root) / 'datasets')
    backend = LocalWorkflowBackend(store.repo, artifacts, registry)
    write_json(directory/'dataset_spec.json', spec.model_dump(mode='json'))
    write_json(directory/'dataset_link.json', {'harness_run_id':child, 'artifact_root':str(artifacts.root),
                                              'target_model_evaluation':False})
    backend.recover_expired(child)
    while True:
        if stop is not None and stop.is_set():
            raise ResourceWait('Dataset run retained for service resume: '+child)
        if store.snapshot(task['run_id'])['state'] == 'CANCELED':
            if backend.status(child)['state'] != 'SUCCEEDED':
                backend.cancel(child)
            raise RuntimeError('Dataset production canceled; artifacts retained: '+child)
        row = store.repo.claim(child)
        if row is not None:
            done = threading.Event()
            watcher = threading.Thread(target=_execution_control, args=(store,task,child,row,backend,stop,done), daemon=True)
            watcher.start()
            try:
                backend.execute(row)
            finally:
                done.set()
                watcher.join(timeout=2)
            continue
        store.repo.refresh(child)
        snapshot = backend.status(child)
        write_json(directory/'dataset_status.json', _brief(snapshot))
        if snapshot['state'] == 'SUCCEEDED':
            record = (build_training_release if spec.purpose == 'training' else build_release)(store.repo, artifacts, child)
            result = {'directory':str(directory), 'harness_run_id':child, 'release':record,
                      'target_model_evaluation':False,
                      'publication_status':('reviewed_training_dataset' if spec.purpose == 'training' else 'reviewed_development_dataset') if spec.semantic_review else 'unreviewed_'+record['status'].lower()+'_candidate',
                      'gt_modified_by_reviewer':False}
            write_json(directory/'dataset_result.json', result)
            return result
        if snapshot['state'] in {'FAILED_FINAL','BLOCKED_DEPENDENCY','CANCELED'}:
            failed = [t['task_id']+':'+t['state'] for t in snapshot['tasks'] if t['state'] in {'FAILED_FINAL','QUARANTINED','BLOCKED_DEPENDENCY','CANCELED'}]
            raise RuntimeError('Dataset candidate retained in '+str(directory)+'; '+child+' '+', '.join(failed)+'; gate issues and metrics: dataset_status.json')
        # Retry delays and a surviving worker lease should not occupy the entire
        # SpatialForge coordinator; its next turn resumes this same linked run.
        raise ResourceWait('Dataset child is waiting on its recorded worker/retry lease: '+child)
