from __future__ import annotations

import itertools
import json
import random
import shutil
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Literal, Protocol
from urllib.request import urlopen

from PIL import Image, ImageDraw
from pydantic import Field

from .domain import (Annotation, AnswerRecord, Bundle, Contract, DatasetSpec, Evidence, HarnessError,
                     HealthResult, MediaAsset, PluginDescriptor, PublicMetadata, SpatialContext,
                     VisibleEvalItem, WorkResult, WorkUnit, Identifier, Nonempty,SourceRecord)
from .gates import decode_image, relation, require_valid, validate_bundle
from .store import safe_path


@dataclass(frozen=True)
class ExecutionContext:
    spec: DatasetSpec
    output_dir: Path
    inputs: dict[str, tuple[Bundle, Path]]

    def resolve(self, uri: str) -> Path:
        if uri.startswith('input:'):
            task, path = uri[6:].split('/',1)
            if task not in self.inputs:
                raise HarnessError('UNDECLARED_INPUT', task)
            return safe_path(self.inputs[task][1], path, True)
        return safe_path(self.output_dir, uri, True)


class HarnessPlugin(Protocol):
    def describe(self) -> PluginDescriptor: ...
    def validate_parameters(self, parameters: dict) -> None: ...
    def healthcheck(self, parameters: dict) -> HealthResult: ...
    def plan(self, unit: WorkUnit) -> list[WorkUnit]: ...
    def execute(self, ctx: ExecutionContext, unit: WorkUnit) -> WorkResult: ...
    def validate(self, ctx: ExecutionContext, result: WorkResult) -> list: ...
    def cleanup(self, ctx: ExecutionContext, result: WorkResult | None) -> None: ...


class Plugin:
    plugin_id = ''
    kind = 'source'
    description = ''

    def describe(self):
        return PluginDescriptor(plugin_id=self.plugin_id, kind=self.kind, description=self.description)

    def validate_parameters(self, parameters):
        if parameters:
            raise HarnessError('UNKNOWN_PARAMETERS', self.plugin_id)

    def healthcheck(self, parameters):
        return HealthResult(ready=True)

    def plan(self, unit):
        self.validate_parameters(unit.parameters)
        return [unit]

    def validate(self, ctx, result):
        if result.bundle is None:
            raise HarnessError('PLUGIN_EMPTY_RESULT', self.plugin_id)
        return []

    def cleanup(self, ctx, result):
        pass


class EntitySourceParameters(Contract):
    path: Nonempty
    source_uri: Nonempty
    license_id: Nonempty
    scene_id: Identifier
    revision: Identifier
    image: str = 'img_0001.jpg'
    annotations: str = 'entity_annotations.json'
    split: Literal['train','validation','test'] = 'test'
    annotation_producer: Nonempty
    annotation_version: Nonempty
    producer_type: Literal['simulator','model','human','fixture']
    review_status: Literal['accepted','needs_human_review','fixture']


