import json
import time
import traceback
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from sqlalchemy.exc import TimeoutError as DatabaseTimeout, OperationalError
from .files import write_json
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
from .scene_acceptance import policy_for, admit_program, capture_acceptance
from .scene_review_reference import review_spatial_context, GUIDANCE as REFERENCE_GUIDANCE
from .repair_context import build_repair_context,bound_repair_context,scene_changes,GUIDANCE as REPAIR_GUIDANCE
from .scene_scheduler import capture_handoff as _scheduler_capture_handoff
from .scene_scheduler import coordinate as _coordinate


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
                        raw=response if isinstance(response,dict) and response.get('schema') in {'spatialforge.scene/v1','spatialforge.scene/v2'} else apply_scene_replacements(raw,response)
                    else:
                        response=completion(prompt+('\nPrevious response failed: '+error if error else ''),trace,images,49152,stop=stop,context=unit.get('run_context'))
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


def review_scene(store,task,stop,*,capture_only=False):
    if stop.is_set():
        if getattr(stop, 'canceled', False):
            store.update(task['id'],state='CANCELED',failure={'stage':'review','error':'run canceled'})
        return
    unit=task['unit'];directory=store.directory(task['id'],unit['revision']);capture=directory/'capture'
    execution_mode=unit.get('intent',{}).get('execution_mode')
    record_progress(directory,'scene_review')
    report=json.loads((capture/'report.json').read_text())
    program=json.loads((directory/'program.json').read_text())
    evidence=json.loads((capture/'evidence.json').read_text()) if (capture/'evidence.json').is_file() else {}
    strict_policy = _strict_policy(store.root, execution_mode)
    physical_precheck=capture_acceptance(store.root,program,report,evidence,{},capture,execution_mode) if strict_policy else {}
    physical_issues=physical_precheck.get('physical_issues',[])
    spatial_context=None
    if report['status']=='captured' and not physical_issues:
        prompt='检查实际 Isaac 视图和执行证据是否满足原始场景需求：'+json.dumps(unit['intent'],ensure_ascii=False)+'''。
返回 JSON：{"acceptable":boolean,"visual_quality":1到5,"semantic_fidelity":1到5,"issues":[string],"repair_suggestions":[string],"visual_realism":{"status":"needs_improvement"|"visually_plausible"|"matches_declared_geometry"|"not_requested","issues":[string],"prioritized_repairs":[string],"basis":"rendered_views_only"}}。
依据任务判断物体身份、尺度、支撑、功能分区、材质、采光和机位。逼真室内要求还应检查建筑围合、连接细节、间接光、接触阴影及亮部纹理；明确可见的实质缺陷应影响 acceptable。每项问题标出对应视图或执行记录，建议具体的资产、程序或采集调整。
执行回执说明实际使用的资产、尺寸、姿态和材质；视觉评价说明是否可辨识且符合任务，两者分别陈述。采用最终世界姿态和实际尺寸；组合体的 size 是整体布局包络，geometry_parts 记录执行器实际创建的局部零件及 USD 类型，零件尺寸和偏移来自执行程序。区分几何构成与图片中的可辨识程度。AABB 是保守包围盒，预览警告不能单独证明穿透。材质 applied/skipped、纹理 fallback、未校准参数按回执解释。
physics 是动作前沉降；interaction 是实际施力轨迹，view_N 是动作结束后的视图，动作前后另有独立图片。建议采用已支持的程序字段；能力缺口直接说明。
当前是采集后的场景审查，数据生成和打包尚未执行，将在本阶段之后进行。target_items 是后续题目导出目标，不是当前物体或标注数量；最终包和导出计数此时缺失不能作为场景不合格理由。可据当前图像、分割和动作证据指出影响后续数据可用性的具体问题；导出是否成功由后续实际产物验证。
模型意见不写入 GT，也不等同人审、照片真实感认证或正式 benchmark 通过。
'''
        prompt+='\n沉降记录：'+json.dumps(report.get('physics',{}),ensure_ascii=False)
        if strict_policy:
            prompt+='''\n严格生产验收：默认要求真实可辨识的场景资产和符合生活常识的布局。简化几何只有保存计划明确声明的实验范围才可合格，不能以几何形状冒充真实家具。逐一检查物体身份、正常尺度、支撑与安装、房间用途与物品关系、通行与操作空间、材质与照明。任何不确定、缺图或问题必须 passed=false；不得仅凭名字、设计图或全静态 stable=true 宣称物理合理。额外返回 life_review:{checks:[{check:object_identity|realistic_scale|support_and_attachment|functional_layout|access_and_clearance|materials_and_lighting,passed:boolean,evidence:[{view:"view_0.png",observation:"该实际视图中的具体可见现象"}]}]}。六项分别恰好一条，每条给出真实已附图片文件名和具体观察；不合格给出可执行修改。visual_realism.status 必须根据实拍作出判断。模型意见不是物理测量或GT。'''
        if strict_policy:
            admission = admit_program(store.root, program,execution_mode=execution_mode)
            if admission.get('scene_brief'):
                brief=admission['scene_brief']
                context={k:brief[k] for k in ('name','summary','hard_requirements','object_roles','physical_assumptions')}
                if brief.get('spatial_reference'):context['spatial_reference']=brief['spatial_reference']
                spatial_context=review_spatial_context(brief,evidence,physical_precheck.get('native_relation_checks',[]))
                write_json(directory/'scene_spatial_context.json',spatial_context)
                prompt+='\n明确参照和本次原生方向/支撑事实（不能代替实际逐图生活检查）：'+json.dumps(spatial_context,ensure_ascii=False)
                context['visual_relations']=[{'index':i,**r} for i,r in enumerate(brief['relations']) if r['type'] not in {'supported_by','mounted_to'}]
                prompt += '\n必须对照的场景标题、摘要、角色及空间关系：' + json.dumps(context, ensure_ascii=False)
                prompt += ('\n额外返回 brief_alignment:{passed:boolean,hard_requirements_preserved:boolean,observations:[{view:"view_0.png",observation:"实际可见依据"}],'
                           'unresolved:[string],proposed_summary_revision:{reason:string,summary:string,changes:[string]}}。'
                           '检查摘要中的每个关键物体角色、支撑、邻接、朝向、取用与通行关系。功能布局须适合人在此实际使用。'
                           '对照全部机位发现椅子翻倒、柜门冲突、桌面穿物、悬空、失衡、比例扭曲或不合用途摆放均须失败。'
                           '摘要有遗漏或自身矛盾时提出具体修订，保留用户硬要求；不能通过改写摘要为已有缺陷开脱。'
                           '修订建议只是待执行设计，未重新采集验收不得把它当成修复证据。')
                prompt += ('\nbrief_alignment 另须完整返回 requirement_checks 与 relation_checks 数组：'
                           '分别按 hard_requirements 的0起始索引和 visual_relations 的原始index逐项检查，每条 {index:整数,passed:boolean,view:"view_0.png",observation:"具体可见依据"}。'
                           '不得遗漏、重复或仅笼统声称全部通过。实际图无法确认的要求应失败并留在unresolved。')
                prompt += '\n支撑和固定安装已按原生回执逐项校验并单独留证；不重复输出物理relation_checks。仍须检查图中可见的悬空、穿插和姿态缺陷，不能根据物体名字认为合格。'
                prompt += '\nbrief_alignment.observations 须逐一覆盖本次全部 view_N.png，每个视角写具体观察，不能只挑最好的一张。'
            declaration = admission.get('geometry_exception')
            if declaration:
                prompt += '\n保存计划声明的简化几何实验：' + json.dumps(declaration, ensure_ascii=False)
                prompt += ('\n按该声明检查几何身份、测量尺度、支撑与安装、实验布局、通行/操作空间和材质照明；'
                           '生活合理性采用声明的实验设定，不要求实验方块长得像日常家具。'
                           '六项逐图检查仍须通过，例外不替代物理证据。实拍符合声明时 visual_realism.status=matches_declared_geometry；'
                           '不符合时 needs_improvement 且 acceptable=false。不得将此实验标为真实生活场景。')
        prompt+='\n渲染执行记录：'+json.dumps(report.get('render_settings',{}),ensure_ascii=False)
        entity_fields={'shadow_settings','render_representation','appearance_scope','id','kind','label','prim_path','size','requested_size','initial_center','settled_center','final_center','current_center','declared_yaw_deg','world_transform','world_transform_convention','spatial_evidence_step','orientation_wxyz','world_aabb','support','dynamic','parameter_origin','physics','collision','appearance','geometry_parts'}
        dependency_fields={'appearance_scope','render_representation','gaussian','entity_id','kind','asset_id','asset_kind','embedded_geometry','vertices','triangles','source_frame','world_frame','source_up_axis','normalization','normalization_scale_xyz','uniform_scale','scale_mode','requested_size_limits_m','actual_size_m','source_bounds','oriented_bounds_before_scale','orientation_deg_xyz','orientation_source','source_watertight','appearance','appearance_overrides','transported_materials','transported_uvs','bound_texture_materials','texture_sampling','native_colliders_preserved','portability'}
        material_fields={'appearance_scope','entity_id','prim_path','kind','texture_id','texture_tint','uv_scale_m','color_space','normal_convention','calibration','source','roughness','metallic','applied','skipped'}
        receipt={'origin':evidence.get('origin'),'entities':[{key:value for key,value in entity.items() if key in entity_fields} for entity in evidence.get('entities',{}).values() if isinstance(entity,dict)],'asset_dependencies':[{key:value for key,value in dependency.items() if key in dependency_fields} for dependency in evidence.get('asset_dependencies',[]) if isinstance(dependency,dict)],'material_dependencies':[{key:value for key,value in dependency.items() if key in material_fields} for dependency in evidence.get('material_dependencies',[]) if isinstance(dependency,dict)],'realism':evidence.get('realism',{})}
        if strict_policy:
            # Full native receipts remain saved and are checked deterministically.
            # Repeating all material paths and primitive parts in a visual prompt
            # makes complex rooms time out without adding visible observations.
            visual_fields={'id','kind','label','size','current_center','settled_center','final_center',
                           'world_aabb','support','dynamic','orientation_wxyz','parameter_origin'}
            receipt={'origin':evidence.get('origin'),
                     'entities':[{k:v for k,v in entity.items() if k in visual_fields} for entity in evidence.get('entities',{}).values()],
                     'asset_dependencies':[{k:v for k,v in dependency.items() if k in {'entity_id','asset_id','actual_size_m','orientation_deg_xyz','render_representation','scale_mode'}}
                                           for dependency in evidence.get('asset_dependencies',[])],
                     'scope':'compact visual context; full collider, part, support and material receipts remain in capture/evidence.json and acceptance checks'}
            prompt+='\n紧凑返回：每条观察只写一个具体可见事实（约20到45个汉字），不重复摘要；不确定仍须失败。只返回规定字段，禁止长篇重述程序。'
        prompt+='\n实体与资产执行记录：'+json.dumps(receipt,ensure_ascii=False)
        geometry_path=directory/'geometry_preview.json'
        changes_path=directory/'repair_changes.json'
        if changes_path.is_file():
            changes=json.loads(changes_path.read_text())
            changes={**changes,'comparison_recorded_at':'before_capture','capture_status':report['status'],
                     'capture_token':report.get('token')}
            prompt+='\n本次程序改动对照：'+json.dumps(changes,ensure_ascii=False)
        if geometry_path.is_file() and not strict_policy:
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
        prompt+='\n实拍相机位置、朝向与图片对应：'+json.dumps([{'view':f'view_{i}.png',**c} for i,c in enumerate(program['cameras'])],ensure_ascii=False)
        prompt+='\n关系判断须区分画面坐标、世界坐标及使用者视角；左右前后按摘要明确参照判断，不得随相机换位而改变场景关系。未定义参照时指出文字歧义，不臆造世界方向。相机高度以执行位置为准，不能仅凭俯视构图判断拍摄高度。外观名称须由实际形态和材质支持，禁止把未观察到的颜色或品牌当事实。'
        prompt+='\n全部机位共同覆盖场景，不要求每张照片同时看见所有物体。单一视角遮挡不能证明物体缺失、穿插或悬空；须检查其它对应机位和原生姿态证据。全部机位仍无法辨认或验证的项目应失败并列为未解；清晰可见的缺陷必须保留，不能由程序名称替代外观。'
        prompt+='\n'+REFERENCE_GUIDANCE
        layout_reference=directory/'layout_reference.png'
        if layout_reference.is_file():
            review_images.append(layout_reference)
            prompt+='\n最后一张是扩散设计参考，其余是实际 Isaac 视图。额外返回 design_alignment:{status:"aligned"|"partial"|"diverged",issues:[string]}，比较功能分区、主要物体、材质、采光和氛围；参考仅用于设计比较，不是仿真成品、GT 或像素匹配目标。'
        review=completion(prompt,directory/'model_calls'/'scene_review',review_images,
                          10000 if strict_policy.get('require_scene_brief') else 5000,
                          bounded_review=bool(strict_policy),stop=stop,context=unit.get('run_context'))
    else: review={'acceptable':False,'issues':physical_issues or report.get('errors',[]),
                 'repair_suggestions':['Repair the actual support, attachment or layout issue in a new complete program and capture again.'],
                 'visual_review_skipped':bool(physical_issues)}
    if spatial_context is not None:review['spatial_reference_context']=spatial_context
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
    acceptance=capture_acceptance(store.root,program,report,evidence,review,capture,execution_mode)
    if acceptance.get('enforced'):
        review['production_acceptance']=acceptance
        write_json(directory/'scene_acceptance.json',acceptance)
        if acceptance.get('scene_brief'):
            write_json(directory/'scene_brief_alignment.json', {'brief': acceptance['scene_brief'],
                       'observation': review.get('brief_alignment', {}), 'passed': acceptance['passed'],
                       'iteration_required': not acceptance['passed'], 'hard_requirements_may_be_relaxed': False})
        review.setdefault('issues',[]).extend(acceptance['issues'])
    acceptance_passed = acceptance.get('passed') is not False
    passed=review.get('acceptable') is True and review['physical_stable'] and review['renderable'] and interaction_passed is not False and acceptance_passed
    review['passed']=passed
    review['publication_status']='pilot_candidate' if passed else 'exploration_requires_improvement'
    review['execution_mode']=execution_mode or 'exploration'
    review['evaluation_status']='not_evaluated' if not acceptance.get('enforced') else ('passed' if acceptance.get('passed') else 'failed')
    write_json(directory/'scene_review.json',review)
    if not passed:
        if acceptance.get('enforced'):
            # Strict production never exports exploration/failed scenes. DSH can
            # read these receipts and submit a revised, fully checked program.
            record_progress(directory,'scene_acceptance_failed',issues=review.get('issues',[]))
            store.update(task['id'],state='FAILED_FINAL',failure={'scene_review':review,'artifacts_preserved':str(directory),
                'next_action':'repair_complete_program_and_resubmit','data_exported':False},result={'directory':str(directory)})
            return
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
    if capture_only:
        record_progress(directory,'complete',scene_acceptance='passed')
        store.update(task['id'],state='SUCCEEDED',result={'operation':'capture_only','directory':str(directory),
            'report':report,'scene_review':review,'scene_quality_assessed':True,'data_exported':False},unit={**unit,'phase':'complete'})
        return
    record_progress(directory,'data_export')
    summary=produce(directory,unit['intent'].get('split','dev'),unit['intent'],stop=stop,context=unit.get('run_context'))
    record_progress(directory,'complete')
    store.update(task['id'],state='SUCCEEDED',result={'summary':summary,'directory':str(directory),'scene_review':review},unit={**unit,'phase':'complete'})


def _capture_handoff(unit):
    return _scheduler_capture_handoff(unit)


def coordinate(store,stop):
    return _coordinate(
        store,
        stop,
        plan_scene=plan_scene,
        review_scene=review_scene,
        policy_for=policy_for,
        capture_only_review=review_scene,
        capture_handoff=_capture_handoff,
        generation_tools=GenerationTools,
        generated_asset_reviewer=review_generated_asset,
        resource_wait=ResourceWait,
    )
