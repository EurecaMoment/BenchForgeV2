from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from .domain import Bundle, DatasetSpec, HarnessError, Issue, TemplateEvidence,ModelEvidence
from .store import safe_path


def decode_image(path: Path) -> dict:
    try:
        expected = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}
        with Image.open(path) as im:
            if im.format != expected.get(path.suffix.lower()):
                raise ValueError('extension/encoding mismatch or unsupported image format')
            im.verify()
        with Image.open(path) as im:
            im.load()
            if im.mode != 'RGB':
                raise ValueError('RGB image must have three channels')
            extrema = im.getextrema()
            if all(lo == hi for lo, hi in extrema):
                raise ValueError('uniform image is not acceptable RGB evidence')
            return {'width':im.width, 'height':im.height, 'encoding':im.format, 'channels':3, 'byte_size':path.stat().st_size}
    except Exception as exc:
        raise HarnessError('MEDIA_DECODE_FAILED', f'{path.name}: {exc}') from exc


def relation(a, b, axis):
    idx = 0 if axis == 'x' else 1
    delta = (a.bbox_xyxy[idx]+a.bbox_xyxy[idx+2]-b.bbox_xyxy[idx]-b.bbox_xyxy[idx+2])/2
    name = ('left' if delta < 0 else 'right') if axis == 'x' else ('above' if delta < 0 else 'below')
    return delta, name


