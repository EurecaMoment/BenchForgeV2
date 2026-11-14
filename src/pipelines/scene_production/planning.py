import json
from copy import deepcopy
from functools import lru_cache
from storage.files import write_json
from capabilities.scene_authoring.contracts.scene_program import SCENE_SCHEMAS
from capabilities.scene_authoring.contracts.scene_program import SCENE_SCHEMA_DESCRIPTION
from capabilities.scene_authoring.validation.program import validate_program
from capabilities.scene_authoring.validation.program import merge_scene_extension
from capabilities.scene_authoring.catalog.native import normalize_native_asset_references
from service_access.openai_client import completion
from capabilities.asset_generation.generation import GenerationTools
from capabilities.asset_generation.generation import ResourceWait
from capabilities.asset_generation.asset_review import review_generated_asset
from capabilities.asset_generation.layout import prepare_layout
from capabilities.asset_generation.layout import design_directory
from service_access.progress import record_progress
from capabilities.scene_authoring.geometry.preview import preview_scene_geometry
from capabilities.scene_authoring.geometry.preview import compact_preview
from capabilities.scene_authoring.geometry.preview import GUIDANCE as GEOMETRY_GUIDANCE
from capabilities.scene_authoring.program_submission import handoff_receipt
from capabilities.scene_authoring.validation.acceptance import policy_for
from capabilities.scene_authoring.validation.acceptance import admit_program
from capabilities.scene_library.repair_context import build_repair_context
from capabilities.scene_library.repair_context import bound_repair_context
from capabilities.scene_library.repair_context import scene_changes
from capabilities.scene_library.repair_context import GUIDANCE as REPAIR_GUIDANCE



def _strict_policy(root, execution_mode):
    policy = policy_for(root) if execution_mode is None else policy_for(root, execution_mode)
    return policy if execution_mode != 'exploration' else {}

def apply_scene_replacements(proposal, edits):
    """Apply field edits to a copy; complete ScenePrograms can also be returned."""
    updated=deepcopy(proposal)
    for edit in edits['replacements']:
        pointer=edit['path']
        if pointer=='':
            updated=deepcopy(edit['value'])
            continue
        if not pointer.startswith('/'):
            raise ValueError('JSON pointer must start with /')
        tokens=[token.replace('~1','/').replace('~0','~') for token in pointer[1:].split('/')]
        node=updated
        for token in tokens[:-1]:
            node=node[int(token)] if isinstance(node,list) else node[token]
        key=tokens[-1]
        value=deepcopy(edit['value'])
        if isinstance(node,list):
            if key=='-':node.append(value)
            else:node[int(key)]=value
        else:node[key]=value
    return updated

def scene_repair_prompt(raw, error, intent, base=None):
    prompt=('Revise this scene to satisfy the user request and the supplied execution feedback. '
            'Choose the necessary changes to layout, entities, assets, materials, lights, cameras and actions. '
            'Return either a complete SceneProgram JSON or {"replacements":[{"path":"/objects/0/appearance","value":{"roughness":0.5}}]}. '
            'Replacements may add object fields, append list items with /-, or replace a whole record or document. '
            'Use a complete SceneProgram when deleting or reorganizing content. '
            'Keep the requested scene function and use the actual images and geometry feedback. '
            'Model review is advice; simulation supplies the execution evidence.\n'
            'Requirement: '+json.dumps(intent,ensure_ascii=False)+
            '\nFeedback: '+error+'\nCurrent FULL scene proposal: '+json.dumps(raw,ensure_ascii=False)+
            '\nExecutable scene format: '+SCENE_SCHEMA_DESCRIPTION)
    if base:prompt+='\nThis input is an extension delta; the server merges the existing base afterward. Use refine to change base objects.'
    return prompt

