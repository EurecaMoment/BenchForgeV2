"""Select, review, and publish BenchForge scene questions and evidence."""
from collections import Counter
import json
import shutil
import zipfile
import uuid
import threading
from pathlib import Path
from types import SimpleNamespace
from service_access.runtime_config import environment_value
from capabilities.dataset_authoring.scene_capture.spatial_tasks import SCENE_TEMPLATE_IDS
from capabilities.dataset_authoring.scene_capture.spatial_tasks import generate_spatial
from capabilities.dataset_authoring.scene_capture.spatial_tasks import select_diverse
from capabilities.dataset_authoring.scene_capture.spatial_tasks import render
from storage.files import write_json
from service_access.openai_client import completion
from capabilities.dataset_authoring.quantity import delivery_status
from capabilities.dataset_authoring.quantity import validate_quantity_contract
from service_access.request_context import RunContext
from service_access.request_context import check_cancelled
from capabilities.scene_authoring.validation.policy import resolve_execution_mode
from capabilities.dataset_authoring.scene_capture.product_diagnostics import collection_diagnostics as _collection_diagnostics
from capabilities.dataset_authoring.scene_capture.product_packaging import capture_file as _capture_file
from capabilities.dataset_authoring.scene_capture.product_packaging import package_capture as _package_capture


_PUBLISH_LOCK=threading.Lock()


def filter_readable_candidates(pairs):
    """Keep geometry and GT untouched; require room around the center marker.

    The renderer draws radius r with a white outline. Requiring bbox extent
    2*r+6 leaves three pixels on each side of that diameter. This is a small
    marker eligibility rule, not a semantic, occlusion or realism certificate.
    """
    eligible=[];excluded={};by_source=Counter();policies={}
    for row,record in pairs:
        size=record.data['entities']['image_size']
        font_size=max(10,min(24,round(min(size['width'],size['height'])*.035)))
        radius=max(2,round(font_size/7));minimum=2*radius+6
        policies[record.record_id]={'image_size':size,'marker_radius_px':radius,'min_bbox_edge_px':minimum}
        problems=[]
        for obj in row['provenance']['objects']:
            x1,y1,x2,y2=obj['bbox']
            if min(x2-x1,y2-y1)<minimum:
                problems.append(obj['id'])
                excluded[(record.record_id,obj['id'])]={
                    'source_record':record.record_id,'object_id':obj['id'],
                    'bbox':obj['bbox'],'bbox_extent_px':[x2-x1,y2-y1],
                    'reason':'bbox_too_small_for_center_marker','min_bbox_edge_px':minimum}
        if problems:by_source[record.record_id]+=1
        else:eligible.append((row,record))
    examples=list(excluded.values())
    return eligible,{'schema':'benchforge.data-selection/v1',
        'generated_candidates':len(pairs),'eligible_candidates':len(eligible),
        'filtered_by_marker_size':len(pairs)-len(eligible),
        'filtered_candidates_by_source':dict(by_source),'marker_policy_by_source':policies,
        'excluded_object_count':len(examples),'excluded_objects':examples[:80],
        'excluded_objects_omitted':max(0,len(examples)-80),
        'policy_basis':'BenchForge marker center radius; bbox minimum = marker diameter + 6 pixels',
        'operator_guidance':'For excluded objects, inspect the capture and choose a closer or less occluded camera view if they matter to the task. No scene parameters are changed automatically.',
        'gt_modified':False,'semantic_acceptance':False,
        'limitations':['Marker size eligibility does not prove label visibility, lack of overlap, or semantic answerability.',
                       'Visual item review still applies; review decisions are model opinions, not benchmark certification.']}


