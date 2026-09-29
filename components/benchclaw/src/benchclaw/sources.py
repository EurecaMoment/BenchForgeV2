"""Source adapters materialize declared inputs; the common core controls execution."""
import io
import json
import shutil
from pathlib import Path

from PIL import Image
from pydantic import Field

from .domain import (AnswerRecord,Bundle,Contract,HarnessError,HealthResult,MediaAsset,SourceRecord,PublicMetadata,
                     SpatialContext,TemplateEvidence,VisibleEvalItem,WorkResult,WorkUnit,Resources)
from .gates import decode_image
from .plugins import Plugin,merge_inputs,materialize_files
from .store import safe_path


class ImagesParameters(Contract):
    path:str
    images:list[str]=Field(default_factory=list)
    pattern:str='*.jpg'
    annotation:dict


class ImageCollection(Plugin):
    plugin_id='source.images'
    description='Materialize and annotate every explicitly selected image as an independently recoverable task'

    def validate_parameters(self,parameters):
        p=ImagesParameters.model_validate(parameters)
        if '/' in p.pattern or '\\' in p.pattern or '..' in p.pattern:
            raise HarnessError('IMAGE_PATTERN','Use a filename pattern within one explicit directory')

    def healthcheck(self,parameters):
        return HealthResult(ready=Path(parameters['path']).is_dir(),code='IMAGE_SOURCE_MISSING')

    def plan(self,unit):
        self.validate_parameters(unit.parameters)
        p=ImagesParameters.model_validate(unit.parameters);root=Path(p.path)
        images=p.images or sorted(x.name for x in root.glob(p.pattern) if x.is_file())
        if not images or len(set(images))!=len(images):
            raise HarnessError('IMAGE_COLLECTION','Image selection is empty or contains duplicates')
        from .legacy import DefaultAnnotationSource,AnnotationParameters
        result=[]
        for index,name in enumerate(images):
            path=safe_path(root,name,True)
            params={**p.annotation,'path':str(root),'image':name,'source_uri':path.as_uri(),
                    'scene_id':p.annotation.get('scene_id',unit.task_id)+f'_{index:06}'}
            parsed=AnnotationParameters.model_validate(params)
            result.append(unit.model_copy(update={'task_id':unit.task_id+f'_{index:06}',
                'plugin_id':'source.default_annotation','parameters':parsed.model_dump(mode='json'),
                'resources':DefaultAnnotationSource().describe().resources}))
        return result


class ImportParameters(Contract):
    path:str
    source_uri:str
    license_id:str='unverified'
    split:str='test'
    indices:list[int]|None=None
    review_status:str='accepted'


def add_image(output,source,asset_id,scene_id,params):
    dest=safe_path(output,f'media/{asset_id}.png');dest.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as im:
        clean=Image.new('RGB',im.size);clean.paste(im.convert('RGB'));clean.save(dest)
    context=SpatialContext(context_id=asset_id+'_spatial',scene_id=scene_id,coordinate_convention='image_x_right_y_down',length_unit='px')
    asset=MediaAsset(asset_id=asset_id,uri=dest.relative_to(output).as_posix(),scene_id=scene_id,
        spatial_context_id=context.context_id,source_uri=params.source_uri,license_id=params.license_id,
        split=params.split,**decode_image(dest))
    return asset,context


def official_record(output,raw,index,unit,p,image_sources):
    rid=unit.task_id+f'_record_{index:06}';scene=raw.get('scene_id',rid)
    assets=[];contexts=[]
    for j,image in enumerate(image_sources):
        asset,context=add_image(output,image,rid+f'_image_{j:02}',scene,p);assets.append(asset);contexts.append(context)
    if not assets:raise HarnessError('OFFICIAL_MEDIA_EMPTY',rid)
    data={'prompt':raw['prompt'],'choices':raw.get('choices',[]),'answer_type':raw.get('answer_type','json'),
          'gold':raw['gold'],'rubric_id':raw.get('rubric_id','normalized_exact'),'template_id':raw.get('template_id','official_qa'),
          'language':raw.get('language','en'),
          'capability_ids':raw.get('capability_ids',[]),'source_metadata':raw.get('source_metadata',{})}
    record=SourceRecord(record_id=rid,format='official_qa',asset_refs=[a.asset_id for a in assets],source_uri=p.source_uri,
                        review_status=p.review_status,data=data)
    return assets,contexts,record


class EvalsetSource(Plugin):
    plugin_id='source.evalset'
    description='Import explicit official question/answer/media JSONL with source attribution and physical image copies'
    def validate_parameters(self,p):ImportParameters.model_validate(p)
    def healthcheck(self,p):return HealthResult(ready=Path(p['path']).is_file(),code='DATASET_MISSING')
    def execute(self,ctx,unit):
        p=ImportParameters.model_validate(unit.parameters);path=Path(p.path)
        rows=[json.loads(line) for line in path.read_text().splitlines() if line]
        indices=p.indices if p.indices is not None else list(range(len(rows)))
        if len(set(indices))!=len(indices) or any(i<0 or i>=len(rows) for i in indices):
            raise HarnessError('DATASET_INDICES','Invalid or duplicate selected indices')
        assets=[];contexts=[];records=[]
        for i in indices:
            raw=rows[i]
            images=[safe_path(path.parent,x,True) for x in raw['images']]
            a,c,r=official_record(ctx.output_dir,raw,i,unit,p,images);assets+=a;contexts+=c;records.append(r)
        return WorkResult(status='succeeded',bundle=Bundle(assets=assets,contexts=contexts,records=records),metrics={'records':len(records)})


