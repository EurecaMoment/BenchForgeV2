import json
import time
import traceback
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from benchclaw.store import write_json
from .contracts import SCENE_SCHEMA_DESCRIPTION,validate_program,merge_scene_extension,normalize_native_asset_references
from .model import completion
from .products import produce
from .generation import GenerationTools,ResourceWait
from .asset_review import review_generated_asset
from .scene_quality import audit_scene
from .layout import prepare_layout
from .design import design_directory,execute_design
from .progress import record_progress
from .geometry_preview import preview_scene_geometry,compact_preview,GUIDANCE as GEOMETRY_GUIDANCE
from .program_submission import handoff_receipt
from .repair_context import build_repair_context,bound_repair_context,scene_changes,GUIDANCE as REPAIR_GUIDANCE


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
    unit=task['unit'];directory=store.directory(task['id'],unit['revision'])
    record_progress(directory,'scene_planning')
    submission=unit.get('submitted_program')
    direct=bool(submission) and not unit.get('quality_repairs',0) and not unit.get('operator_feedback')
    prompt='' if direct else 'You plan scenes for an embodied dataset. Actively realize the requirement: combine available assets, primitives and composite geometry creatively. Use multiple parts for unfamiliar objects, choose useful alternative geometry, and preserve the requested function. Prefer concrete attempts and iterate from feedback over declaring inability. Produce a readable coherent scene for this frozen requirement. '+json.dumps(unit['intent'],ensure_ascii=False)+'\n'+SCENE_SCHEMA_DESCRIPTION
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
                        response=completion(scene_repair_prompt(raw,feedback,unit['intent'],base)+layout_instruction,trace,images,49152)
                        # Accept either a complete scene or field edits.
                        raw=response if isinstance(response,dict) and response.get('schema') in {'spatialforge.scene/v1','spatialforge.scene/v2'} else apply_scene_replacements(raw,response)
                    else:
                        response=completion(prompt+('\nPrevious response failed: '+error if error else ''),trace,images,49152)
                        raw=response if isinstance(response,dict) and isinstance(response.get('objects'),list) else None
                        if raw is None:raise ValueError('planner response must be a scene object with objects list')
                    p=merge_scene_extension(base,raw) if base else raw
                    validate_program(p);break
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