def produce(directory,split='dev',intent=None,*,stop=None,context=None):
    """Commit a complete release atomically; keep partial export attempts for audit."""
    intent = intent or {}
    requested_mode = intent.get('execution_mode')
    execution_mode = resolve_execution_mode(requested_mode)
    policy_mode = (
        requested_mode
        if requested_mode is not None or environment_value('BENCHFORGE_EXECUTION_MODE') is not None
        else None
    )
    quantity_contract = validate_quantity_contract(intent.get('quantity_contract', 'best_effort'))
    check_cancelled(stop, 'product export')
    from capabilities.scene_authoring.validation.acceptance import require_accepted
    require_accepted(directory.parent.parent,directory,policy_mode)
    if split not in {'dev','train'}:raise ValueError('split must be dev or train')
    published=directory/'release'
    with _PUBLISH_LOCK:
        receipt=published/'complete.json'
        if receipt.exists():
            summary=json.loads(receipt.read_text(encoding='utf-8'))
            if summary['split']!=split:raise ValueError('Completed release split is immutable; use its original split')
            if summary['accepted']<1:raise ValueError('Existing empty release is not a usable dataset; retain it for inspection')
            return summary
        if published.exists():
            published.rename(directory/('legacy_release_'+uuid.uuid4().hex[:8]))
        attempt=directory/'product_attempts'/('export_'+uuid.uuid4().hex[:12])
        attempt.mkdir(parents=True)
        summary=_produce(
            directory,
            attempt,
            split,
            intent,
            stop=stop,
            context=context,
        )
        check_cancelled(stop, 'release finalization')
        write_json(attempt/'complete.json',summary)
        try:attempt.rename(published)
        except FileExistsError:
            if (published/'complete.json').exists():return json.loads((published/'complete.json').read_text(encoding='utf-8'))
            raise
        return summary


def _question_candidates(capture,frames,target):
    pairs=[]
    sources={f['frame_id']:capture/f['image'] for f in frames}
    for f in frames:
        record=SimpleNamespace(record_id=f['frame_id'],data={'entities':{'image_size':f['image_size'],'objects':f['objects']}})
        spec=SimpleNamespace(template_ids=SCENE_TEMPLATE_IDS,seed=29,target_items=target)
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


