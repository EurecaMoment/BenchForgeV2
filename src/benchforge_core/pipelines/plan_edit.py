"""Validate direct edits, save a new contract and invalidate the old production plan."""
from copy import deepcopy
from pathlib import Path
from ..runtime import read, Runtime
from .plan_versions import current


def save_edit(workspace,session,base_plan,assessment,split=None):
    root=Path(workspace).resolve();base=Path(base_plan).resolve()
    if not base.is_relative_to(root) or base.name!='plan.json':
        raise ValueError('Only a saved plan inside this workspace can be edited')
    folder=base.parent
    while folder!=root:
        request=folder/'request.json'
        context=read(request).get('context',{}) if request.is_file() else {}
        state=folder/'state.json'
        if state.is_file():context=read(state).get('context',context)
        if context.get('session_id')==session or session in context.get('session_ids',[]):break
        folder=folder.parent
    else:raise ValueError('The plan does not belong to this conversation')
    active=current(root,session)
    if active and active['plan']!=str(base):
        raise ValueError('The displayed plan has been replaced. Refresh before editing.')
    old=read(base);document=deepcopy(assessment)
    # Preserve fields deliberately excluded from the public document.
    def merge(original, edited):
        if isinstance(original,dict) and isinstance(edited,dict):
            return {**original,**{key:merge(original.get(key),child) for key,child in edited.items()}}
        if isinstance(original,list) and isinstance(edited,list):
            return [merge(original[index] if index<len(original) else None,child) for index,child in enumerate(edited)]
        return edited
    document=merge(old.get('assessment',{}),document)
    selections=[{'template_ids':[row['template_id']],'count':row['count'],'reason':row['selection_reason']}
                for row in document['coverage']]
    inputs=deepcopy(old['inputs'])
    inputs.update(selections=selections,target_items=document['dataset']['target_items'],seed=document['dataset']['seed'],
                  target_scene_count=document['scenes']['target_scene_count'])
    if split is not None:
        if split not in ('train','dev','test','sealed'):raise ValueError('Unknown execution partition')
        inputs['split']=split
    changes=[key for key in document if document.get(key)!=old.get('assessment',{}).get(key)]
    if inputs.get('split')!=old['inputs'].get('split'):changes.append('split')
    if not changes:return {'state':'unchanged','plan':str(base)}
    steps=deepcopy(old['steps'])
    def update_bindings(value):
        if isinstance(value,list):return [update_bindings(child) for child in value]
        if not isinstance(value,dict):return value
        return {key:deepcopy(inputs[key]) if key in ('selections','target_items','seed','split','target_scene_count') and
                key in inputs and not (isinstance(child,str) and child.startswith('$')) else update_bindings(child) for key,child in value.items()}
    steps=update_bindings(steps)
    args={'objective':document['summary'],'pipeline_id':old['pipeline_id'],'assessment':document,
          'selections':selections,'inputs':inputs,'steps':steps,
          '_plan_edit':{'base_plan':str(base),'changes':changes,'application_required':True}}
    runtime=Runtime(root);runtime.dsh_context={'session_id':session,'call_id':'workbench-direct-plan-edit'}
    try:return runtime.call('pipeline_plan',args)
    finally:runtime.close()
