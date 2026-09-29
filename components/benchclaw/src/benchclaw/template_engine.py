"""Adapt the original executable template engine without adding another workflow."""
import argparse
import importlib.util
import io
import json
import random
import sys
from pathlib import Path

from PIL import Image,ImageChops

from .domain import (AnswerRecord,Bundle,HarnessError,MediaAsset,PublicMetadata,SourceRecord,
                     TemplateEvidence,VisibleEvalItem,WorkResult)
from .gates import decode_image
from .plugins import Plugin,merge_inputs,materialize_files
from .store import safe_path

ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'BenchClaw/templates/tools/synthesize_static_vlm_benchmark.py'


def engine():
    name='benchclaw_migrated_templates'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,ENGINE)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return sys.modules[name]


def catalogue():
    m=engine()
    coverage=json.loads((ROOT/'BenchClaw/templates/template_library/executable_template_coverage.json').read_text())
    executable={x['template_id'] for x in coverage if x['executable_in_tool']=='yes'} | {'T085'}
    sets={k:sorted(v & executable) for k,v in m.TEMPLATE_SETS.items()}
    sets['strict_all_supported']=sorted(executable-m.DEPRECATED_LOCKED_TEMPLATES)
    from .spatial_tasks import IDS
    return {'sets':sets,'task_contracts':{'legacy-v1':'Original executable definitions',
            'spatial-v2':{'templates':sorted(IDS),'two_dimensional_measure':'visible_bbox_center_px',
                'depth_measure':'median_euclidean_range_m','requires_calibrated_capture_for_depth':True}},
            'templates':[x for x in coverage if x['template_id'] in executable]+[{'template_id':'T085','executable_in_tool':'yes',**m.TEMPLATE_META.get('T085',{})}],
            'deprecated':sorted(m.DEPRECATED_LOCKED_TEMPLATES),
            'declared_without_generator':sorted(set.union(*m.TEMPLATE_SETS.values())-executable-m.DEPRECATED_LOCKED_TEMPLATES)}


def generate(record,image_path,spec,output=None):
    if spec.task_contract=='spatial-v2':
        from .spatial_tasks import generate_spatial
        return generate_spatial(record,image_path,spec,output)
    m=engine()
    allowed=set(catalogue()['sets'][spec.template_set])
    if spec.template_ids:
        missing=set(spec.template_ids)-allowed
        if missing:
            raise HarnessError('UNSUPPORTED_TEMPLATE',','.join(sorted(missing)))
        allowed=set(spec.template_ids)
    if not record.data.get('depth_validated',False):
        allowed-={f'T{i:03}' for i in [36,37,38,39,40,41,45,91,95,96,97]}
    if not record.data.get('metric_3d_verified',False):
        allowed-={'T040','T041','T056','T057','T060','T063'}
    if not allowed:
        return []
    entity=record.data['entities']
    with Image.open(image_path) as im:
        buf=io.BytesIO();im.convert('RGB').save(buf,format='JPEG',quality=95)
    sample=m.build_sample(record.record_id,record.source_uri,entity,buf.getvalue(),'rgb.jpg',None,None)
    args=argparse.Namespace(seed=spec.seed,asset_dir=str(output or '/replay'),template_ids=','.join(sorted(allowed)),
        template_set=spec.template_set,max_per_template=max(1,min(spec.target_items,8)),min_conf=.5,min_area=80,
        require_valid=True,drop_categories='sky,cloud,clouds,road,ground,terrain,floor,ceiling,wall',max_area_frac=.35,
        include_depth=record.data.get('depth_validated',False),include_3d=record.data.get('metric_3d_verified',False),
        negative_categories=','.join(m.DEFAULT_NEGATIVE_CATEGORIES),xy_margin_frac=.06)
    # Replay uses the same arithmetic and seeded selection, but performs no file writes.
    original_sink,original_overlay=m.ItemSink,m.make_overlay
    class Sink(original_sink):
        def __init__(self,sample,asset_dir,max_per_template,rng,allowed_template_ids=None):
            self.sample,self.asset_dir,self.max_per_template,self.rng=sample,asset_dir,max_per_template,rng
            self.allowed_template_ids=allowed_template_ids
            from collections import Counter
            self.items=[];self.count_by_template=Counter();self.used_signatures=set()
            self.base_image_path=Path('/replay')/sample.sample_id/'rgb.jpg'
    if output is None:
        m.ItemSink=Sink;m.make_overlay=lambda *a,**kw:None
    try:
        return m.generate_items_for_sample(sample,args)
    finally:
        m.ItemSink,m.make_overlay=original_sink,original_overlay


