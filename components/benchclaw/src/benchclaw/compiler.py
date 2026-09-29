from .domain import DatasetSpec, HarnessError, Plan, WorkUnit
from .plugins import Registry


def validate_plan(plan: Plan, registry: Registry):
    names={unit.task_id for unit in plan.tasks}
    if len(names)!=len(plan.tasks):
        raise HarnessError('DUPLICATE_TASK','Task IDs must be unique')
    done=set()
    for unit in plan.tasks:
        plugin=registry.get(unit.plugin_id)
        if plugin.describe().version!=unit.plugin_version:
            raise HarnessError('PLUGIN_VERSION',unit.plugin_id)
        plugin.validate_parameters(unit.parameters)
        if not set(unit.depends_on)<=names:
            raise HarnessError('DAG_MISSING_DEPENDENCY',unit.task_id)
        if any(getattr(unit.resources,k)>getattr(plan.spec.capacity,k) for k in ('cpu','gpu','memory_gb')):
            raise HarnessError('INSUFFICIENT_RESOURCES',unit.task_id)
    while len(done)<len(names):
        ready={u.task_id for u in plan.tasks if u.task_id not in done and set(u.depends_on)<=done}
        if not ready:
            raise HarnessError('DAG_CYCLE','Workflow contains a cycle')
        done|=ready
    children={parent for u in plan.tasks for parent in u.depends_on}
    if names-children!={'validate'}:
        raise HarnessError('DAG_ORPHAN','All tasks must lead to the final validation task')


def compile_spec(spec: DatasetSpec, registry: Registry) -> Plan:
    if spec.task_contract=='spatial-v2':
        from .spatial_tasks import IDS
        if set(spec.template_ids)-IDS:
            raise HarnessError('TASK_CONTRACT_UNSUPPORTED','Unsupported spatial-v2 template selection')
    if spec.collection_policy and spec.collection_policy.min_items>spec.target_items:
        raise HarnessError('COLLECTION_ITEM_BUDGET','Candidate budget is below declared minimum accepted items')
    if spec.collection_policy and not spec.semantic_review:
        raise HarnessError('COLLECTION_REVIEW_REQUIRED','Collection acceptance requires item critique and collection review')
    if spec.purpose=='training' and not spec.semantic_review:
        raise HarnessError('TRAINING_REVIEW_REQUIRED','Training generation requires content review')
    units=[]
    if spec.research:
        units.append(WorkUnit(task_id='research',stage=1,plugin_id='planning.research',parameters=spec.research,retry=spec.retry))
    for source in spec.sources:
        plugin=registry.get(source.plugin)
        if plugin.describe().kind!='source':
            raise HarnessError('PLUGIN_KIND','Acquisition requires a source plugin')
        unit=WorkUnit(task_id=f'acquire_{source.source_id}',stage=2,plugin_id=source.plugin,
                      plugin_version=plugin.describe().version,parameters=source.parameters,
                      resources=plugin.describe().resources,retry=spec.retry)
        planned=plugin.plan(unit)
        if not planned or any(not u.task_id.startswith(unit.task_id) for u in planned):
            raise HarnessError('PLUGIN_PLAN','Source expansion must remain within its task namespace')
        units.extend(planned)
    parents={p for u in units for p in u.depends_on}
    leaves=[u.task_id for u in units if u.task_id not in parents or u.operation=='capture']
    if any(s.plugin in {'source.erqa','source.evalset'} for s in spec.sources) and any(s.plugin not in {'source.erqa','source.evalset'} for s in spec.sources) and spec.template_set=='bbox_center_2d':
        raise HarnessError('MIXED_TEMPLATE_SET','Mixed official and generated datasets require an explicit static template set')
    official=all(s.plugin in {'source.erqa','source.evalset'} for s in spec.sources)
    if official and all(s.parameters.get('indices') is not None for s in spec.sources):
        expected=sum(len(s.parameters['indices']) for s in spec.sources)
        if expected!=spec.target_items:raise HarnessError('OFFICIAL_COUNT','Target must equal the explicitly selected official records')
    candidates=any(s.plugin=='source.candidates' for s in spec.sources)
    if candidates and (len(spec.sources)!=1 or not spec.semantic_review or spec.research):
        raise HarnessError('CANDIDATE_REVIEW_SCOPE','Paired candidate snapshots require one source and semantic review')
    units.append(WorkUnit(task_id='evidence',stage=3,plugin_id='synthesis.candidates' if candidates else 'evidence.records' if spec.template_set!='bbox_center_2d' or official else 'evidence.geometry',depends_on=leaves,retry=spec.retry))
    units.append(WorkUnit(task_id='synthesis',stage=4,plugin_id='synthesis.candidates' if candidates else 'synthesis.official' if official else 'synthesis.templates' if spec.template_set!='bbox_center_2d' else 'synthesis.spatial',depends_on=['evidence'],retry=spec.retry))
    final_parent='synthesis'
    if spec.semantic_review:
        review_parameters=dict(spec.semantic_review)
        if review_parameters.get('rubric_version')=='v4':review_parameters['dataset_objective']=spec.objective
        units.append(WorkUnit(task_id='candidate_gate',stage=4,plugin_id='gate.dataset',depends_on=['synthesis'],retry=spec.retry))
        units.append(WorkUnit(task_id='semantic_review',stage=4,plugin_id='review.semantic',parameters=review_parameters,depends_on=['candidate_gate'],retry=spec.retry))
        final_parent='semantic_review'
    if spec.collection_policy:
        units.append(WorkUnit(task_id='collection_review',stage=4,plugin_id='review.collection',
                             parameters=spec.semantic_review,depends_on=[final_parent],retry=spec.retry))
        final_parent='collection_review'
    units.append(WorkUnit(task_id='validate',stage=4,plugin_id='gate.dataset',depends_on=[final_parent],retry=spec.retry))
    plan=Plan(spec=spec,tasks=units)
    validate_plan(plan,registry)
    return plan