class EntitySource(Plugin):
    plugin_id = 'source.entities'
    description = 'Explicit v1 migration of image + legacy entity_annotations; 2D only, no guessed camera calibration'

    def validate_parameters(self, parameters):
        EntitySourceParameters.model_validate(parameters)

    def healthcheck(self, parameters):
        p = EntitySourceParameters.model_validate(parameters)
        try:
            root = Path(p.path).resolve()
            safe_path(root,p.image,True)
            safe_path(root,p.annotations,True)
            return HealthResult(ready=True)
        except HarnessError as exc:
            return HealthResult(ready=False, code=exc.failure.code, message=str(exc))

    def execute(self, ctx, unit):
        p = EntitySourceParameters.model_validate(unit.parameters)
        root = Path(p.path).resolve()
        image = safe_path(root,p.image,True)
        meta = decode_image(image)
        data = json.loads(safe_path(root,p.annotations,True).read_text())
        if data['image_size'] != {'width':meta['width'],'height':meta['height']}:
            raise HarnessError('SOURCE_SIZE_MISMATCH','Legacy annotation dimensions do not match RGB')
        aid = f'{unit.task_id}_rgb'
        context = SpatialContext(context_id=f'{unit.task_id}_spatial', scene_id=p.scene_id,
                                 coordinate_convention='image_x_right_y_down', length_unit='px')
        dest = safe_path(ctx.output_dir,f'media/{aid}{image.suffix.lower()}')
        dest.parent.mkdir(parents=True)
        shutil.copyfile(image,dest)
        asset = MediaAsset(asset_id=aid,uri=dest.relative_to(ctx.output_dir).as_posix(), scene_id=p.scene_id,
                           spatial_context_id=context.context_id,source_uri=p.source_uri,license_id=p.license_id,
                           split=p.split,producer=p.annotation_producer,producer_version=p.annotation_version,**meta)
        anns = []
        for index,obj in enumerate(data['objects']):
            if obj.get('valid_for_question_generation') is not True:
                continue
            # This migrator deliberately names one legacy schema. Unknown variants are not guessed.
            ann = Annotation(annotation_id=f'{unit.task_id}_ann_{index}',asset_id=aid,object_id=obj['object_id'],
                             label=obj['category'],bbox_xyxy=obj['bbox_2d']['xyxy'],confidence=obj['confidence']['value'],
                             producer=p.annotation_producer,producer_version=p.annotation_version,
                             producer_type=p.producer_type,review_status=p.review_status)
            anns.append(ann)
        record=SourceRecord(record_id=unit.task_id+'_source',format='template_entities',asset_refs=[aid],
            source_uri=p.source_uri,review_status=p.review_status,data={'entities':data,'depth_validated':False,'metric_3d_verified':False})
        bundle = Bundle(assets=[asset],contexts=[context],annotations=anns,records=[record])
        if len(anns)<2:
            raise HarnessError('INSUFFICIENT_ANNOTATIONS','At least two usable object boxes are required')
        require_valid(validate_bundle(bundle,ctx.spec,ctx.resolve,final=False))
        return WorkResult(status='succeeded',bundle=bundle,metrics={'assets':1,'annotations':len(anns)})


def merge_inputs(ctx):
    values = {key:[] for key in ('assets','contexts','annotations','evidence','visible','answers','records','files')}
    for task,(bundle,_) in sorted(ctx.inputs.items()):
        for asset in bundle.assets:
            uri = f'input:{task}/{asset.uri}'
            values['assets'].append(asset.model_copy(update={'uri':uri}))
        for key in values:
            if key == 'files':
                values[key].extend(f.model_copy(update={'uri':f'input:{task}/{f.uri}','original_uri':f.original_uri or f.uri}) for f in bundle.files)
            elif key != 'assets':
                values[key].extend(getattr(bundle,key))
    return Bundle(**values)