def review_scene(store,task,stop):
    unit=task['unit'];directory=store.directory(task['id'],unit['revision']);capture=directory/'capture'
    record_progress(directory,'scene_review')
    report=json.loads((capture/'report.json').read_text())
    program=json.loads((directory/'program.json').read_text())
    evidence=json.loads((capture/'evidence.json').read_text()) if (capture/'evidence.json').is_file() else {}
    if report['status']=='captured':
        prompt='检查实际 Isaac 视图和执行证据是否满足原始场景需求：'+json.dumps(unit['intent'],ensure_ascii=False)+'''。
返回 JSON：{"acceptable":boolean,"visual_quality":1到5,"semantic_fidelity":1到5,"issues":[string],"repair_suggestions":[string],"visual_realism":{"status":"needs_improvement"|"visually_plausible"|"not_requested","issues":[string],"prioritized_repairs":[string],"basis":"rendered_views_only"}}。
依据任务判断物体身份、尺度、支撑、功能分区、材质、采光和机位。逼真室内要求还应检查建筑围合、连接细节、间接光、接触阴影及亮部纹理；明确可见的实质缺陷应影响 acceptable。每项问题标出对应视图或执行记录，建议具体的资产、程序或采集调整。
执行回执说明实际使用的资产、尺寸、姿态和材质；视觉评价说明是否可辨识且符合任务，两者分别陈述。采用最终世界姿态和实际尺寸；组合体的 size 是整体布局包络，geometry_parts 记录执行器实际创建的局部零件及 USD 类型，零件尺寸和偏移来自执行程序。区分几何构成与图片中的可辨识程度。AABB 是保守包围盒，预览警告不能单独证明穿透。材质 applied/skipped、纹理 fallback、未校准参数按回执解释。
physics 是动作前沉降；interaction 是实际施力轨迹，view_N 是动作结束后的视图，动作前后另有独立图片。建议采用已支持的程序字段；能力缺口直接说明。
当前是采集后的场景审查，数据生成和打包尚未执行，将在本阶段之后进行。target_items 是后续题目导出目标，不是当前物体或标注数量；最终包和导出计数此时缺失不能作为场景不合格理由。可据当前图像、分割和动作证据指出影响后续数据可用性的具体问题；导出是否成功由后续实际产物验证。
模型意见不写入 GT，也不等同人审、照片真实感认证或正式 benchmark 通过。
'''
        prompt+='\n沉降记录：'+json.dumps(report.get('physics',{}),ensure_ascii=False)
        prompt+='\n渲染执行记录：'+json.dumps(report.get('render_settings',{}),ensure_ascii=False)
        entity_fields={'shadow_settings','render_representation','appearance_scope','id','kind','label','prim_path','size','requested_size','initial_center','settled_center','final_center','current_center','declared_yaw_deg','world_transform','world_transform_convention','spatial_evidence_step','orientation_wxyz','world_aabb','support','dynamic','parameter_origin','physics','collision','appearance','geometry_parts'}
        dependency_fields={'appearance_scope','render_representation','gaussian','entity_id','kind','asset_id','asset_kind','embedded_geometry','vertices','triangles','source_frame','world_frame','source_up_axis','normalization','normalization_scale_xyz','uniform_scale','scale_mode','requested_size_limits_m','actual_size_m','source_bounds','oriented_bounds_before_scale','orientation_deg_xyz','orientation_source','source_watertight','appearance','appearance_overrides','transported_materials','transported_uvs','bound_texture_materials','texture_sampling','native_colliders_preserved','portability'}
        material_fields={'appearance_scope','entity_id','prim_path','kind','texture_id','texture_tint','uv_scale_m','color_space','normal_convention','calibration','source','roughness','metallic','applied','skipped'}
        receipt={'origin':evidence.get('origin'),'entities':[{key:value for key,value in entity.items() if key in entity_fields} for entity in evidence.get('entities',{}).values() if isinstance(entity,dict)],'asset_dependencies':[{key:value for key,value in dependency.items() if key in dependency_fields} for dependency in evidence.get('asset_dependencies',[]) if isinstance(dependency,dict)],'material_dependencies':[{key:value for key,value in dependency.items() if key in material_fields} for dependency in evidence.get('material_dependencies',[]) if isinstance(dependency,dict)],'realism':evidence.get('realism',{})}
        prompt+='\n实体与资产执行记录：'+json.dumps(receipt,ensure_ascii=False)
        geometry_path=directory/'geometry_preview.json'
        changes_path=directory/'repair_changes.json'
        if changes_path.is_file():
            changes=json.loads(changes_path.read_text())
            changes={**changes,'comparison_recorded_at':'before_capture','capture_status':report['status'],
                     'capture_token':report.get('token')}
            prompt+='\n本次程序改动对照：'+json.dumps(changes,ensure_ascii=False)
        if geometry_path.is_file():
            prompt+='\n仿真前的程序几何建议：'+json.dumps(compact_preview(json.loads(geometry_path.read_text())),ensure_ascii=False)
        camera_receipts=[{'frame_id':frame.get('frame_id'),'image':frame.get('image'),'camera':frame.get('camera'),'step_id':frame.get('step_id')} for frame in evidence.get('frames',[])]
        prompt+='\n相机执行记录：'+json.dumps(camera_receipts,ensure_ascii=False)
        prompt+='\n实际外力动作证据：'+json.dumps(evidence.get('interaction',{}),ensure_ascii=False)
        prompt+='\n环境贴图执行记录：'+json.dumps(evidence.get('environment_dependencies',[]),ensure_ascii=False)
        prompt+='\n灯具尺寸执行记录：'+json.dumps(evidence.get('light_receipts',[]),ensure_ascii=False)
        review_images=sorted(capture.glob('view_*.png'))
        for action_result in evidence.get('interaction',{}).get('action_results',[]):
            for key in ('before_image','after_image'):
                name=action_result.get(key)
                if name and (capture/name).is_file():review_images.append(capture/name)
        prompt+='\n实际图片顺序：'+json.dumps([image.name for image in review_images],ensure_ascii=False)
        layout_reference=directory/'layout_reference.png'
        if layout_reference.is_file():
            review_images.append(layout_reference)
            prompt+='\n最后一张是扩散设计参考，其余是实际 Isaac 视图。额外返回 design_alignment:{status:"aligned"|"partial"|"diverged",issues:[string]}，比较功能分区、主要物体、材质、采光和氛围；参考仅用于设计比较，不是仿真成品、GT 或像素匹配目标。'
        review=completion(prompt,directory/'model_calls'/'scene_review',review_images,5000)
    else: review={'acceptable':False,'issues':report['errors'],'repair_suggestions':['resolve execution error without changing pipeline code']}
    review['physical_stable']=report.get('physics',{}).get('stable',False);review['renderable']=report.get('renderable',False)
    frames=evidence.get('frames',[])
    native=evidence.get('origin')=='isaac_native'
    views=[frame for frame in frames if isinstance(frame,dict) and isinstance(frame.get('frame_id'),str) and (capture/(frame['frame_id']+'.png')).is_file()]
    quality_capture={**report,'views':views,'depth':[],'segmentation':{},'semantic_labels':{},'interaction':evidence.get('interaction',{})}
    for frame in views:
        name=frame['frame_id']
        if (capture/(name+'_depth.npy')).is_file():quality_capture['depth'].append(name+'_depth.npy')
    segmented=[frame for frame in views if (capture/(frame['frame_id']+'_semantic.npy')).is_file() and (capture/(frame['frame_id']+'_instance.npy')).is_file()]
    if native and segmented:
        labels={'authority':'simulator','frames':[{'frame_id':frame['frame_id'],'objects':frame.get('objects',[]),'semantic_info':frame.get('semantic_info',{}),'instance_info':frame.get('instance_info',{})} for frame in segmented]}
        quality_capture['segmentation']=labels;quality_capture['semantic_labels']=labels
    if isinstance(evidence.get('physics'),dict):quality_capture['physics']=evidence['physics']
    review['scene_quality']=audit_scene(program,quality_capture,unit['intent'])
    requested_actions=[action for action in program.get('interactions',program.get('affordances',[])) if action.get('action')=='apply_force']
    interaction=evidence.get('interaction',{})
    review['interaction']=interaction
    results={row.get('id'):row for row in interaction.get('action_results',[]) if isinstance(row,dict)}
    def action_has_receipt(action):
        result=results.get(action['id'],{})
        return (result.get('success') is True and result.get('action')=='apply_force' and result.get('object_id')==action['object_id']
                and all(isinstance(result.get(key),str) and (capture/result[key]).is_file() for key in ('trajectory_file','before_image','after_image')))
    interaction_passed=(native and interaction.get('validated') is True and all(action_has_receipt(action) for action in requested_actions)) if requested_actions else None
    if interaction_passed is False:
        review.setdefault('issues',[]).append('Requested physical interaction did not pass simulator validation')
        review.setdefault('repair_suggestions',[]).append('Repair action force, duration, surface clearance or dynamic support using the captured action trace')
    review['interaction_requested']=bool(requested_actions)
    review['interaction_passed']=interaction_passed
    passed=review.get('acceptable') is True and review['physical_stable'] and review['renderable'] and interaction_passed is not False
    review['passed']=passed
    review['publication_status']='pilot_candidate' if passed else 'exploration_requires_improvement'
    write_json(directory/'scene_review.json',review)
    if not passed:
        # The operator owns revisions of a submitted SceneProgram. Keep its
        # capture/review and export eligible observations without a second planner.
        if not unit.get('submitted_program') and unit.get('quality_repairs',0)<2 and report['status']=='captured':
            store.update(task['id'],state='PENDING',unit={**unit,'phase':'plan','revision':unit['revision']+1,'quality_source_revision':unit['revision'],'quality_repairs':unit.get('quality_repairs',0)+1})
            return
        if report['status']!='captured' or not review['renderable']:
            store.update(task['id'],state='FAILED_FINAL',failure={'scene_review':review,'artifacts_preserved':str(directory),'next_action':'engineering_recovery'},result={'directory':str(directory)})
            return
        # Exploration keeps useful observations even when scene-wide aesthetics or
        # dynamics still need work; product eligibility records the actual evidence.
    if store.snapshot(task['run_id'])['state']=='CANCELED':return
    record_progress(directory,'data_export')
    summary=produce(directory,unit['intent'].get('split','dev'),unit['intent'])
    record_progress(directory,'complete')
    store.update(task['id'],state='SUCCEEDED',result={'summary':summary,'directory':str(directory),'scene_review':review},unit={**unit,'phase':'complete'})