def _produce(directory,release,split,intent,*,stop=None,context=None):
    intent = intent or {}
    target = intent.get('target_items', 24)
    quantity_contract = validate_quantity_contract(intent.get('quantity_contract', 'best_effort'))
    execution_mode = resolve_execution_mode(intent.get('execution_mode'))
    run_context = RunContext.from_record(context)
    if type(target) is not int or not 1 <= target <= 1000:
        raise ValueError('target_items must be an integer in 1..1000')
    capture=directory/'capture';evidence=json.loads((capture/'evidence.json').read_text(encoding='utf-8'))
    pairs=_question_candidates(capture,evidence['frames'],target)
    eligible,selection=filter_readable_candidates(pairs)
    extra_budget=min(target,8);review_budget=target+extra_budget
    # One bounded diversity order avoids reusing comparison evidence across
    # replenishment batches. Reserve images are rendered only when consumed.
    pool=select_diverse(eligible,review_budget)
    selected=[];cursor=0;batch_index=0
    public=[];authority=[];reviews=[]
    def save_selection(state):
        selection.update({
            'export_attempt': release.name,
            'state': state,
            'extra_review_budget': extra_budget,
            'review_budget': review_budget,
            'unique_candidate_pool': len(pool),
            'candidates_reviewed': len(reviews),
            'replenishment_candidates_reviewed': max(0, len(reviews)-min(target, len(pool))),
            **delivery_status(len(public), target, quantity_contract),
            'reviewed_item_ids': [r['item_id'] for r in reviews],
            'rejected_item_ids': [r['item_id'] for r in reviews if r.get('valid') is not True],
            'unused_reserved_candidates': len(pool)-cursor,
        })
        write_json(release/'data_selection.json',selection)
        # Answer-free latest receipt for operator feedback; full attempts persist.
        write_json(directory/'data_selection.json',selection)
        write_json(release/'item_reviews.json',reviews)
    save_selection('reviewing')
    while len(public)<target and cursor<len(pool):
        check_cancelled(stop, 'question generation and review')
        batch_count=min(target-len(public),len(pool)-cursor)
        batch=_render_question_images(release,capture,evidence['frames'],pool[cursor:cursor+batch_count])
        cursor+=len(batch);selected.extend(batch)
        author_input=[{k:row[k] for k in ('item_id','question','options','task_contract')} for row,_ in batch]
        authored=completion('你为人类撰写空间智能题目。下面每题的实体字母、可见标注框中心、关系方向、排序/单选要求是结构化任务语义，不得改变。仅润色表达，避免冗长机械化，保留作答依据与选项语义。不要猜答案。返回JSON {"items":[{"item_id":string,"question":string}]}。'+json.dumps(author_input,ensure_ascii=False),release/'model_calls'/f'item_author_{batch_index}',max_tokens=5000,stop=stop,context=run_context)
        wording={item['item_id']:item['question'] for item in authored.get('items',[]) if isinstance(item.get('question'),str)}
        batch_index+=1
        for row,record in batch:
            check_cancelled(stop, 'question review')
            original=row['question'];row['question']=wording.get(row['item_id'],original)
            prompt='你是独立审题者。只依据给出的图片判断下面题目是否目标明确、标记对应正确、可以从图片作答、表达自然，同时检查改写是否保持原始题目语义（对象、方向、中心点定义、排序/单选）。不要给答案或改变GT。返回JSON {"valid":boolean,"issues":[string],"quality":1到5}。原始语义题目：'+original+'。待审题目：'+json.dumps({k:row[k] for k in ('question','options','answer_type')},ensure_ascii=False)
            review=completion(prompt,release/'model_calls'/f'item_review_{len(reviews)}',[row['image']],2048,stop=stop,context=run_context)
            reviews.append({**review,'item_id':row['item_id']})
            if review.get('valid') is True:
                item={k:row[k] for k in ('item_id','template_id','question','options','answer_type','task_contract','scoring')}
                media=release/'images';media.mkdir(exist_ok=True)
                shutil.copy2(row['image'],media/Path(row['image']).name)
                item['image']='images/'+Path(row['image']).name;item['split']=split
                public.append(item)
                authority.append({'item_id':row['item_id'],'answer':row['answer'],'derivation':row['derivation'],'evidence':row['provenance'],'truth_domain':'synthetic_world','GT_writer':'benchforge_backend.spatial_tasks.generate_spatial'})
            save_selection('reviewing')
    check_cancelled(stop, 'release assembly')
    save_selection('target_reached' if len(public)>=target else ('review_budget_exhausted' if len(reviews)>=review_budget else 'candidate_pool_exhausted'))
    write_json(release/'model_bundle.json',public);write_json(release/'authority_bundle.json',authority)
    write_json(release/'item_reviews.json',reviews)
    if split=='train':
        answers={a['item_id']:a['answer'] for a in authority}
        with (release/'sft.jsonl').open('w',encoding='utf8') as out:
            for p in public:out.write(json.dumps({'messages':[{'role':'user','content':p['question']+' '+json.dumps(p['options'],ensure_ascii=False)},{'role':'assistant','content':json.dumps(answers[p['item_id']],ensure_ascii=False)}],'images':[p['image']],'source_item_id':p['item_id']},ensure_ascii=False)+'\n')
    summary={'candidates_reviewed':len(selected),'templates':sorted({p['template_id'] for p in public}),'frames':len(evidence['frames']),'split':split,'purpose':'training_sft' if split=='train' else 'development_benchmark','robot_trajectories':False,'quality_grade':'pilot','source':'native_isaac','scene_family':intent.get('scene_family',directory.parent.name),'harness_reused':'spatial_tasks.generate_spatial/select_diverse/render','all_items_semantically_reviewed':True}
    summary.update(delivery_status(len(public), target, quantity_contract))
    summary['execution_mode'] = execution_mode
    summary['run_context'] = run_context.to_dict() if run_context else None
    summary.update(collection_review_performed=False, collection_diagnostics_performed=True,
                   human_approved=False, benchmark_approved=False,
                   gt_modified_by_reviewer=False,
                   publication_status='pilot_candidate' if public else 'empty_candidate')
    summary['evaluation_status'] = (
        'not_evaluated'
        if execution_mode == 'exploration'
        else 'passed'
    )
    summary['collection_diagnostics']=_collection_diagnostics(public,authority,evidence,pairs,selected,target,summary['scene_family'])
    summary['data_selection']=selection
    scene_review=directory/'scene_review.json'
    if (directory/'layout_reference.json').is_file():summary['layout_guidance']=json.loads((directory/'layout_reference.json').read_text(encoding='utf-8'))
    if scene_review.is_file():
        reviewed_scene=json.loads(scene_review.read_text(encoding='utf-8'))
        summary['scene_quality_passed']=reviewed_scene.get('passed') is True
        summary['visual_realism']=reviewed_scene.get('visual_realism',{'status':'not_assessed','basis':'no_separate_realism_review'})
        if public:
            summary['publication_status']=reviewed_scene.get('publication_status','exploration_requires_improvement')
    if public:
        summary.update(_package_capture(directory,release,evidence,stop=stop))
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
