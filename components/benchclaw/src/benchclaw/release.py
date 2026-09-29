from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from sqlalchemy import select, update

from .domain import ArtifactRef, Bundle, DatasetSpec, HarnessError, uid, now
from .gates import require_valid, validate_bundle
from .metadata import releases, visible_items, answers
from .store import safe_path, write_json, write_jsonl


def final_bundle(repo,store,run_id):
    run=repo.status(run_id)
    if run['state']!='SUCCEEDED':
        raise HarnessError('RUN_NOT_COMPLETE',f'Cannot release run in {run["state"]}')
    task=next(t for t in run['tasks'] if t['task_id']=='validate')
    ref=ArtifactRef.model_validate(task['artifact'])
    directory=store.verify(ref)
    bundle=Bundle.model_validate(task['result']['bundle'])
    spec=DatasetSpec.model_validate(run['plan']['spec'])
    return bundle,spec,directory,run


def validate_run(repo,store,run_id,policy=None):
    bundle,spec,directory,_=final_bundle(repo,store,run_id)
    if policy:
        spec=DatasetSpec.model_validate({**spec.model_dump(),'quality_policy':policy})
    issues=validate_bundle(bundle,spec,lambda uri:safe_path(directory,uri,True))
    return {'run_id':run_id,'policy':spec.quality_policy,'full_scan':True,'media_checked':len(bundle.assets),
            'items_checked':len(bundle.visible),'passed':not any(i.severity in {'error','fatal'} for i in issues),
            'issues':[i.model_dump() for i in issues]}