def canonical(row,record,media_refs):
    answer_type=row['answer_type'].lower()
    types={'single_choice':'single_choice','multi_choice':'multi_choice','multiple_choice':'multi_choice','multi_select':'multi_choice',
           'binary':'single_choice','yes_no':'single_choice','interval':'interval','ordering':'ordering','ordered_list':'ordering','number':'numeric','numeric':'numeric','json_array':'json','json':'json'}
    answer_type=types.get(answer_type,answer_type)
    if answer_type not in {'single_choice','multi_choice','interval','ordering','numeric','json','text'}:
        raise HarnessError('TEMPLATE_ANSWER_TYPE',answer_type)
    choices=row['options'] if row['options'] is not None else []
    if isinstance(choices,dict) and len(set(str(v) for v in choices.values()))!=len(choices):
        if not row.get('auxiliary_images'):
            raise HarnessError('AMBIGUOUS_TEMPLATE_OPTIONS','Duplicate category options without visible object labels')
        choices={k:f'{k}: {v}' for k,v in choices.items()}
    question=row['question']
    if row['template_id']=='T033':
        question='在标注图中，物体 A 与物体 B 的二维外接框是否重叠，或框间距不超过图像短边的 1.5%？'
    visible=VisibleEvalItem(item_id=row['item_id'],prompt=question,media_refs=media_refs,
                           choices=choices,answer_type=answer_type)
    ev=TemplateEvidence(evidence_id='ev_'+row['item_id'],asset_refs=record.asset_refs,source_refs=[record.record_id],
        template_id=row['template_id'],derivation=row.get('derivation','legacy_template_engine/v1'),
        fields={'generated_item_id':row['item_id'],**({'task_contract':row['task_contract']} if 'task_contract' in row else {})})
    metric={'set_exact_match + macro_f1':'set_exact_match'}.get(row['scoring']['metric'],row['scoring']['metric'])
    gold=row['answer']
    if answer_type=='single_choice' and isinstance(choices,dict) and gold not in choices:
        matched=[key for key,value in choices.items() if value==gold]
        if len(matched)!=1:raise HarnessError('TEMPLATE_GOLD','Cannot resolve semantic gold to an unambiguous option')
        gold=matched[0]
    answer=AnswerRecord(item_id=row['item_id'],gold=gold,rubric_id=metric,
                        template_id=row['template_id'],capability_ids=row.get('capability_ids',[]),
                        metric_parameters={'tolerance':row['scoring'].get('tolerance')},evidence_refs=[ev.evidence_id])
    return visible,answer,ev


