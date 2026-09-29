"""Directly reuses BenchClaw spatial-v2 GT, marking and diverse candidate selection."""
import json
import shutil
import zipfile
import uuid
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from benchclaw.spatial_tasks import generate_spatial, select_diverse, render
from benchclaw.store import write_json
from .model import completion
from .data_selection import filter_readable_candidates


_PUBLISH_LOCK=threading.Lock()


def _collection_diagnostics(public, authority, evidence, candidates, selected, target, scene_family):
    """Reuse Harness arithmetic, with observational policy and original source-frame identity.

    The scene route has no declared collection acceptance contract. Its inherited
    defaults are diagnostic reference points, never new publication thresholds.
    """
    from benchclaw.collection_review import collection_statistics, policy_violations
    from benchclaw.domain import CollectionPolicy
    frames={frame['frame_id']:frame for frame in evidence['frames']}
    if len(frames)!=len(evidence['frames']):raise ValueError('Duplicate source frame IDs')
    public_ids=[row['item_id'] for row in public];authority_ids=[row['item_id'] for row in authority]
    if len(set(public_ids))!=len(public_ids) or len(set(authority_ids))!=len(authority_ids) or set(public_ids)!=set(authority_ids):
        raise ValueError('Collection item/authority IDs must be unique and match')
    selected_ids={row['item_id'] for row,_ in selected}
    if not set(public_ids)<=selected_ids:raise ValueError('Accepted item is absent from selected candidates')
    answers={row['item_id']:row for row in authority}
    visible_rows=[];answer_rows=[];evidence_rows=[]
    for item in public:
        contract=item['task_contract'];source=contract['source_record']
        if source not in frames:raise ValueError('Collection item refers to an unknown source frame')
        original_objects={obj['object_id'] for obj in frames[source]['objects']}
        if not set(contract['objects'])<=original_objects:raise ValueError('Collection item refers to an unknown source object')
        iid=item['item_id'];eid='ev_'+iid
        visible_rows.append(SimpleNamespace(item_id=iid,prompt=item['question'],choices=item['options'],answer_type=item['answer_type']))
        answer_rows.append(SimpleNamespace(item_id=iid,gold=answers[iid]['answer'],template_id=item['template_id'],evidence_refs=[eid]))
        # Count original capture RGB, not a different question overlay per item.
        evidence_rows.append(SimpleNamespace(evidence_id=eid,source_refs=[source],asset_refs=[frames[source]['image']],fields={'task_contract':contract}))
    bundle=SimpleNamespace(visible=visible_rows,answers=answer_rows,evidence=evidence_rows)
    stats=collection_statistics(bundle)
    policy=CollectionPolicy()
    reference=policy.model_dump(include={'min_items','min_source_records','max_majority_baseline','baseline_min_items','required_templates'})
    findings=policy_violations(stats,policy)
    candidate_sources={record.record_id for _,record in candidates}
    selected_sources={record.record_id for _,record in selected}
    accepted_sources=set(stats['items_by_source'])
    available_sources=set(frames)
    if not (candidate_sources|selected_sources)<=available_sources:raise ValueError('Candidate source frame is absent from capture evidence')
    shortfall=max(0,target-len(public))
    if shortfall:findings.append(f'accepted item shortfall {shortfall} relative to requested target {target}')
    if available_sources-accepted_sources:findings.append('captured frames without accepted items: '+','.join(sorted(available_sources-accepted_sources)))
    return {'schema':'spatialforge.collection-diagnostics/v1',
            'implementation':'benchclaw.collection_review.collection_statistics/policy_violations',
            'mode':'record_only','collection_acceptance':'not_assessed',
            'reference_policy':reference,'reference_policy_source':'inherited CollectionPolicy defaults; observational only',
            'statistics':stats,'findings':findings,
            'scope':{'scene_family':scene_family,'scene_families':1,
                     'source_record_unit':'one captured camera frame; multiple frames do not establish cross-scene coverage',
                     'captured_frames':len(frames),'captured_images':len({f['image'] for f in frames.values()}),
                     'candidate_source_frames':sorted(candidate_sources),'selected_source_frames':sorted(selected_sources),
                     'accepted_source_frames':sorted(accepted_sources),'unused_source_frames':sorted(available_sources-accepted_sources),
                     'accepted_frame_coverage':len(accepted_sources)/len(frames) if frames else 0},
            'selection':{'generated_candidates':len(candidates),'selected_candidates':len(selected),
                         'filtered_by_item_review':len(selected)-len(public),'target_items':target,'shortfall':shortfall,
                         'candidate_templates':dict(Counter(row['template_id'] for row,_ in candidates)),
                         'selected_templates':dict(Counter(row['template_id'] for row,_ in selected))},
            'human_approved':False,'benchmark_approved':False,'gt_modified':False,
            'limitations':['Observations do not certify collection quality or enforce answer balancing.',
                           'Majority values are in-sample constant-answer diagnostics, not no-image model evaluations.',
                           'Repeated comparison evidence means the same source frame, relation family and object set; repeated wording alone is not a duplicate.',
                           'One scene family cannot establish cross-scene generalization; no corpus-wide split or duplicate audit was performed.']}