def materialize_files(ctx,bundle):
    files=[]
    for file in bundle.files:
        dest=safe_path(ctx.output_dir,f'files/{file.file_id}{Path(file.uri).suffix}')
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ctx.resolve(file.uri),dest)
        files.append(file.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
    return files


class GeometryEvidence(Plugin):
    plugin_id = 'evidence.geometry'
    kind = 'evidence'
    description = 'Compute image-space relations from explicit object boxes and pixel coordinate frames'

    def execute(self,ctx,unit):
        from .cleaning import clean_bundle
        bundle = clean_bundle(ctx,merge_inputs(ctx))
        # Each committed task is self contained; only required parent assets are copied.
        updated=[]
        for asset in bundle.assets:
            dest = safe_path(ctx.output_dir,f'media/{asset.asset_id}{Path(asset.uri).suffix}')
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ctx.resolve(asset.uri),dest)
            updated.append(asset.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
        evidence=[]
        for asset in updated:
            anns=[a for a in bundle.annotations if a.asset_id==asset.asset_id]
            for a,b in itertools.combinations(anns,2):
                for axis,dimension in [('x',asset.width),('y',asset.height)]:
                    if axis not in ctx.spec.relation_axes:
                        continue
                    delta,name=relation(a,b,axis)
                    if abs(delta)<dimension*.06:
                        continue
                    evidence.append(Evidence(evidence_id=f'ev_{len(evidence):06}',asset_refs=[asset.asset_id],
                                             annotation_refs=[a.annotation_id,b.annotation_id],axis=axis,
                                             measurement=delta,margin_px=dimension*.06,relation=name,
                                             confidence=min(a.confidence,b.confidence)))
        if not evidence:
            raise HarnessError('NO_EVIDENCE','No unambiguous image-space relationships')
        out=bundle.model_copy(update={'assets':updated,'files':materialize_files(ctx,bundle),'evidence':evidence})
        require_valid(validate_bundle(out,ctx.spec,lambda uri:safe_path(ctx.output_dir,uri,True),final=False))
        return WorkResult(status='succeeded',bundle=out,metrics={'evidence':len(evidence)})


class SpatialSynthesizer(Plugin):
    plugin_id='synthesis.spatial'
    kind='synthesizer'
    description='Evidence-derived 2D multiple-choice questions with neutral A/B visual anchors'

    def execute(self,ctx,unit):
        bundle=merge_inputs(ctx)
        assets={a.asset_id:a for a in bundle.assets}
        anns={a.annotation_id:a for a in bundle.annotations}
        candidates=list(bundle.evidence)
        rng=random.Random(ctx.spec.seed)
        rng.shuffle(candidates)
        if len(candidates)<ctx.spec.target_items:
            raise HarnessError('INSUFFICIENT_EVIDENCE',f'{len(candidates)} evidence records for {ctx.spec.target_items} requested items')
        chosen=candidates[:ctx.spec.target_items]
        new_assets=[]
        # Keep original evidence RGB plus each visible overlay.
        for asset in bundle.assets:
            dest=safe_path(ctx.output_dir,f'media/{asset.asset_id}{Path(asset.uri).suffix}')
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ctx.resolve(asset.uri),dest)
            new_assets.append(asset.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
        visible=[]
        answers=[]
        text={'left':'左侧','right':'右侧','above':'上方','below':'下方'} if ctx.spec.language=='zh-CN' else {'left':'left','right':'right','above':'above','below':'below'}
        # Balanced answer positions without correlating keys to relation or source ordering.
        option_count=2 if ctx.spec.relation_options=='axis_pair' else 4
        gold_positions=[i%option_count for i in range(len(chosen))]
        rng.shuffle(gold_positions)
        bound_evidence=[]
        for index,(ev,gold_pos) in enumerate(zip(chosen,gold_positions)):
            asset=assets[ev.asset_refs[0]]
            dest=safe_path(ctx.output_dir,f'media/overlay_{index:06}.png')
            with Image.open(ctx.resolve(asset.uri)) as im:
                canvas=im.convert('RGB')
                draw=ImageDraw.Draw(canvas)
                for label,ann_id,color in zip(['A','B'],ev.annotation_refs,['#ff3030','#00d5ff']):
                    ann=anns[ann_id]
                    x,y,x2,y2=ann.bbox_xyxy
                    draw.rectangle((x,y,x2-1,y2-1),outline=color,width=3)
                    draw.rectangle((x,y,x+18,y+18),fill=color)
                    draw.text((x+4,y+2),label,fill='black')
                canvas.save(dest)
            overlay=MediaAsset(**{**asset.model_dump(),**decode_image(dest),'asset_id':f'overlay_{index:06}',
                                 'uri':dest.relative_to(ctx.output_dir).as_posix(),'producer':self.plugin_id,'producer_version':'0.1.0'})
            new_assets.append(overlay)
            bound_evidence.append(ev.model_copy(update={'visible_asset_ref':overlay.asset_id}))
            allowed=('left','right') if ev.axis=='x' else ('above','below')
            order=[x for x in text if x!=ev.relation and (ctx.spec.relation_options!='axis_pair' or x in allowed)]
            rng.shuffle(order)
            order.insert(gold_pos,ev.relation)
            semantics=dict(zip('ABCD',order))
            prompt=('图中红框 A 的中心相对于蓝框 B 的中心，在水平方向的哪一侧？' if ev.axis=='x' else '图中红框 A 的中心相对于蓝框 B 的中心，在竖直方向的哪一侧？') if ctx.spec.language=='zh-CN' else f'Where is the center of red box A relative to blue box B along the {"horizontal" if ev.axis=="x" else "vertical"} axis?'
            iid=f'item_{index:06}'
            visible.append(VisibleEvalItem(item_id=iid,prompt=prompt,media_refs=[overlay.uri],choices={k:text[v] for k,v in semantics.items()},public_metadata=PublicMetadata(language=ctx.spec.language)))
            answers.append(AnswerRecord(item_id=iid,gold='ABCD'[gold_pos],evidence_refs=[ev.evidence_id],choice_semantics=semantics))
        out=bundle.model_copy(update={'assets':new_assets,'files':materialize_files(ctx,bundle),'evidence':bound_evidence,'visible':visible,'answers':answers})
        require_valid(validate_bundle(out,ctx.spec,lambda uri:safe_path(ctx.output_dir,uri,True)))
        return WorkResult(status='succeeded',bundle=out,metrics={'items':len(visible)})


class GatePlugin(Plugin):
    plugin_id='gate.dataset'
    kind='validator'
    description='Full declared-media decode, evidence recomputation, answer, split and provenance checks'

    def execute(self,ctx,unit):
        bundle=merge_inputs(ctx)
        source_task=next(iter(ctx.inputs))
        original=ctx.inputs[source_task][0]
        assets=[]
        for asset in bundle.assets:
            dest=safe_path(ctx.output_dir,asset.uri.split('/',1)[1])
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ctx.resolve(asset.uri),dest)
            assets.append(asset.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
        files=[]
        for file in bundle.files:
            dest=safe_path(ctx.output_dir,file.uri.split('/',1)[1]);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ctx.resolve(file.uri),dest)
            files.append(file.model_copy(update={'uri':dest.relative_to(ctx.output_dir).as_posix()}))
        out=original.model_copy(update={'assets':assets,'files':files})
        issues=validate_bundle(out,ctx.spec,lambda uri:safe_path(ctx.output_dir,uri,True),
                              acceptance=unit.task_id=='validate')
        errors=any(i.severity in {'error','fatal'} for i in issues)
        return WorkResult(status='quarantined' if errors else 'succeeded',bundle=out,issues=issues,
                          metrics={'media_checked':len(assets),'items_checked':len(out.visible)})