class TemplateSynthesizer(Plugin):
    plugin_id='synthesis.templates';kind='synthesizer'
    description='Original executable static templates with reproducible evidence and multiple answer types'

    def execute(self,ctx,unit):
        import shutil
        bundle=merge_inputs(ctx)
        assets={a.asset_id:a for a in bundle.assets}
        official=[r for r in bundle.records if r.format=='official_qa']
        target=ctx.spec.target_items-len(official)
        if target<0:raise HarnessError('OFFICIAL_COUNT','Target cannot omit explicitly selected official questions')
        candidates=[]
        for record in bundle.records:
            if record.format=='template_entities':
                image=ctx.resolve(assets[record.asset_refs[0]].uri)
                candidates.extend((row,record) for row in generate(record,image,ctx.spec))
        candidates.sort(key=lambda pair:(pair[0]['template_id'],pair[0]['item_id']))
        # For v2 select across frames, templates and semantic answers, rather than
        # taking the first lexicographic items from the first frame.
        from collections import defaultdict
        if ctx.spec.task_contract=='spatial-v2':
            from .spatial_tasks import select_diverse
        groups=defaultdict(list)
        for row,record in candidates:groups[row['template_id']].append((row,record))
        missing=set(ctx.spec.template_ids)-set(groups)
        if missing:
            raise HarnessError('TEMPLATE_EVIDENCE_MISSING',','.join(sorted(missing)))
        chosen=[]
        if ctx.spec.task_contract=='spatial-v2':
            chosen=select_diverse(candidates,target)
            groups={}
        while groups and len(chosen)<target:
            for key in list(groups):
                if len(chosen)==target:break
                chosen.append(groups[key].pop(0))
                if not groups[key]:del groups[key]
        if len(chosen)!=target:
            raise HarnessError('INSUFFICIENT_TEMPLATE_EVIDENCE',f'{len(chosen)} reproducible items for {ctx.spec.target_items} requested')
        used={r.record_id for _,r in chosen}
        originals=[]
        for asset in bundle.assets:
            dest=safe_path(ctx.output_dir,f'media/{asset.asset_id}{Path(asset.uri).suffix}');dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ctx.resolve(asset.uri),dest)
            originals.append(asset.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
        produced={}
        for record in bundle.records:
            if record.record_id in used:
                source_image=ctx.resolve(assets[record.asset_refs[0]].uri)
                if ctx.spec.task_contract=='spatial-v2':
                    from .spatial_tasks import render
                    selected={row['item_id'] for row,rec in chosen if rec.record_id==record.record_id}
                    rows=[row for row in generate(record,source_image,ctx.spec) if row['item_id'] in selected]
                    for row in rows:
                        path=ctx.output_dir/'generated'/record.record_id/(row['item_id']+'.png')
                        render(source_image,row['provenance']['objects'],path);row['image']=str(path)
                else:rows=generate(record,source_image,ctx.spec,ctx.output_dir/'generated')
                produced.update({r['item_id']:r for r in rows})
        visible=[];answers=[];evidence=[];media=list(originals)
        for row,record in chosen:
            actual=produced[row['item_id']]
            image=Path(actual['image'])
            dest=safe_path(ctx.output_dir,f'media/{row["item_id"]}.png')
            with Image.open(image) as im:im.convert('RGB').save(dest)
            source=assets[record.asset_refs[0]]
            asset=MediaAsset(**{**source.model_dump(),**decode_image(dest),'asset_id':'visible_'+row['item_id'],'uri':dest.relative_to(ctx.output_dir).as_posix()})
            media.append(asset)
            v,a,e=canonical(row,record,[asset.uri]);visible.append(v);answers.append(a);evidence.append(e)
        by_id={a.asset_id:a for a in media}
        for record in official:
            d=record.data;eid='ev_'+record.record_id
            visible.append(VisibleEvalItem(item_id=record.record_id,prompt=d['prompt'],choices=d['choices'],answer_type=d['answer_type'],media_refs=[by_id[x].uri for x in record.asset_refs],public_metadata=PublicMetadata(language=d.get('language','en'))))
            answers.append(AnswerRecord(item_id=record.record_id,gold=d['gold'],rubric_id=d['rubric_id'],template_id=d['template_id'],capability_ids=d.get('capability_ids',[]),evidence_refs=[eid]))
            evidence.append(TemplateEvidence(evidence_id=eid,asset_refs=record.asset_refs,source_refs=[record.record_id],template_id=d['template_id'],derivation='official_import/v1'))
        out=bundle.model_copy(update={'assets':media,'visible':visible,'answers':answers,'evidence':evidence,'files':materialize_files(ctx,bundle)})
        return WorkResult(status='succeeded',bundle=out,metrics={'items':len(visible),'templates':len({a.template_id for a in answers})})


def validate_template_items(bundle,spec,resolve,issue):
    assets={a.asset_id:a for a in bundle.assets};records={r.record_id:r for r in bundle.records}
    answers={a.item_id:a for a in bundle.answers};evidence={e.evidence_id:e for e in bundle.evidence}
    import tempfile
    replay={}
    temporary=tempfile.TemporaryDirectory(prefix='benchclaw-replay-')
    try:
      _validate_items(bundle,spec,resolve,issue,assets,records,answers,evidence,replay,Path(temporary.name))
    finally:
      temporary.cleanup()


def _validate_items(bundle,spec,resolve,issue,assets,records,answers,evidence,replay,directory):
    checked=set()
    for item in bundle.visible:
        answer=answers.get(item.item_id)
        if not answer or not answer.evidence_refs:continue
        ev=evidence.get(answer.evidence_refs[0])
        if not isinstance(ev,TemplateEvidence):continue
        try:
            if len(ev.source_refs)!=1 or ev.template_id!=answer.template_id:
                raise ValueError('Invalid template evidence identity')
            record=records[ev.source_refs[0]]
            if ev.asset_refs!=record.asset_refs:
                raise ValueError('Template source media binding differs')
            if (record.data.get('metric_3d_verified') or record.data.get('range_verified')) and record.review_status!='fixture':
                origin=records.get(record.data.get('capture_record_ref'))
                if not origin or origin.format!='capture' or not origin.data.get('ground_truth',{}).get('camera_intrinsics'):
                    raise ValueError('Metric geometry requires calibrated simulator source evidence')
                if record.record_id not in checked:
                    validate_metric_geometry(record,origin,bundle,resolve)
                    checked.add(record.record_id)
            if spec.quality_policy=='production-v1' and record.review_status!='accepted':
                issue('ANNOTATION_REVIEW_REQUIRED','Source evidence requires review',item.item_id)
            if record.format=='template_entities':
                if record.record_id not in replay:
                    replay[record.record_id]={r['item_id']:r for r in generate(record,resolve(assets[record.asset_refs[0]].uri),spec,
                        None if spec.task_contract=='spatial-v2' else directory/record.record_id)}
                row=replay[record.record_id][item.item_id]
                if spec.task_contract=='spatial-v2':
                    from .spatial_tasks import render
                    path=directory/record.record_id/(item.item_id+'.png')
                    render(resolve(assets[record.asset_refs[0]].uri),row['provenance']['objects'],path)
                    row['image']=str(path)
                expected_fields={'generated_item_id':item.item_id,**({'task_contract':row['task_contract']} if 'task_contract' in row else {})}
                if ev.derivation!=row.get('derivation','legacy_template_engine/v1') or ev.fields!=expected_fields:
                    raise ValueError('Invalid derivation identity')
                if len(item.media_refs)!=1:
                    raise ValueError('One generated overlay required')
                with Image.open(row['image']) as expected,Image.open(resolve(item.media_refs[0])) as actual:
                    if expected.size!=actual.size or ImageChops.difference(expected.convert('RGB'),actual.convert('RGB')).getbbox():
                        raise ValueError('Visible image differs from replayed template overlay')
                v,a,e=canonical(row,record,item.media_refs)
                if (v.prompt,v.choices,v.answer_type,a.gold,a.rubric_id,a.template_id,a.capability_ids,a.metric_parameters)!=(item.prompt,item.choices,item.answer_type,answer.gold,answer.rubric_id,answer.template_id,answer.capability_ids,answer.metric_parameters):
                    raise ValueError('Template question/answer differs from deterministic replay')
            elif record.format=='official_qa':
                expected=record.data
                if ev.derivation!='official_import/v1' or item.item_id!=record.record_id:
                    raise ValueError('Official evidence identity changed')
                refs=[assets[x].uri for x in record.asset_refs]
                if (item.prompt,item.choices,item.answer_type,answer.gold,answer.rubric_id,answer.template_id,answer.capability_ids,item.media_refs)!=(expected['prompt'],expected['choices'],expected['answer_type'],expected['gold'],expected['rubric_id'],expected['template_id'],expected.get('capability_ids',[]),refs):
                    raise ValueError('Official question, media or answer changed after import')
            else:
                raise ValueError('Capture records cannot directly establish question answers')
        except (KeyError,ValueError,OSError,StopIteration,HarnessError) as exc:
            issue('TEMPLATE_DERIVATION',str(exc),item.item_id)


def validate_metric_geometry(record,capture,bundle,resolve):
    """Recompute only the metric fields actually introduced by the capture adapter."""
    import numpy as np
    files={f.file_id:f for f in bundle.files};assets={a.asset_id:a for a in bundle.assets}
    with Image.open(resolve(assets[capture.asset_refs[0]].uri)) as original,Image.open(resolve(assets[record.asset_refs[0]].uri)) as annotated:
        if original.size!=annotated.size or ImageChops.difference(original.convert('RGB'),annotated.convert('RGB')).getbbox():
            raise ValueError('Calibrated depth belongs to a different source image')
    depth_file=next(files[f] for f in capture.data['file_refs'] if files[f].kind=='depth')
    depth=np.load(resolve(depth_file.uri),allow_pickle=False);k=np.array(capture.data['ground_truth']['camera_intrinsics'])
    record_files={files[f].original_uri or files[f].uri:files[f] for f in record.data['file_refs']}
    for obj in record.data['entities']['objects']:
        with Image.open(resolve(record_files[obj['mask']['path']].uri)) as im:mask=np.asarray(im)>0
        if mask.ndim==3:mask=mask.any(axis=2)
        if mask.shape!=depth.shape:raise ValueError('Mask/depth alignment changed')
        y,x=np.where(mask & np.isfinite(depth) & (depth>0));z=depth[y,x]
        if not len(z):
            if obj.get('depth_median') is not None or obj.get('range_median_m') is not None or obj.get('centroid_3d') or obj.get('rough_3d_bbox'):
                raise ValueError('Missing simulator depth cannot establish metric geometry')
            continue
        xyz=np.column_stack(((x-k[0,2])*z/k[0,0],(y-k[1,2])*z/k[1,1],z))
        if abs(float(np.median(z))-obj['depth_median'])>1e-5 or not np.allclose(np.median(xyz,axis=0),obj['centroid_3d']['xyz'],rtol=0,atol=1e-5) or not np.allclose(xyz.max(axis=0)-xyz.min(axis=0),obj['rough_3d_bbox']['size_xyz'],rtol=0,atol=1e-5):
            raise ValueError('Metric geometry differs from captured depth and declared masks')
        if record.data.get('range_verified') and abs(float(np.median(np.linalg.norm(xyz,axis=1)))-obj['range_median_m'])>1e-5:
            raise ValueError('Range differs from calibrated depth and mask')