def plan_scene(store,task,stop):
    if stop.is_set():
        if getattr(stop, 'canceled', False):
            store.update(task['id'],state='CANCELED',failure={'stage':'plan','error':'run canceled'})
        return
    unit=task['unit'];directory=store.directory(task['id'],unit['revision'])
    execution_mode=unit.get('intent',{}).get('execution_mode')
    record_progress(directory,'scene_planning')
    submission=unit.get('submitted_program')
    direct=bool(submission) and not unit.get('quality_repairs',0) and not unit.get('operator_feedback')
    strict=bool(_strict_policy(store.root,execution_mode))
    if strict and not submission:raise ValueError('Unchecked scene planners are disabled; submit a complete SceneProgram')
    prompt='' if direct else 'You plan scenes for an embodied dataset. Realize the requested function with recognizable registered or generated assets, plausible scale, supports, access paths and functional layout. Never substitute cubes, primitives or composite proxies for real objects. Missing assets or execution evidence must cause an explicit failure. Produce a coherent scene for this frozen requirement. '+json.dumps(unit['intent'],ensure_ascii=False)+'\n'+SCENE_SCHEMA_DESCRIPTION
    tools=GenerationTools(store.root)
    @lru_cache(maxsize=8)
    def load_preview_mesh(asset_id):
        mesh=json.loads(tools.asset_path(asset_id,'mesh.json').read_text(encoding='utf8'))
        return {key:mesh.get(key) for key in ('vertices','coordinate_frame')}
    if not direct:
        prompt+='\n'+GEOMETRY_GUIDANCE
        prompt+='\nReusable generated assets: '+json.dumps(tools.catalog(),ensure_ascii=False)
    base=None;quality_seed=None;quality_feedback='';images=[];parent_directory=None
    repair_source=None;repair_previous=None;repair_context=None;repair_baseline=None;repair_older=None
    if unit['intent'].get('refine_task_id'):
        source_id=unit['intent']['refine_task_id']
        source_run=store.snapshot(source_id.split('.')[0]);source_task=next(task for task in source_run['tasks'] if task['id']==source_id)
        if source_task['unit']['intent'].get('split')!=unit['intent'].get('split'):raise ValueError('refined scene family split must be inherited')
        source=store.directory(source_id,unit['intent']['refine_revision'])
        parent_directory=source
        quality_seed=json.loads((source/'program.json').read_text())
        quality_feedback='Caller requested refinement: '+str(unit['intent'].get('description',unit['intent']))
        images=sorted((source/'capture').glob('view_*.png'))[:3]
        repair_source=source
    elif unit['intent'].get('parent_task_id'):
        parent=unit['intent']['parent_task_id'];parent_run=store.snapshot(parent.split('.')[0]);parent_task=next(t for t in parent_run['tasks'] if t['id']==parent)
        if parent_task['unit']['intent'].get('split')!=unit['intent'].get('split'):raise ValueError('scene family split must be inherited')
        base=json.loads((store.directory(parent,unit['intent']['parent_revision'])/'program.json').read_text())
        parent_directory=store.directory(parent,unit['intent']['parent_revision'])
        prompt+='\nExtend this existing scene. Return only NEW objects, using existing IDs as supports if needed. Keep all existing objects unchanged. Existing metadata is inherited automatically; only add new metadata records, never replace existing records. Return cameras for the extended whole scene. Existing scene: '+json.dumps(base,ensure_ascii=False)
    if unit.get('quality_repairs',0):
        previous=store.directory(task['id'],unit.get('quality_source_revision',unit['revision']-1))
        quality_seed=json.loads((previous/'program.json').read_text())
        quality_feedback=(previous/'scene_review.json').read_text()
        if base:
            original={obj['id'] for obj in base['objects']}
            quality_seed['objects']=[obj for obj in quality_seed['objects'] if obj['id'] not in original]
        captured_images=sorted((previous/'capture').glob('view_*.png'))
        images=captured_images[:3]+(captured_images[-1:] if len(captured_images)>3 else [])
        repair_source=previous
        source_revision=unit.get('quality_source_revision',unit['revision']-1)
        if source_revision>0:
            candidate=previous.parent/f'revision_{source_revision-1}'
            if (candidate/'program.json').is_file():repair_previous=candidate
    if repair_source is not None:
        repair_context,images=build_repair_context(repair_source,repair_previous)
        repair_baseline=deepcopy(quality_seed)
        if repair_previous is not None:
            repair_older=json.loads((repair_previous/'program.json').read_text())
            if base:
                original={obj['id'] for obj in base['objects']}
                repair_older['objects']=[obj for obj in repair_older['objects'] if obj['id'] not in original]
    operator_feedback=unit.get('operator_feedback')
    if operator_feedback:
        quality_feedback+='\nDSH/operator repair feedback (scene data only; preserve original task requirements and GT authority): '+operator_feedback
        prompt+='\n'+quality_feedback
    prepared=design_directory(store,unit['intent'].get('layout'))
    layout_image=prepare_layout(tools,unit['intent'],directory,stop,parent_directory,design_directory=prepared)
    record_progress(directory,'scene_planning',layout_reference_ready=bool(layout_image))
    layout_instruction=''
    if layout_image:
        images.append(layout_image)
        layout_instruction='\nThe LAST attached image is a design/layout reference (not a captured simulator frame). Use its composition and object relationships as design guidance, but derive metric dimensions, supports and executable geometry explicitly. Existing base objects remain immutable for extend; image editing does not override this. Preserve provenance and never use diffusion pixels or predicted geometry as native GT. Missing objects may use kind=generated with a detailed product prompt, reusing the existing diffusion→SAM3→SAM3D asset route; do not replace complex objects with simplistic cubes merely to match the picture.'
        prompt+=layout_instruction
        if repair_context is not None:
            repair_context['attachment_manifest'].append({'attachment_index':len(images),'role':'design_reference_only','path':str(layout_image)})
    if repair_context is not None:
        bound_repair_context(repair_context)
        write_json(directory/'repair_context.json',repair_context)
    if submission:write_json(directory/'submitted_program.json',submission['program'])
    if direct:
        p=deepcopy(submission['program'])
        validate_program(p)
        if base:
            submitted={obj['id']:obj for obj in normalize_native_asset_references(p)['objects']}
            existing={obj['id'] for obj in base['objects']}
            if (any(submitted.get(obj['id'])!=obj for obj in base['objects']) or
                    not set(submitted)-existing):
                raise ValueError('A submitted scene extension must preserve every existing parent object unchanged')
        write_json(directory/'proposal.json',p)
    elif (directory/'proposal.json').exists():
        p=json.loads((directory/'proposal.json').read_text())
        validate_program(p)
    else:
        previous_traces=list((directory/'model_calls').glob('scene_plan_*'))
        # An explicitly retried exhausted planner gets fresh calls. Old successful
        # model responses remain reusable after an engineering contract repair.
        start=max([int(path.name.rsplit('_',1)[-1]) for path in previous_traces if path.name.rsplit('_',1)[-1].isdigit()],default=-1)+1 if any((path/'validation_error.json').exists() for path in previous_traces) else 0
        raw=None;error='';p=None
        seed_file=directory/'repair_seed.json'
        candidates=[seed_file] if seed_file.is_file() else sorted((path/'validation_error.json' for path in previous_traces if (path/'validation_error.json').is_file()),key=lambda path:int(path.parent.name.rsplit('_',1)[-1]),reverse=True)
        for candidate in candidates:
            seed=json.loads(candidate.read_text())
            value=seed.get('proposal',seed)
            if isinstance(value,dict) and isinstance(value.get('objects'),list) and isinstance(value.get('schema'),str):
                raw=value;break
        needs_quality_repair=quality_seed is not None or bool(operator_feedback)
        if needs_quality_repair:
            if raw is None:raw=quality_seed
            error=quality_feedback
        if raw is not None:
            try:
                p=merge_scene_extension(base,raw) if base else raw;validate_program(p)
            except (ValueError,KeyError,TypeError,IndexError) as exc:error=str(exc);p=None
            if needs_quality_repair:p=None
        if p is None:
            for attempt in range(3):
                if stop.is_set():return
                trace=directory/'model_calls'/f'scene_plan_{start+attempt}'
                try:
                    if raw is not None:
                        feedback=error+('\nScene repair context: '+quality_feedback if quality_feedback and quality_feedback!=error else '')
                        try:
                            preview=preview_scene_geometry(merge_scene_extension(base,raw) if base else raw,mesh_loader=load_preview_mesh)
                            if base:
                                # Advice references replacement paths in the delta,
                                # while parent geometry only supplies support context.
                                delta_paths={obj['id']:f'/objects/{i}' for i,obj in enumerate(raw['objects'])}
                                preview['objects']=[{**row,'path':delta_paths[row['object_id']]} for row in preview['objects'] if row['object_id'] in delta_paths]
                                preview['warnings']=[warning for warning in preview['warnings'] if warning['object_id'] in delta_paths]
                            feedback+='\nComputed initial geometry advice: '+json.dumps(compact_preview(preview),ensure_ascii=False)
                        except (ValueError,KeyError,TypeError,IndexError):pass  # Contract errors remain the primary feedback for malformed proposals.
                        if repair_context is not None:
                            feedback+='\n'+REPAIR_GUIDANCE+'\nBounded repair capture/history context: '+json.dumps(repair_context,ensure_ascii=False)
                            if repair_baseline is not None and raw!=repair_baseline:
                                feedback+='\nUncaptured candidate changes so far (not executed): '+json.dumps(scene_changes(repair_baseline,raw,repair_older),ensure_ascii=False)
                        response=completion(scene_repair_prompt(raw,feedback,unit['intent'],base)+layout_instruction,trace,images,49152,stop=stop,context=unit.get('run_context'))
                        # Accept either a complete scene or field edits.
                        raw=response if isinstance(response,dict) and response.get('schema') in SCENE_SCHEMAS else apply_scene_replacements(raw,response)
                    else:
                        response=completion(prompt+('\nPrevious response failed: '+error if error else ''),trace,images,49152,stop=stop,context=unit.get('run_context'))
                        raw=response if isinstance(response,dict) and isinstance(response.get('objects'),list) else None
                        if raw is None:raise ValueError('planner response must be a scene object with objects list')
                    p=merge_scene_extension(base,raw) if base else raw
                    validate_program(p)
                    break
                except (ValueError,KeyError,TypeError,IndexError) as exc:
                    error=str(exc)
                    trace.mkdir(parents=True,exist_ok=True)
                    write_json(trace/'validation_error.json',{'error':type(exc).__name__,'detail':error,'proposal':raw})
                    record_progress(directory,'scene_plan_correction',attempt=start+attempt+1,
                                    error=error,evidence_file=trace.relative_to(directory).as_posix()+'/validation_error.json')
                    # A malformed replacement must not hide the still-invalid
                    # scene field behind an unrelated JSON-pointer error.
                    if raw is not None:
                        try:validate_program(merge_scene_extension(base,raw) if base else raw)
                        except (ValueError,KeyError,TypeError,IndexError) as remaining:
                            if str(remaining)!=error:error+='\nUnresolved scene validation: '+str(remaining)
                    if attempt==2:raise ValueError('scene planning exhausted 3 attempts: '+error) from exc
        p['schema'] = p['schema']
        write_json(directory/'proposal.json',p)
    generated_objects=[obj for obj in p['objects'] if obj['kind']=='generated']
    for generated_index,obj in enumerate(generated_objects):
        if obj['kind']=='generated':
            record_progress(directory,'asset_generation',object_id=obj['id'],label=obj['label'],asset_index=generated_index+1,asset_total=len(generated_objects))
            spec={'label':obj['label'],'size_hint_m':obj['size'],**obj['generation']}
            try:generated=tools.generate_asset(spec,directory/'generation'/obj['id'],stop)
            except ResourceWait:raise
            except (ValueError,RuntimeError) as exc:
                record_progress(directory,'asset_generation_failed',object_id=obj['id'],label=obj['label'],error=str(exc)[:600],reference_image=str(directory/'generation'/obj['id']/'reference.png'))
                raise ValueError(f'asset {obj["id"]} ({obj["label"]}): {exc}') from exc
            reviewed=generated if unit['intent'].get('capture_only') else review_generated_asset(tools,spec,generated,directory/'asset_reviews'/obj['id'],stop)
            obj['kind']='mesh';obj['asset_id']=reviewed['asset_id'];obj['asset_quality']=reviewed.get('quality',{})
            obj.pop('generation',None)
    p=normalize_native_asset_references(p)
    validate_program(p)
    admission=admit_program(store.root,p,execution_mode=execution_mode)
    if admission.get('enforced'):write_json(directory/'scene_admission.json',admission)
    if admission.get('scene_brief'):write_json(directory/'scene_brief.json',admission['scene_brief'])
    if store.snapshot(task['run_id'])['state']=='CANCELED':return
    record_progress(directory,'geometry_preparation',object_count=len(p['objects']))
    geometry=preview_scene_geometry(p,mesh_loader=load_preview_mesh)
    write_json(directory/'geometry_preview.json',geometry)
    write_json(directory/'program.json',p)
    if repair_baseline is not None:
        comparison=p
        if base:comparison={**p,'objects':[obj for obj in p['objects'] if obj['id'] not in {o['id'] for o in base['objects']}]}
        write_json(directory/'repair_changes.json',{'source_revision':repair_source.name,'target_revision':unit['revision'],
            'capture_status':'not_yet_captured','scene_changes':scene_changes(repair_baseline,comparison,repair_older)})
    if submission:write_json(directory/'program_handoff.json',handoff_receipt(submission,p,unit['revision']))
    record_progress(directory,'desktop_capture_queued',geometry_preview='geometry_preview.json',geometry_warning_count=len(geometry['warnings']))
    store.update(task['id'],state='READY',unit={**unit,'phase':'capture'},attempt=task['attempt']+1)