class ERQASource(EvalsetSource):
    plugin_id='source.erqa'
    description='Import local ERQA Parquet preserving official multi-image questions and answers'
    def execute(self,ctx,unit):
        import pyarrow.parquet as pq
        p=ImportParameters.model_validate(unit.parameters)
        parquet=pq.ParquetFile(p.path)
        indices=p.indices if p.indices is not None else list(range(parquet.metadata.num_rows))
        if len(set(indices))!=len(indices) or any(i<0 or i>=parquet.metadata.num_rows for i in indices):
            raise HarnessError('DATASET_INDICES','Invalid ERQA indices')
        selected=set(indices);rows={};offset=0
        for batch in parquet.iter_batches(batch_size=8):
            for row in batch.to_pylist():
                if offset in selected:rows[offset]=row
                offset+=1
            if selected.issubset(rows):break
        assets=[];contexts=[];records=[]
        for i in indices:
            row=rows[i]
            images=[]
            values=row.get('images')
            if values is None:
                values=[row[k] for k in row if k.startswith('image') and row[k] is not None]
            for value in values:
                if isinstance(value,dict) and value.get('bytes'):
                    images.append(io.BytesIO(value['bytes']))
                elif isinstance(value,bytes):images.append(io.BytesIO(value))
                else:raise HarnessError('ERQA_IMAGE_FORMAT','Expected encoded image bytes')
            import re
            # Copy option text verbatim from the official prompt; do not replace it
            # with letter-to-letter placeholders. Preserve the full prompt and GT.
            option_text=row['question'].split('Choices:',1)[-1].split('Please answer',1)[0].strip()
            matches=list(re.finditer(r'(?:^|\s)([A-Z])\.\s',option_text))
            options={match[1]:option_text[match.end():matches[j+1].start() if j+1<len(matches) else len(option_text)].strip()
                     for j,match in enumerate(matches)}
            gold=row.get('answer')
            if gold is None:raise HarnessError('ERQA_ANSWER_MISSING',str(i))
            raw={'prompt':row['question'],'gold':gold,'choices':options,'answer_type':'single_choice' if options else 'json',
                 'rubric_id':'normalized_exact','template_id':'ERQA','capability_ids':[row['question_type']],
                 'source_metadata':{'question_id':row['question_id'],'visual_indices':row['visual_indices']}}
            a,c,r=official_record(ctx.output_dir,raw,i,unit,p,images);assets+=a;contexts+=c;records.append(r)
        return WorkResult(status='succeeded',bundle=Bundle(assets=assets,contexts=contexts,records=records),metrics={'official_records':len(records)})


class RecordEvidence(Plugin):
    plugin_id='evidence.records';kind='evidence'
    description='Normalize typed official/template records and preserve their assets without fabricating labels'
    def execute(self,ctx,unit):
        from .cleaning import clean_bundle
        bundle=clean_bundle(ctx,merge_inputs(ctx)) if unit.plugin_id=='evidence.records' else merge_inputs(ctx)
        assets=[]
        for asset in bundle.assets:
            dest=safe_path(ctx.output_dir,f'media/{asset.asset_id}{Path(asset.uri).suffix}');dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ctx.resolve(asset.uri),dest);assets.append(asset.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
        if not bundle.records:raise HarnessError('RECORDS_MISSING','No source records available')
        return WorkResult(status='succeeded',bundle=bundle.model_copy(update={'assets':assets,'files':materialize_files(ctx,bundle)}),metrics={'records':len(bundle.records)})


class OfficialSynthesizer(RecordEvidence):
    plugin_id='synthesis.official';kind='synthesizer'
    description='Preserve imported official questions, all declared media, and hidden answers'
    def execute(self,ctx,unit):
        result=super().execute(ctx,unit);bundle=result.bundle
        records=[r for r in bundle.records if r.format=='official_qa']
        if len(records)!=ctx.spec.target_items:
            raise HarnessError('OFFICIAL_COUNT','target_items must equal the explicitly selected official records; no silent truncation')
        assets={a.asset_id:a for a in bundle.assets};visible=[];answers=[];evidence=[]
        for r in records:
            d=r.data;eid='ev_'+r.record_id
            visible.append(VisibleEvalItem(item_id=r.record_id,prompt=d['prompt'],choices=d['choices'],answer_type=d['answer_type'],media_refs=[assets[x].uri for x in r.asset_refs],public_metadata=PublicMetadata(language=d.get('language','en'))))
            answers.append(AnswerRecord(item_id=r.record_id,gold=d['gold'],rubric_id=d['rubric_id'],template_id=d['template_id'],capability_ids=d.get('capability_ids',[]),evidence_refs=[eid]))
            evidence.append(TemplateEvidence(evidence_id=eid,asset_refs=r.asset_refs,source_refs=[r.record_id],template_id=d['template_id'],derivation='official_import/v1'))
        return result.model_copy(update={'bundle':bundle.model_copy(update={'visible':visible,'answers':answers,'evidence':evidence})})
