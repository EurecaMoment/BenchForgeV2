"""Validate direct edits, save a new contract and invalidate the old production plan."""
from copy import deepcopy
from pathlib import Path
import re
from benchmark_workflows.server.storage.artifacts import read
from benchmark_workflows.server.pipelines.operation_runtime import Runtime
from benchmark_workflows.server.assessment_planning.assessment import assessment_with_current_schema
from benchmark_workflows.server.assessment_planning.plan_versions import current


ASSESSMENT_BLOCK = re.compile(r'^```assessment-yaml\s*\r?\n(.*?)^```\s*$', re.M | re.S)


def assessment_from_markdown(markdown, *, required=True):
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError('The edited Markdown document is empty')
    if len(markdown) > 512_000:
        raise ValueError('The edited Markdown document is too large')
    blocks = list(ASSESSMENT_BLOCK.finditer(markdown))
    if not blocks and not required:
        return None
    if len(blocks) != 1:
        raise ValueError('The Markdown document must contain exactly one ```assessment-yaml block')
    try:
        import yaml
        value = yaml.safe_load(blocks[0].group(1))
    except ImportError as error:
        raise ValueError('Markdown plan editing requires PyYAML in the production environment') from error
    except yaml.YAMLError as error:
        raise ValueError('The assessment-yaml block is invalid: ' + str(error).splitlines()[0]) from error
    if not isinstance(value, dict):
        raise ValueError('The assessment-yaml block must contain a mapping')
    return value


def save_edit(workspace,session,base_plan,assessment=None,split=None,*,markdown=None,base_markdown=None):
    markdown_edit = markdown is not None
    if markdown_edit:
        if assessment is not None:
            raise ValueError('Send either a complete Markdown document or a structured assessment, not both')
        if not isinstance(markdown, str) or len(markdown) > 512_000 or not markdown.strip():
            raise ValueError('The edited Markdown document must be non-empty and no larger than 512 KB')
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
    old=read(base)
    parsed=assessment_from_markdown(markdown,required=False) if markdown_edit else assessment
    def merge(original, edited):
        if isinstance(original,dict) and isinstance(edited,dict):
            return {**original,**{key:merge(original.get(key),child) for key,child in edited.items()}}
        if isinstance(original,list) and isinstance(edited,list):
            return [merge(original[index] if index<len(original) else None,child) for index,child in enumerate(edited)]
        return edited
    baseline_markdown=old.get('user_markdown','')
    if isinstance(base_markdown,str) and len(base_markdown)<=512_000:
        if baseline_markdown:
            old_narrative=re.sub(r'^```assessment-yaml\s*\r?\n.*?^```\s*$', '', baseline_markdown, flags=re.M|re.S).strip()
            base_narrative=re.sub(r'^```assessment-yaml\s*\r?\n.*?^```\s*$', '', base_markdown, flags=re.M|re.S).strip()
            if old_narrative!=base_narrative:
                raise ValueError('The Markdown baseline no longer matches the saved plan; refresh before editing.')
            baseline_markdown=base_markdown
        else:
            base_document=assessment_from_markdown(base_markdown,required=False)
            if base_document is None or assessment_with_current_schema(merge(old.get('assessment',{}),base_document))==assessment_with_current_schema(old.get('assessment',{})):
                baseline_markdown=base_markdown
            else:
                raise ValueError('The Markdown baseline does not match the saved assessment; refresh before editing.')
    if parsed is None:
        document=deepcopy(old.get('assessment'))
        markdown_normalization=True
    else:
        document=deepcopy(parsed)
        markdown_normalization=False
    if not isinstance(document, dict):
        raise ValueError('A complete assessment document is required')
    # Preserve fields deliberately excluded from the public document.
    document=merge(old.get('assessment',{}),document)
    prior_assessment = assessment_with_current_schema(old.get('assessment', {}))
    document = assessment_with_current_schema(document)
    if markdown_edit and parsed is not None:
        markdown_normalization=document==prior_assessment
    selections=[{'template_ids':[row['template_id']],'count':row['count'],'reason':row['selection_reason']}
                for row in document['coverage']]
    inputs=deepcopy(old['inputs'])
    inputs.update(selections=selections,target_items=document['dataset']['target_items'],seed=document['dataset']['seed'],
                  target_scene_count=document['scenes']['target_scene_count'])
    if split is not None:
        if split not in ('train','dev','test','sealed'):raise ValueError('Unknown execution partition')
        inputs['split']=split
    changes=[key for key in document if document.get(key)!=prior_assessment.get(key)]
    if markdown_edit and markdown != old.get('user_markdown'):
        changes.append('markdown_document')
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
          '_plan_edit':{'base_plan':str(base),'changes':changes,'application_required':True,
                        'markdown_edit':markdown_edit,'markdown_normalization':markdown_normalization,
                        'base_narrative':re.sub(r'^```assessment-yaml\s*\r?\n.*?^```\s*$', '', baseline_markdown, flags=re.M|re.S).strip()},
          **({'_user_markdown':markdown} if markdown_edit else {})}
    runtime=Runtime(root);runtime.dsh_context={'session_id':session,'call_id':'workbench-direct-plan-edit'}
    try:return runtime.call('pipeline_plan',args)
    finally:runtime.close()