def _capture_file(capture, relative):
    path=capture/relative
    if not relative or Path(relative).is_absolute() or not path.resolve().is_relative_to(capture.resolve()):
        raise ValueError('Invalid capture evidence reference: '+str(relative))
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('Missing capture evidence: '+str(relative))
    return path


def _package_capture(directory, release, evidence):
    """Package only recorded scene/action files; keep installed USD dependencies explicit."""
    capture=directory/'capture';result={}
    interaction=evidence.get('interaction',{})
    actions=interaction.get('action_results',[])
    if actions:
        files={}
        for action in actions:
            for key in ('trajectory_file','before_image','after_image'):
                if action.get(key):files[action[key]]=_capture_file(capture,action[key])
            if action.get('success') is True and not all(action.get(k) for k in ('trajectory_file','before_image','after_image')):
                raise ValueError('Successful interaction lacks trajectory or before/after image evidence')
        with zipfile.ZipFile(release/'interaction_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('interaction.json',json.dumps(interaction,ensure_ascii=False,indent=2))
            for relative,path in files.items():archive.write(path,relative)
        result.update(interaction_bundle='interaction_bundle.zip',interaction_validated=interaction.get('validated') is True)
    if (capture/'scene.usda').is_file():
        files={name:_capture_file(capture,name) for name in ('scene.usda','evidence.json','report.json')}
        report=json.loads(files['report.json'].read_text())
        if report.get('scene_format')=='usdc':files['scene.usdc']=_capture_file(capture,'scene.usdc')
        for resource in report.get('scene_resources',[]):
            relative=resource['file'];files[relative]=_capture_file(capture,relative)
        files['program.json']=_capture_file(directory,'program.json')
        if (directory/'scene_review.json').is_file():files['scene_review.json']=directory/'scene_review.json'
        if (directory/'layout_reference.json').is_file():
            files['layout_reference.json']=_capture_file(directory,'layout_reference.json')
            files['layout_reference.png']=_capture_file(directory,'layout_reference.png')
        for frame in evidence['frames']:
            relative=frame['image'];files[relative]=_capture_file(capture,relative)
            stem=Path(relative).with_suffix('')
            for suffix in ('.json','_depth.npy','_semantic.npy','_instance.npy'):
                relative=stem.as_posix()+suffix
                files[relative]=_capture_file(capture,relative)
        dependencies={'asset_dependencies':evidence.get('asset_dependencies',[]),
                      'material_dependencies':evidence.get('material_dependencies',[]),
                      'environment_dependencies':evidence.get('environment_dependencies',[]),
                      'space_dependencies':evidence.get('space_dependencies',[]),
                      'scene_resources':report.get('scene_resources',[]),
                      'scene_resources_unresolved':report.get('scene_resources_unresolved',[]),
                      'scene_resource_scope':report.get('scene_resource_scope'),
                      'self_contained':False,'dependency_resolution_verified':False,
                      'limitations':['Native USD references and material modules can require the original Isaac asset installation paths.',
                                     'This package preserves captured files; it does not copy the installed asset library or rewrite USD references.']}
        with zipfile.ZipFile(release/'scene_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for relative,path in files.items():archive.write(path,relative)
            archive.writestr('dependencies.json',json.dumps(dependencies,ensure_ascii=False,indent=2))
            archive.writestr('README.txt','Open scene.usda in Isaac Sim with the original native asset and material installation available.\n'
                            'Images listed in scene_resources were copied beside the scene and use relative paths in the exported root layer.\n'
                            'Consult dependencies.json for recorded dependencies. This is not a self-contained portable USD package.\n'
                            'program.json is the scene request; evidence/report/views are captured results. Interaction traces are in the separate interaction bundle.\n')
        result.update(scene_bundle='scene_bundle.zip',scene_self_contained=False)
    return result


def produce(directory,split='dev',intent=None):
    """Commit a complete release atomically; keep partial export attempts for audit."""
    if split not in {'dev','train'}:raise ValueError('split must be dev or train')
    published=directory/'release'
    with _PUBLISH_LOCK:
        receipt=published/'complete.json'
        if receipt.exists():
            summary=json.loads(receipt.read_text())
            if summary['split']!=split:raise ValueError('Completed release split is immutable; use its original split')
            if summary['accepted']<1:raise ValueError('Existing empty release is not a usable dataset; retain it for inspection')
            return summary
        if published.exists():
            published.rename(directory/('legacy_release_'+uuid.uuid4().hex[:8]))
        attempt=directory/'product_attempts'/('export_'+uuid.uuid4().hex[:12])
        attempt.mkdir(parents=True)
        summary=_produce(directory,attempt,split,intent)
        write_json(attempt/'complete.json',summary)
        try:attempt.rename(published)
        except FileExistsError:
            if (published/'complete.json').exists():return json.loads((published/'complete.json').read_text())
            raise
        return summary


def _question_candidates(capture,frames,target):
    pairs=[]
    sources={f['frame_id']:capture/f['image'] for f in frames}
    for f in frames:
        record=SimpleNamespace(record_id=f['frame_id'],data={'entities':{'image_size':f['image_size'],'objects':f['objects']},'range_verified':False})
        spec=SimpleNamespace(template_ids=['T021','T022','T023','T024','T025','T034','T035'],seed=29,target_items=target)
        for row in generate_spatial(record,sources[record.record_id],spec,output=None):pairs.append((row,record))
    return pairs


def _render_question_images(directory,capture,frames,pairs):
    sources={f['frame_id']:capture/f['image'] for f in frames}
    selected=[]
    for row,record in pairs:
        path=directory/'question_images'/record.record_id/(row['item_id']+'.png')
        render(sources[record.record_id],row['provenance']['objects'],path)
        # Keep candidate records intact for diagnostics; only the selected copy
        # gets a materialized image path and later human-facing wording.
        selected.append(({**row,'image':str(path)},record))
    return selected


def _select_question_images(directory,capture,frames,target):
    """Select eligible unchanged candidates before writing question overlays."""
    pairs=_question_candidates(capture,frames,target)
    eligible,_=filter_readable_candidates(pairs)
    selected=_render_question_images(directory,capture,frames,select_diverse(eligible,target))
    return pairs,selected


def _produce(directory,release,split,intent):
    intent=intent or {};target=intent.get('target_items',24)
    capture=directory/'capture';evidence=json.loads((capture/'evidence.json').read_text())
    pairs=_question_candidates(capture,evidence['frames'],target)
    eligible,selection=filter_readable_candidates(pairs)
    extra_budget=min(target,8);review_budget=target+extra_budget
    # One bounded diversity order avoids reusing comparison evidence across
    # replenishment batches. Reserve images are rendered only when consumed.
    pool=select_diverse(eligible,review_budget)
    selected=[];cursor=0;batch_index=0
    public=[];authority=[];reviews=[]
    def save_selection(state):
        selection.update(export_attempt=release.name,state=state,target_items=target,
            extra_review_budget=extra_budget,review_budget=review_budget,unique_candidate_pool=len(pool),
            candidates_reviewed=len(reviews),replenishment_candidates_reviewed=max(0,len(reviews)-min(target,len(pool))),
            accepted=len(public),shortfall=max(0,target-len(public)),
            reviewed_item_ids=[r['item_id'] for r in reviews],
            rejected_item_ids=[r['item_id'] for r in reviews if r.get('valid') is not True],
            unused_reserved_candidates=len(pool)-cursor)
        write_json(release/'data_selection.json',selection)
        # Answer-free latest receipt for operator feedback; full attempts persist.
        write_json(directory/'data_selection.json',selection)
        write_json(release/'item_reviews.json',reviews)
    save_selection('reviewing')
    while len(public)<target and cursor<len(pool):
        batch_count=min(target-len(public),len(pool)-cursor)
        batch=_render_question_images(release,capture,evidence['frames'],pool[cursor:cursor+batch_count])
        cursor+=len(batch);selected.extend(batch)
        author_input=[{k:row[k] for k in ('item_id','question','options','task_contract')} for row,_ in batch]
        authored=completion('你为人类撰写空间智能题目。下面每题的实体字母、可见标注框中心、关系方向、排序/单选要求是结构化任务语义，不得改变。仅润色表达，避免冗长机械化，保留作答依据与选项语义。不要猜答案。返回JSON {"items":[{"item_id":string,"question":string}]}。'+json.dumps(author_input,ensure_ascii=False),release/'model_calls'/f'item_author_{batch_index}',max_tokens=5000)
        wording={item['item_id']:item['question'] for item in authored.get('items',[]) if isinstance(item.get('question'),str)}
        batch_index+=1
        for row,record in batch:
            original=row['question'];row['question']=wording.get(row['item_id'],original)
            prompt='你是独立审题者。只依据给出的图片判断下面题目是否目标明确、标记对应正确、可以从图片作答、表达自然，同时检查改写是否保持原始题目语义（对象、方向、中心点定义、排序/单选）。不要给答案或改变GT。返回JSON {"valid":boolean,"issues":[string],"quality":1到5}。原始语义题目：'+original+'。待审题目：'+json.dumps({k:row[k] for k in ('question','options','answer_type')},ensure_ascii=False)
            review=completion(prompt,release/'model_calls'/f'item_review_{len(reviews)}',[row['image']],2048)
            reviews.append({**review,'item_id':row['item_id']})
            if review.get('valid') is True:
                item={k:row[k] for k in ('item_id','template_id','question','options','answer_type','task_contract','scoring')}
                media=release/'images';media.mkdir(exist_ok=True)
                shutil.copy2(row['image'],media/Path(row['image']).name)
                item['image']='images/'+Path(row['image']).name;item['split']=split
                public.append(item)
                authority.append({'item_id':row['item_id'],'answer':row['answer'],'derivation':row['derivation'],'evidence':row['provenance'],'truth_domain':'synthetic_world','GT_writer':'benchclaw.spatial_tasks.generate_spatial'})
            save_selection('reviewing')
    save_selection('target_reached' if len(public)>=target else ('review_budget_exhausted' if len(reviews)>=review_budget else 'candidate_pool_exhausted'))
    write_json(release/'model_bundle.json',public);write_json(release/'authority_bundle.json',authority)
    write_json(release/'item_reviews.json',reviews)
    if split=='train':
        answers={a['item_id']:a['answer'] for a in authority}
        with (release/'sft.jsonl').open('w',encoding='utf8') as out:
            for p in public:out.write(json.dumps({'messages':[{'role':'user','content':p['question']+' '+json.dumps(p['options'],ensure_ascii=False)},{'role':'assistant','content':json.dumps(answers[p['item_id']],ensure_ascii=False)}],'images':[p['image']],'source_item_id':p['item_id']},ensure_ascii=False)+'\n')
    summary={'accepted':len(public),'target_items':target,'candidates_reviewed':len(selected),'shortfall':max(0,target-len(public)),'templates':sorted({p['template_id'] for p in public}),'frames':len(evidence['frames']),'split':split,'purpose':'training_sft' if split=='train' else 'development_benchmark','robot_trajectories':False,'quality_grade':'pilot','source':'native_isaac','scene_family':intent.get('scene_family',directory.parent.name),'harness_reused':'spatial_tasks.generate_spatial/select_diverse/render','all_items_semantically_reviewed':True}
    summary.update(target_reached=len(public)>=target, collection_review_performed=False,
                   collection_diagnostics_performed=True,
                   human_approved=False, benchmark_approved=False,
                   gt_modified_by_reviewer=False,
                   publication_status='pilot_candidate' if public else 'empty_candidate')
    summary['collection_diagnostics']=_collection_diagnostics(public,authority,evidence,pairs,selected,target,summary['scene_family'])
    summary['data_selection']=selection
    scene_review=directory/'scene_review.json'
    if (directory/'layout_reference.json').is_file():summary['layout_guidance']=json.loads((directory/'layout_reference.json').read_text())
    if scene_review.is_file():
        reviewed_scene=json.loads(scene_review.read_text())
        summary['scene_quality_passed']=reviewed_scene.get('passed') is True
        summary['visual_realism']=reviewed_scene.get('visual_realism',{'status':'not_assessed','basis':'no_separate_realism_review'})
        if public:
            summary['publication_status']=reviewed_scene.get('publication_status','exploration_requires_improvement')
    if public:summary.update(_package_capture(directory,release,evidence))
    write_json(release/'collection_report.json',summary)
    if not public:
        raise ValueError('No accepted items; candidate files and reviews retained in '+str(release))
    with zipfile.ZipFile(release/'model_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(release/'model_bundle.json','model_bundle.json')
        for p in (release/'images').glob('*.png') if (release/'images').exists() else []:archive.write(p,p.relative_to(release))
    with zipfile.ZipFile(release/'authority_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('authority_bundle.json','collection_report.json','item_reviews.json','data_selection.json'):archive.write(release/name,name)
    if split=='train':
        with zipfile.ZipFile(release/'training_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
            archive.write(release/'sft.jsonl','sft.jsonl')
            for p in (release/'images').glob('*.png') if (release/'images').exists() else []:archive.write(p,p.relative_to(release))
    return summary