class Registry:
    def __init__(self):
        from .legacy import DefaultAnnotationSource
        from .sources import ImageCollection,ERQASource,EvalsetSource,RecordEvidence,OfficialSynthesizer
        from .template_engine import TemplateSynthesizer
        from .simulators import HabitatSource,LiberoSource,CarlaSource,LiberoHDF5Source,CaptureAnnotator
        from .research import ResearchPlugin
        from .semantic_review import SemanticReview,CandidateSource,CandidatePass,AnnotationSnapshot
        from .collection_review import CollectionReview
        self.plugins={p.plugin_id:p for p in [EntitySource(),DefaultAnnotationSource(),ImageCollection(),ERQASource(),EvalsetSource(),
                     ResearchPlugin(),HabitatSource(),LiberoSource(),CarlaSource(),LiberoHDF5Source(),CaptureAnnotator(),
                     RecordEvidence(),OfficialSynthesizer(),TemplateSynthesizer(),SemanticReview(),CollectionReview(),CandidateSource(),CandidatePass(),AnnotationSnapshot(),GeometryEvidence(),SpatialSynthesizer(),GatePlugin()]}
        for ep in entry_points(group='benchclaw.plugins'):
            plugin=ep.load()()
            desc=plugin.describe()
            if desc.plugin_id in self.plugins:
                raise HarnessError('DUPLICATE_PLUGIN',desc.plugin_id)
            self.plugins[desc.plugin_id]=plugin

    def get(self,key):
        if key not in self.plugins:
            raise HarnessError('PLUGIN_NOT_FOUND',key)
        return self.plugins[key]