def validate_bundle(bundle: Bundle, spec: DatasetSpec, resolve_asset, final=True, acceptance=True) -> list[Issue]:
    issues = []
    def issue(code, message, entity_id='', severity='error'):
        issues.append(Issue(code=code, message=message, entity_id=entity_id, severity=severity))

    tables = {}
    for name, key in [('assets','asset_id'), ('contexts','context_id'), ('annotations','annotation_id'), ('evidence','evidence_id'), ('visible','item_id'), ('answers','item_id'),('records','record_id'),('files','file_id')]:
        rows = getattr(bundle, name)
        ids = [getattr(x,key) for x in rows]
        if len(ids) != len(set(ids)):
            issue('DUPLICATE_ID', name)
        tables[name] = {getattr(x,key): x for x in rows}
    assets, contexts, anns, evs = (tables[k] for k in ('assets','contexts','annotations','evidence'))
    for file in bundle.files:
        try:
            path=resolve_asset(file.uri)
            if path.stat().st_size!=file.byte_size:raise ValueError('File size mismatch')
            if file.kind=='depth' and path.suffix=='.npy':
                import numpy as np
                depth=np.load(path,allow_pickle=False)
                if depth.ndim!=2 or not np.isfinite(depth).all() or not (depth>0).any():
                    raise ValueError('Depth must be finite, two dimensional and nonempty')
        except (OSError,ValueError,HarnessError) as exc:
            issue('DATA_FILE_INVALID',str(exc),file.file_id)
    for record in bundle.records:
        if any(ref not in assets for ref in record.asset_refs):
            issue('RECORD_MEDIA_MISSING','Record references undeclared media',record.record_id)
        if any(ref not in tables['files'] for ref in record.data.get('file_refs',[])):
            issue('RECORD_FILE_MISSING','Record references missing auxiliary data',record.record_id)
    scene_splits = {}
    if not assets:
        issue('EMPTY_MEDIA', 'No media assets')
    for asset in assets.values():
        if asset.spatial_context_id not in contexts or contexts[asset.spatial_context_id].scene_id != asset.scene_id:
            issue('SPATIAL_CONTEXT_MISSING', 'Asset must reference its scene context', asset.asset_id)
        if asset.scene_id in scene_splits and scene_splits[asset.scene_id] != asset.split:
            issue('SPLIT_LEAKAGE', 'Scene occurs in multiple splits', asset.scene_id)
        scene_splits[asset.scene_id] = asset.split
        try:
            meta = decode_image(resolve_asset(asset.uri))
            if any(getattr(asset,k) != v for k,v in meta.items()):
                issue('MEDIA_METADATA_MISMATCH', 'Declared image metadata differs from decoded image', asset.asset_id)
        except HarnessError as exc:
            issue(exc.failure.code, str(exc), asset.asset_id)
        if spec.quality_policy == 'production-v1' and asset.license_id.lower() in {'unknown','fixture-only','unverified'}:
            issue('LICENSE_UNVERIFIED', 'Production requires verified source licensing', asset.asset_id)
    object_keys = set()
    for ann in anns.values():
        asset = assets.get(ann.asset_id)
        if asset is None or ann.bbox_xyxy[2] > asset.width or ann.bbox_xyxy[3] > asset.height:
            issue('BBOX_OUT_OF_BOUNDS', 'Bounding box must fit referenced RGB', ann.annotation_id)
        key = (ann.asset_id, ann.object_id)
        if key in object_keys:
            issue('DUPLICATE_OBJECT', 'Object identity must be unique within a frame', ann.annotation_id)
        object_keys.add(key)
        if ann.confidence < 0.5:
            issue('ANNOTATION_LOW_CONFIDENCE', 'Review required below confidence 0.5', ann.annotation_id)
        if spec.quality_policy == 'production-v1' and (ann.review_status != 'accepted' or ann.producer_type == 'fixture'):
            issue('ANNOTATION_REVIEW_REQUIRED', 'Production evidence requires accepted annotations', ann.annotation_id)
    for ev in evs.values():
        if isinstance(ev,ModelEvidence):
            issue('GT_DERIVATION_REQUIRED','Model judgments cannot replace annotation/simulator/official GT evidence',ev.evidence_id)
            continue
        if isinstance(ev,TemplateEvidence):
            if not ev.source_refs:
                issue('TEMPLATE_EVIDENCE_INVALID','Template evidence needs source references',ev.evidence_id)
            if any(ref not in assets for ref in ev.asset_refs):
                issue('TEMPLATE_EVIDENCE_MEDIA','Template evidence has undeclared media',ev.evidence_id)
            continue
        try:
            a,b = [anns[k] for k in ev.annotation_refs]
            if a.annotation_id == b.annotation_id or a.asset_id != b.asset_id or ev.asset_refs != [a.asset_id]:
                raise ValueError('Evidence must reference two distinct objects in the same image')
            if ev.axis not in spec.relation_axes:
                issue('RELATION_AXIS_NOT_REQUESTED','Evidence axis must match DatasetSpec',ev.evidence_id)
            delta, expected = relation(a,b,ev.axis)
            if abs(delta) < ev.margin_px or abs(delta-ev.measurement) > 1e-6 or expected != ev.relation:
                raise ValueError('Evidence relation/measurement cannot be recomputed')
        except (KeyError, ValueError) as exc:
            issue('EVIDENCE_INVALID', str(exc), ev.evidence_id)
    if final:
        if acceptance and spec.collection_policy:
            from .collection_review import validate_collection
            validate_collection(bundle,spec,resolve_asset,issue)
        from .semantic_review import validate_review_bundle
        reviewed=validate_review_bundle(bundle,spec,resolve_asset,issue)
        if any(isinstance(e,ModelEvidence) for e in bundle.evidence) and not reviewed:
            issue('SEMANTIC_REVIEW_MISSING','Model-reviewed claims require a review manifest')
        if bundle.records:
            from .template_engine import validate_template_items
            validate_template_items(bundle,spec,resolve_asset,issue)
        if not reviewed and len(bundle.visible) != spec.target_items:
            issue('TARGET_COUNT', f'Expected {spec.target_items}, got {len(bundle.visible)}')
        missing=set(spec.template_ids)-{a.template_id for a in bundle.answers}
        if missing and not reviewed:issue('TEMPLATE_COVERAGE','Requested templates absent: '+','.join(sorted(missing)))
        if set(tables['visible']) != set(tables['answers']):
            issue('ANSWER_COVERAGE', 'Visible and answer IDs must match exactly')
        media_by_uri = {a.uri for a in assets.values()}
        used_evidence = set()
        for item in bundle.visible:
            if any(uri not in media_by_uri for uri in item.media_refs):
                issue('UNDECLARED_MEDIA', 'Visible item references unknown image', item.item_id)
            answer = tables['answers'].get(item.item_id)
            if not answer:
                continue
            if len(answer.evidence_refs) != 1 or answer.evidence_refs[0] not in evs:
                issue('ANSWER_EVIDENCE', 'Answer needs one recomputable relation', item.item_id)
                continue
            if answer.evidence_refs[0] in used_evidence:
                issue('DUPLICATE_QUESTION', 'Evidence reused to inflate item count', item.item_id)
            used_evidence.add(answer.evidence_refs[0])
            ev = evs[answer.evidence_refs[0]]
            if isinstance(ev,(TemplateEvidence,ModelEvidence)):
                from .metrics import score_answer
                try:
                    if score_answer(answer.gold,answer.gold,answer.rubric_id,answer.metric_parameters)!=1:
                        raise ValueError('Rubric does not accept its own gold')
                    if item.answer_type in {'single_choice','interval'} and str(answer.gold) not in item.choices:
                        raise ValueError('Gold is not one of the declared options')
                    if item.answer_type=='multi_choice' and (not isinstance(answer.gold,list) or not set(answer.gold)<=set(item.choices)):
                        raise ValueError('Multi-choice gold contains undeclared options')
                except (ValueError,TypeError) as exc:
                    issue('RUBRIC_INVALID',str(exc),item.item_id)
                continue
            overlay = assets.get(ev.visible_asset_ref)
            if overlay is None or item.media_refs != [overlay.uri]:
                issue('EVIDENCE_MEDIA_BINDING', 'Visible media must match evidence overlay', item.item_id)
            else:
                try:
                    original = assets[ev.asset_refs[0]]
                    with Image.open(resolve_asset(original.uri)) as source, Image.open(resolve_asset(overlay.uri)) as actual:
                        expected = source.convert('RGB')
                        draw = ImageDraw.Draw(expected)
                        for label,ann_id,color in zip(['A','B'],ev.annotation_refs,['#ff3030','#00d5ff']):
                            x,y,x2,y2 = anns[ann_id].bbox_xyxy
                            draw.rectangle((x,y,x2-1,y2-1),outline=color,width=3)
                            draw.rectangle((x,y,x+18,y+18),fill=color)
                            draw.text((x+4,y+2),label,fill='black')
                        if expected.size != actual.size or ImageChops.difference(expected,actual.convert('RGB')).getbbox():
                            issue('OVERLAY_MISMATCH', 'Visible anchors must correspond to the evidence annotations', item.item_id)
                except (KeyError,OSError,HarnessError) as exc:
                    issue('OVERLAY_INVALID',str(exc),item.item_id)
            expected_prompt = ('图中红框 A 的中心相对于蓝框 B 的中心，在水平方向的哪一侧？' if ev.axis=='x' else '图中红框 A 的中心相对于蓝框 B 的中心，在竖直方向的哪一侧？') if spec.language=='zh-CN' else f'Where is the center of red box A relative to blue box B along the {"horizontal" if ev.axis=="x" else "vertical"} axis?'
            if item.prompt != expected_prompt:
                issue('QUESTION_DERIVATION', 'Question must use the evidence-bound template', item.item_id)
            if set(answer.choice_semantics) != set(item.choices) or answer.choice_semantics.get(answer.gold) != ev.relation:
                issue('GOLD_MISMATCH', 'Gold does not follow evidence and choices', item.item_id)
            if spec.relation_options=='axis_pair' and set(answer.choice_semantics.values())!=({'left','right'} if ev.axis=='x' else {'above','below'}):
                issue('CHOICE_AXIS','Options must follow the declared axis-pair specification',item.item_id)
            semantic_text = {'left':'左侧','right':'右侧','above':'上方','below':'下方'} if spec.language == 'zh-CN' else {'left':'left','right':'right','above':'above','below':'below'}
            if any(item.choices.get(k) != semantic_text[v] for k,v in answer.choice_semantics.items()):
                issue('CHOICE_SEMANTICS', 'Visible choice text differs from scoring semantics', item.item_id)
        if spec.quality_policy == 'development-v1':
            issue('DEVELOPMENT_ONLY', 'Complete checks for this run; fixture/development results are not production releases', severity='warning')
    return issues


def require_valid(issues):
    errors = [i for i in issues if i.severity in {'error','fatal'}]
    if errors:
        raise HarnessError(errors[0].code, '; '.join(i.message for i in errors[:8]))