def _capture_handoff(unit):
    """CPU-only preparation/completion should not queue behind asset generation."""
    if unit['phase']=='review':return unit['intent'].get('capture_only',False)
    if unit['phase']!='plan' or not unit.get('submitted_program'):return False
    if unit.get('quality_repairs') or unit.get('operator_feedback'):return False
    if any(unit['intent'].get(key) for key in ('layout','parent_task_id','refine_task_id')):return False
    return not any(obj['kind']=='generated' for obj in unit['submitted_program']['program']['objects'])


def coordinate(store,stop):
    # One scheduler owns FIT stages. A slow GPU/model task does not block reviews.
    # GPU tool locks and desktop DB ownership independently serialize their devices.
    def execute(task):
            try:
                class TaskSignal:
                    def __init__(self):self.checked=0;self.canceled=False
                    def is_set(self):
                        if stop.is_set():return True
                        if time.monotonic()-self.checked>3:
                            self.canceled=store.snapshot(task['run_id'])['state']=='CANCELED';self.checked=time.monotonic()
                        return self.canceled
                task_stop=TaskSignal()
                phase=task['unit']['phase']
                if phase=='layout':
                    execute_design(store,task,task_stop)
                elif phase=='generation':
                    from .generation_stage import execute_generation_stage
                    execute_generation_stage(store,task,task_stop)
                elif phase=='asset':
                    directory=store.directory(task['id'],task['unit']['revision'])
                    intent=task['unit']['intent']
                    spec={'label':intent.get('label',intent['name']),'prompt':intent['description']}
                    spec.update({k:v for k,v in intent.items() if k in {'source_image','source_mask','source_mesh','source_gaussian','asset_id','seed','source_up_axis','size_hint_m','subject_box','edit_reference','texture_baking'}})
                    result=GenerationTools(store.root).generate_asset(spec,directory/'generation',task_stop)
                    if not (spec.get('source_mesh') or spec.get('asset_id')):
                        result=review_generated_asset(GenerationTools(store.root),spec,result,directory/'asset_review',task_stop,repair=False)
                    store.update(task['id'],state='SUCCEEDED',result=result,unit={**task['unit'],'phase':'complete'})
                elif phase=='dataset':
                    from .integration import run_dataset
                    result=run_dataset(store,task,stop=task_stop)
                    store.update(task['id'],state='SUCCEEDED',result=result,unit={**task['unit'],'phase':'complete'})
                elif phase=='review' and task['unit']['intent'].get('capture_only'):
                    directory=store.directory(task['id'],task['unit']['revision'])
                    report=json.loads((directory/'capture/report.json').read_text())
                    files=[{'file':p.relative_to(directory).as_posix(),'source_path':str(p)} for p in sorted((directory/'capture').glob('*')) if p.is_file()]
                    captured=report.get('status')=='captured'
                    result={'operation':'capture_only','directory':str(directory),'files':files,'report':report,
                            'scene_quality_assessed':False,'data_exported':False}
                    store.update(task['id'],state='SUCCEEDED' if captured else 'FAILED_FINAL',result=result,
                                 unit={**task['unit'],'phase':'complete' if captured else 'review'},failure=None if captured else {'capture_report':report})
                else:(plan_scene if phase=='plan' else review_scene)(store,task,task_stop)
            except ResourceWait as exc:
                store.update(task['id'],state='READY',ready_at=time.time()+30,failure={'waiting_resource':str(exc)})
            except Exception as exc:
                traceback.print_exc()
                store.update(task['id'],state='FAILED_FINAL',failure={'error':type(exc).__name__,'detail':str(exc)[:1000]})
    active={};handoffs={}
    with ThreadPoolExecutor(max_workers=3,thread_name_prefix='production') as pool, \
         ThreadPoolExecutor(max_workers=1,thread_name_prefix='capture-handoff') as capture_pool:
        while not stop.is_set():
            active={key:future for key,future in active.items() if not future.done()}
            handoffs={key:future for key,future in handoffs.items() if not future.done()}
            for task in store.all_work():
                if task['id'] in active or task['id'] in handoffs:continue
                if task['unit']['phase'] not in {'plan','review','asset','dataset','layout','generation'} or task['state'] not in {'PENDING','READY'} or (task.get('ready_at') or 0)>time.time():continue
                lightweight=_capture_handoff(task['unit'])
                pending=handoffs if lightweight else active
                if len(pending)>=(1 if lightweight else 3):continue
                store.update(task['id'],state='RUNNING',failure=None)
                pending[task['id']]=(capture_pool if lightweight else pool).submit(execute,task)
            store.settle_runs();stop.wait(2)
