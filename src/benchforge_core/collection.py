"""Bounded collection quality diagnostics; no content hashing or model review."""
import json
from collections import Counter,defaultdict
from .artifacts import write,unique


def assess(items,policy=None):
    policy=policy or {};unique([{**r,'id':r.get('item_id',r.get('id'))} for r in items])
    templates=defaultdict(list);sources=Counter();media=Counter();answers=Counter();duplicates=[];seen=set();invalid=[]
    for row in items:
        tid=row.get('template_id','unknown');templates[tid].append(row)
        sources[row.get('source',row.get('source_name','unknown'))]+=1
        paths=row.get('source_media',row.get('media',[]));media.update(paths)
        answers[json.dumps(row['answer'],sort_keys=True,ensure_ascii=False)]+=1
        signature=(tid,row['question'],tuple(row.get('evidence_refs',[])))
        if signature in seen:duplicates.append(row.get('item_id',row.get('id')))
        seen.add(signature)
        proof=row.get('answerability_proof',{})
        if not proof.get('visible_media') or not proof.get('question_references_visible_anchor') or not proof.get('why_visible_anchor_is_sufficient'):
            invalid.append(row.get('item_id',row.get('id')))
    majority={tid:max(Counter(json.dumps(r['answer'],sort_keys=True) for r in rows).values())/len(rows) for tid,rows in templates.items()}
    failures=[]
    if invalid:failures.append('missing_visible_anchor_contract')
    if duplicates and policy.get('reject_duplicate_evidence_questions',True):failures.append('duplicate_evidence_questions')
    if policy.get('min_sources',0)>len(sources):failures.append('insufficient_sources')
    if policy.get('min_unique_media',0)>len(media):failures.append('insufficient_unique_media')
    if policy.get('max_items_per_source_media') and max(media.values(),default=0)>policy['max_items_per_source_media']:failures.append('media_reuse_limit')
    if policy.get('max_template_majority') and max(majority.values(),default=0)>policy['max_template_majority']:failures.append('constant_answer_shortcut')
    return {'items':len(items),'sources':dict(sources),'unique_media':len(media),'max_media_reuse':max(media.values(),default=0),
        'answers':dict(answers),'template_majority_baseline':majority,'duplicate_items':duplicates,'invalid_anchor_contracts':invalid,
        'failures':failures,'status':'fail' if failures else 'pass','policy':policy,
        'limits':'Path/record-based collection checks only. No content hashes, semantic model review or empirical difficulty claim.'}