def build_release(repo,store,run_id):
    bundle,spec,directory,run=final_bundle(repo,store,run_id)
    if spec.purpose!='evaluation':raise HarnessError('RELEASE_PURPOSE','Use training export for training runs')
    report=validate_run(repo,store,run_id)
    if not report['passed']:
        raise HarnessError('RELEASE_GATE_FAILED',json.dumps(report['issues'],ensure_ascii=False))
    with repo.transaction() as conn:
        existing=conn.execute(select(releases).where(releases.c.run_id==run_id).with_for_update()).mappings().first()
        if existing:
            if existing['state'] in {'PUBLISHED','DEVELOPMENT'}:
                return existing['record']
            release_id=existing['id']
        else:
            release_id=uid('release')
            conn.execute(releases.insert().values(id=release_id,run_id=run_id,state='PREPARING',record={}))
            repo.event(conn,run_id,None,'release.preparing',{'release_id':release_id})
    root=safe_path(store.root,f'releases/{release_id}')
    root.mkdir(parents=True,exist_ok=True)
    # Process-level lock prevents two writers from rebuilding the same release.
    import fcntl
    with (root/'builder.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with repo.engine.connect() as conn:
            state=conn.execute(select(releases).where(releases.c.id==release_id)).mappings().one()
            if state['state'] in {'PUBLISHED','DEVELOPMENT'}:
                return state['record']
        build=root/uid('build')
        model,authority=build/'model_bundle',build/'authority_bundle'
        (model/'media').mkdir(parents=True)
        authority.mkdir(mode=0o700)
        split_rows={}
        media={a.uri:a for a in bundle.assets}
        uri_map={}
        visible=[]
        # Only explicit visible media enters this bundle. Original names and EXIF are removed.
        from PIL import Image
        for item in bundle.visible:
            refs=[]
            for uri in item.media_refs:
                if uri not in uri_map:
                    relative=f'media/{uid("media")}.png'
                    with Image.open(safe_path(directory,uri,True)) as image:
                        clean=Image.new('RGB',image.size)
                        clean.paste(image.convert('RGB'))
                        clean.save(model/relative)
                    uri_map[uri]=relative
                refs.append(uri_map[uri])
            row=item.model_copy(update={'media_refs':refs})
            visible.append(row)
            splits={media[uri].split for uri in item.media_refs}
            if len(splits)!=1:
                raise HarnessError('ITEM_SPLIT_CONFLICT',item.item_id)
            split_rows.setdefault(next(iter(splits)),[]).append(row.model_dump(mode='json'))
        for split,rows in split_rows.items():
            write_jsonl(model/f'data/{split}.jsonl',rows)
        write_json(model/'manifest.json',{'contract_version':'benchclaw.model-bundle/v1','release_id':release_id,
                                         'item_count':len(visible),'splits':{k:len(v) for k,v in split_rows.items()}})
        (model/'README.md').write_text('Model-visible questions and RGB only. Load data/*.jsonl; media_refs are relative to this directory.\n',encoding='utf-8')
        write_jsonl(authority/'answers.jsonl',[a.model_dump(mode='json') for a in bundle.answers])
        write_jsonl(authority/'evidence.jsonl',[a.model_dump(mode='json') for a in bundle.evidence])
        write_jsonl(authority/'annotations.jsonl',[a.model_dump(mode='json') for a in bundle.annotations])
        write_json(authority/'bundle.json',bundle.model_dump(mode='json'))
        # The authority bundle is independently inspectable, including source RGB
        # and overlays used to derive every answer, not dangling store-relative refs.
        for asset in bundle.assets:
            target=safe_path(authority,asset.uri)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(safe_path(directory,asset.uri,True),target)
        for file in bundle.files:
            target=safe_path(authority,file.uri);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(safe_path(directory,file.uri,True),target)
        write_jsonl(authority/'source_records.jsonl',[r.model_dump(mode='json') for r in bundle.records])
        write_jsonl(authority/'files_index.jsonl',[r.model_dump(mode='json') for r in bundle.files])
        for name in ('metrics.py','score_package.py'):
            shutil.copyfile(Path(__file__).with_name(name),authority/name)
        write_json(authority/'quality_report.json',report)
        from .analysis import export_kinship
        write_json(authority/'kinship_summary.json',export_kinship(bundle,authority/'kinship'))
        write_json(authority/'lineage.json',{'run_id':run_id,'spec':spec.model_dump(mode='json'),
                                          'artifacts':[t['artifact'] for t in run['tasks']], 'events':repo.logs(run_id)})
        production=spec.quality_policy=='production-v1'
        status='PUBLISHED' if production else 'DEVELOPMENT'
        record={'release_id':release_id,'run_id':run_id,'created_at':now(),'status':status,
                'visible_bundle_uri':str(root/'model_bundle'),'authority_bundle_uri':str(root/'authority_bundle'),
                'item_count':len(visible),'split_statistics':{k:len(v) for k,v in split_rows.items()},
                'gate_policy_version':spec.quality_policy,'quality_report_uri':str(root/'authority_bundle/quality_report.json')}
        if spec.semantic_review:
            review=json.loads((authority/'review/manifest.json').read_text())
            record['content_review']={'policy':review['policy'],'candidate_items':spec.target_items,
                'accepted_items':len(visible),'discarded_items':spec.target_items-len(visible),'human_approved':False,
                'reviewed_items':review['reviewed_count'],'not_selected_items':review['not_selected_count'],
                'requires_upstream_repair_items':review['requires_upstream_repair_count'],'rejected_items':review['rejected_count'],
                'gt_authority':'original_source_derivation','gt_modified_by_reviewer':False,
                'report_uri':str(root/'authority_bundle/review/manifest.json')}
        if spec.collection_policy:
            collection=json.loads((authority/'collection/manifest.json').read_text())
            record['collection_acceptance']={'policy':collection['policy'],'accepted':collection['accepted'],
                'statistics':collection['statistics'],'limitations':collection['verdict']['limitations'],
                'human_approved':False,'report_uri':str(root/'authority_bundle/collection/manifest.json')}
        (authority/'DATASET_CARD.md').write_text(
            f'# {spec.name}\n\n{spec.objective}\n\nStatus: {status}. Template set: {spec.template_set}. Capabilities: {spec.capabilities}.\n'
            f'Items: {len(visible)}. Scene-disjoint splits: {record["split_statistics"]}.\n'
            'Model evaluation must use the isolated model-bundle mount. Local control-plane users are trusted.\n',encoding='utf-8')
        write_json(build/'record.json',record)
        # Existing completed filesystem commit is recoverable while DB still says PREPARING.
        for name in ('model_bundle','authority_bundle'):
            dest=root/name
            if dest.exists():
                # Preserve interrupted attempt for inspection, never overwrite a published release.
                os.rename(dest,root/f'{name}.interrupted.{uid("old")}')
            os.rename(build/name,dest)
        with repo.transaction() as conn:
            conn.execute(visible_items.delete().where(visible_items.c.release_id==release_id))
            conn.execute(answers.delete().where(answers.c.release_id==release_id))
            for item in visible:
                conn.execute(visible_items.insert().values(id=f'{release_id}.{item.item_id}',release_id=release_id,record=item.model_dump(mode='json')))
            for answer in bundle.answers:
                conn.execute(answers.insert().values(id=f'{release_id}.{answer.item_id}',release_id=release_id,record=answer.model_dump(mode='json')))
            conn.execute(update(releases).where(releases.c.id==release_id).values(state=status,record=record))
            repo.event(conn,run_id,None,'release.'+status.lower(),{'release_id':release_id})
        return record


def get_release(repo,release_id):
    with repo.engine.connect() as conn:
        row=conn.execute(select(releases).where(releases.c.id==release_id)).mappings().first()
        if not row or row['state'] not in {'PUBLISHED','DEVELOPMENT'}:
            raise HarnessError('RELEASE_UNAVAILABLE',release_id)
        review=row['record'].get('content_review',{})
        if review and review.get('policy')!='derived-gt-critique/v3':
            raise HarnessError('RELEASE_RETIRED','Historical model-written-GT experiment is unavailable for current evaluation')
        items=[r for r in conn.execute(select(visible_items.c.record).where(visible_items.c.release_id==release_id)).scalars()]
        gold=[r for r in conn.execute(select(answers.c.record).where(answers.c.release_id==release_id)).scalars()]
        return row['record'],items,gold
