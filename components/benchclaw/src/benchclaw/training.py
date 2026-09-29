"""Training release branch: supervised examples with program-derived labels.

Shares acquisition, annotation, synthesis, critique and replay gates with evaluation.
Uses the same release DB for durable status, but never creates a model evaluation.
"""
import json
import os
import shutil
from pathlib import Path
from sqlalchemy import select,update
from .domain import HarnessError,ModelEvidence,now,uid
from .metadata import releases
from .release import final_bundle,validate_run
from .store import safe_path,write_json,write_jsonl


def supervised_rows(bundle):
    assets={a.uri:a for a in bundle.assets};answers={a.item_id:a for a in bundle.answers}
    rows=[]
    for item in bundle.visible:
        if any(assets[p].split!='train' for p in item.media_refs):
            raise HarnessError('TRAINING_SPLIT','Only explicitly train-assigned sources can enter SFT')
        answer=answers[item.item_id]
        text=answer.gold if isinstance(answer.gold,str) else json.dumps(answer.gold,ensure_ascii=False)
        choices=item.choices
        options='\n'.join(f'{k}: {v}' for k,v in choices.items()) if isinstance(choices,dict) else ''
        hints={'single_choice':'请只输出选项字母。','interval':'请只输出选项字母。','multi_choice':'请输出选项字母的 JSON 数组。',
            'ordering':'请按要求输出选项字母的 JSON 数组。','numeric':'请只输出数值。','json':'请输出 JSON。','text':'请输出简短答案。'}
        english={'single_choice':'Reply with one choice letter.','interval':'Reply with one choice letter.','multi_choice':'Reply with a JSON array of choice letters.',
            'ordering':'Reply with an ordered JSON array.','numeric':'Reply with a number.','json':'Reply with JSON.','text':'Reply with a short answer.'}
        hint=(hints if item.public_metadata.language=='zh-CN' else english)[item.answer_type]
        prompt='\n'.join(x for x in ['<image>\n'*len(item.media_refs),item.prompt,options,hint] if x)
        rows.append({'id':item.item_id,'messages':[{'role':'user','content':prompt},{'role':'assistant','content':text}],
            'images':item.media_refs})
    return rows


def build_training_release(repo,store,run_id):
    bundle,spec,directory,run=final_bundle(repo,store,run_id)
    if spec.purpose!='training':raise HarnessError('TRAINING_PURPOSE','Evaluation runs cannot be exported as training data')
    if not spec.semantic_review:raise HarnessError('TRAINING_REVIEW_REQUIRED','Training examples require content review')
    if any(a.split!='train' for a in bundle.assets):raise HarnessError('TRAINING_SPLIT','All training source assets must be train assigned')
    if any(isinstance(e,ModelEvidence) for e in bundle.evidence):raise HarnessError('GT_DERIVATION_REQUIRED','No model-written supervision')
    report=validate_run(repo,store,run_id)
    if not report['passed']:raise HarnessError('TRAINING_GATE_FAILED',json.dumps(report['issues'],ensure_ascii=False))
    rows=supervised_rows(bundle)
    if not rows:raise HarnessError('TRAINING_EMPTY','No accepted training samples')
    with repo.transaction() as conn:
        old=conn.execute(select(releases).where(releases.c.run_id==run_id).with_for_update()).mappings().first()
        if old and old['state']=='TRAINING_DEVELOPMENT':return old['record']
        rid=old['id'] if old else uid('training')
        if not old:conn.execute(releases.insert().values(id=rid,run_id=run_id,state='TRAINING_PREPARING',record={}))
        repo.event(conn,run_id,None,'training.preparing',{'release_id':rid})
    root=safe_path(store.root,'training/'+rid);root.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (root/'builder.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with repo.engine.connect() as conn:
            existing=conn.execute(select(releases).where(releases.c.id==rid)).mappings().one()
            if existing['state']=='TRAINING_DEVELOPMENT':return existing['record']
        build=root/uid('build');build.mkdir()
        for entry in [*bundle.assets,*bundle.files]:
            dest=safe_path(build,entry.uri);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(safe_path(directory,entry.uri,True),dest)
        write_jsonl(build/'train.jsonl',rows)
        write_jsonl(build/'supervision.jsonl',[a.model_dump(mode='json') for a in bundle.answers])
        write_json(build/'provenance.json',bundle.model_dump(mode='json'))
        write_json(build/'quality_report.json',report)
        review=json.loads((build/'review/manifest.json').read_text())
        record={'release_id':rid,'run_id':run_id,'created_at':now(),'purpose':'training','status':'TRAINING_DEVELOPMENT',
            'format':'messages-images-sft/v1','item_count':len(rows),'training_bundle_uri':str(root/'training_bundle'),
            'gt_authority':'annotation_simulator_or_official_derivation','model_generated_gt':False,
            'candidate_count':review['candidate_count'],'requires_upstream_repair_count':review['requires_upstream_repair_count'],
            'source_scene_ids':sorted({a.scene_id for a in bundle.assets}),'source_uris':sorted({r.source_uri for r in bundle.records}),
            'quality_scope':'content-screened development data; annotation accuracy and training effect not certified'}
        if spec.collection_policy:
            collection=json.loads((build/'collection/manifest.json').read_text())
            record['collection_acceptance']={'accepted':collection['accepted'],'statistics':collection['statistics'],
                'policy':collection['policy'],'limitations':collection['verdict']['limitations'],'human_approved':False}
        write_json(build/'manifest.json',record)
        (build/'README.md').write_text('Training samples: train.jsonl (messages + images, paths relative to this directory).\n'
            'Assistant labels come from supervision.jsonl and replayable source derivation, never reviewer answers.\n'
            'This bundle includes labels and must not be used as a blind evaluation set.\n'
            'The trainer should resolve image paths against this directory. No model training was performed by this export.\n',encoding='utf-8')
        dest=root/'training_bundle'
        if dest.exists():os.rename(dest,root/uid('interrupted'))
        os.rename(build,dest)
        with repo.transaction() as conn:
            conn.execute(update(releases).where(releases.c.id==rid).values(state='TRAINING_DEVELOPMENT',record=record))
            repo.event(conn,run_id,None,'training.exported',{'release_id':rid,'items':len(rows)})
        return record
