"""Deterministic metrics, model-visible inference, diagnostics inputs and portable releases."""
from __future__ import annotations
import base64
import json
import math
import mimetypes
import os
import random
import re
import shutil
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
try:
    from .artifacts import read, rows, write, jsonl, unique
except ImportError:  # bundled standalone scorer
    from artifacts import read, rows, write, jsonl, unique


def identity(row):
    return str(row.get('item_id',row.get('id',row.get('eval_id',''))))


def normalized(value):
    return ' '.join(str(value).strip().casefold().split())


def sequence(value):
    if isinstance(value,list):return value
    if isinstance(value,str):
        try:
            parsed=json.loads(value)
            if isinstance(parsed,list):return parsed
        except ValueError:pass
        return [v.strip() for v in re.split(r'[,;>\s]+',value.strip('[] ')) if v.strip()]
    return []


def metric(item,pred):
    gold=item['answer']
    name=item.get('metric_id','exact_match')
    kind=item.get('answer_type','')
    # OpenAI-compatible respondents commonly wrap scalar/list answers. Recognize
    # only a single documented answer envelope; preserve structured JSON answers.
    if name!='json_field_accuracy' and isinstance(pred,dict) and set(pred)=={'answer'}:
        pred=pred['answer']
    if pred is None:return 0.0
    if name in ('set_f1','multi_choice_f1') or kind=='multi_choice':
        a={normalized(v) for v in sequence(gold)};b={normalized(v) for v in sequence(pred)}
        return 2*len(a&b)/(len(a)+len(b)) if a or b else 1.0
    if name=='pairwise_order_accuracy':
        a=sequence(gold);b=sequence(pred)
        if len(set(b))!=len(b) or set(a)!=set(b):return 0.0
        pairs=[(x,y) for i,x in enumerate(a) for y in a[i+1:]]
        return sum(b.index(x)<b.index(y) for x,y in pairs)/len(pairs) if pairs else float(a==b)
    if name in ('order_exact_accuracy','ordered_exact') or kind=='ordered_list':
        return float([normalized(v) for v in sequence(gold)]==[normalized(v) for v in sequence(pred)])
    if name in ('numeric_tolerance','pose_range','counting_accuracy') or kind=='number':
        try:
            a,b=float(gold),float(pred)
            if not math.isfinite(a) or not math.isfinite(b):return 0.0
            error=abs(a-b)
            tolerance=float(item.get('tolerance',0))
            if name=='pose_range':return 1.0 if error<=tolerance else max(0.0,1-(error-tolerance)/float(item.get('decay',20)))
            if name=='counting_accuracy':return 1.0 if error==0 else 0.5 if error==1 else 0.0
            return float(error<=max(tolerance,float(item.get('relative_tolerance',0))*abs(a)))
        except (ValueError,TypeError):return 0.0
    if name=='json_field_accuracy':
        if isinstance(pred,str):
            try:pred=json.loads(pred)
            except ValueError:return 0.0
        if not isinstance(gold,dict) or not isinstance(pred,dict):return 0.0
        return sum(pred.get(k)==v for k,v in gold.items())/len(gold) if gold else float(not pred)
    if name=='traffic_light_action':
        if normalized(pred)==normalized(gold):return 1.0
        return 0.5 if normalized(pred) in ('stop','proceed') and normalized(gold) in ('stop','proceed') else 0.0
    if name in ('accuracy','exact_match','normalized_exact','order_exact_accuracy'):
        if name=='exact_match':return float(json.dumps(gold,sort_keys=True)==json.dumps(pred,sort_keys=True))
        return float(normalized(gold)==normalized(pred))
    raise ValueError(f'Unsupported deterministic metric {name}; provide an explicit metric plugin rather than silently using exact match')


def score_predictions(items,predictions,model='saved_predictions'):
    expected=unique([{**r,'id':identity(r)} for r in items])
    mapped=unique([{**r,'id':identity(r)} for r in predictions])
    if not expected:raise ValueError('Cannot evaluate an empty dataset')
    extra=set(mapped)-set(expected)
    if extra:raise ValueError(f'Unknown prediction IDs: {sorted(extra)}')
    scored=[]
    for iid,item in expected.items():
        response=mapped.get(iid,{})
        prediction=response.get('prediction',response.get('answer'))
        effective=prediction.get('answer') if isinstance(prediction,dict) and set(prediction)=={'answer'} and item.get('metric_id')!='json_field_accuracy' else prediction
        present=iid in mapped and effective is not None and (not isinstance(effective,str) or bool(effective.strip()))
        scored.append({'id':iid,'item_id':iid,'model':model,'prediction':prediction,
            'score':metric(item,prediction) if present else 0.0,'present':present,
            'template_id':item.get('template_id',item.get('template','unspecified')),
            'source':item.get('source',item.get('source_name',item.get('scene','unspecified'))),
            'capability_tags':item.get('capability_tags',item.get('capabilities',[])),
            'difficulty':item.get('difficulty_level','unspecified')})
    def aggregate(values):return {'items':len(values),'score':sum(v['score'] for v in values)/len(values),
                                  'missing':sum(not v['present'] for v in values)}
    groups={}
    for key in ('template_id','source','difficulty','capability_tags'):
        grouped=defaultdict(list)
        for row in scored:
            vals=row[key] if isinstance(row[key],list) else [row[key]]
            for value in vals:grouped[str(value)].append(row)
        groups[key]={k:aggregate(v) for k,v in grouped.items()}
    return {'model':model,'overall':aggregate(scored),'groups':groups,'scores':scored,
            'error_taxonomy':{'missing':sum(not r['present'] for r in scored),
                'incorrect':sum(r['present'] and r['score']==0 for r in scored),
                'partial_credit':sum(0<r['score']<1 for r in scored)}}


def evaluate(args,directory,config):
    items=rows(args['items'])
    result=score_predictions(items,rows(args['predictions']),args.get('model','saved_predictions'))
    jsonl(directory/'score_items.jsonl',result.pop('scores'))
    write(directory/'metrics.json',result)
    return {**result,'scores':str(directory/'score_items.jsonl'),'metrics':str(directory/'metrics.json')}


def public_row(row,media):
    result={'id':identity(row),'question':row['question'],'media':media}
    if row.get('options',row.get('choices')) is not None:result['choices']=row.get('options',row.get('choices'))
    result['answer_type']=row.get('answer_type','short_text')
    return result


def package(args,directory,config):
    directory.mkdir(parents=True,exist_ok=True)
    root=directory/'benchmark'
    pub=root/'public';private=root/'authority'
    (pub/'media').mkdir(parents=True);private.mkdir()
    source_items=rows(args['items']);unique([{**r,'id':identity(r)} for r in source_items])
    public=[];gold=[]
    for i,row in enumerate(source_items):
        media=row.get('media',[row['image']] if row.get('image') else [])
        if isinstance(media,str):media=[media]
        relocated=[]
        for j,value in enumerate(media):
            source=Path(value)
            if not source.is_absolute():source=Path(args['items']).resolve().parent/source
            if source.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.bmp','.gif','.mp4','.wav'):
                raise ValueError('Public media must not contain privileged arrays or label files')
            dest=pub/'media'/f'{i:06d}_{j}{source.suffix.lower()}'
            shutil.copyfile(source,dest);relocated.append(dest.relative_to(pub).as_posix())
        public.append(public_row(row,relocated))
        gold.append({**row,'id':identity(row),'media':['../public/'+p for p in relocated]})
    jsonl(pub/'items.jsonl',public);jsonl(private/'items.jsonl',gold)
    shutil.copyfile(Path(__file__),root/'score.py')
    shutil.copyfile(Path(__file__).with_name('artifacts.py'),root/'artifacts.py')
    if args.get('bundle'):
        bundle=Path(args['bundle']).resolve()
        copied=root/'reproduce'
        shutil.copytree(bundle,copied)
        # Relocate only files explicitly referenced in bundle records; no filesystem audit.
        external=copied/'inputs';external.mkdir(exist_ok=True)
        mapping={}
        def relocate(value):
            if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
            if isinstance(value,list):return [relocate(v) for v in value]
            if not isinstance(value,str):return value
            path=Path(value)
            if not path.is_absolute():
                # Original image composer can record paths relative to the
                # operation directory (bundle/image_processing/...). Normalize
                # that known prefix before renaming the copy to reproduce/.
                if value.replace('\\','/').startswith(bundle.name+'/'):
                    candidate=(bundle.parent/path).resolve()
                    if candidate.is_file():return candidate.relative_to(bundle).as_posix()
                return value
            try:return path.resolve().relative_to(bundle).as_posix()
            except ValueError:pass
            if path.is_file():
                if value not in mapping:
                    dest=external/f'input_{len(mapping):06d}{path.suffix}'
                    shutil.copyfile(path,dest);mapping[value]=dest.relative_to(copied).as_posix()
                return mapping[value]
            return value  # provenance notes may retain historical paths, never dereferenced
        for path in list(copied.rglob('*.json'))+list(copied.rglob('*.jsonl')):
            if path.suffix=='.jsonl':jsonl(path,[relocate(row) for row in rows(path)])
            else:write(path,relocate(read(path)))
        write(copied/'relocation.json',{'external_files_copied':len(mapping),'note':'Historical source path strings are provenance notes. Executable evidence/media file references are local.'})
    (root/'README.md').write_text('''# Portable benchmark

`public/` is the only model-visible input. `authority/` contains answers and audit data.

Score saved predictions (standard Python only):

    python -X utf8 score.py --items authority/items.jsonl --predictions predictions.jsonl --out metrics.json

Each prediction is `{"id":"...","answer":"..."}`. Missing predictions score zero; duplicate/unknown IDs are rejected.

When `reproduce/` exists, install NumPy and Pillow, then run the supplied generator:

    python -X utf8 reproduce/scripts/generate_items.py --bundle reproduce --evidence-index reproduce/evidence_index.jsonl --out regenerated.jsonl --limit 0 --seed 42

Replay native camera-range measurements when the source provides raw depth and calibration:

    python -X utf8 reproduce/scripts/replay_native_depth.py --bundle reproduce

The reproduction bundle includes original inputs and executable template/metric code. Keep it private during model inference. Declared template complexity and small-sample diagnostics are not empirical proof of benchmark difficulty.
''',encoding='utf-8')
    shutil.make_archive(str(directory/'benchmark-public'),'zip',pub)
    shutil.make_archive(str(directory/'benchmark-complete'),'zip',root)
    return {'public_package':str(directory/'benchmark-public.zip'),'complete_package':str(directory/'benchmark-complete.zip'),
            'public':str(pub),'authority':str(private),'count':len(public)}


def model_eval(args,directory,config):
    public=rows(args['public_items'])
    # Construct allowlisted request rows even if caller accidentally passes audit items.
    configs=config.get('models',{})
    names=args.get('models') or list(configs)
    if not names:raise ValueError('Configure named models or explicitly request baselines')
    items_path=Path(args['public_items']).resolve()
    results=[]
    for name in names:
        if name not in configs:raise ValueError(f'Model not configured: {name}')
        cfg=configs[name];predictions=[];failures=[]
        for index,row in enumerate(public):
            content=[{'type':'text','text':json.dumps(public_row(row,[]),ensure_ascii=False)+'\nReturn only the option key for a choice question (e.g. A), a number for a numeric question, or the requested JSON array/object. Do not include reasoning.'}]
            media=row.get('media',[])
            if isinstance(media,str):media=[media]
            for value in media:
                path=Path(value)
                if not path.is_absolute():path=items_path.parent/path
                mime=mimetypes.guess_type(path.name)[0] or 'image/png'
                content.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()}})
            body={'model':cfg['model'],'messages':[{'role':'user','content':content}],
                  'temperature':cfg.get('temperature',0),'max_tokens':cfg.get('max_tokens',4096),'stream':False,**cfg.get('parameters',{})}
            headers={'Content-Type':'application/json'}
            if cfg.get('token_env'):headers['Authorization']='Bearer '+os.environ[cfg['token_env']]
            url=cfg['url'].rstrip('/')
            if not url.endswith('/chat/completions'):url+=('/chat/completions' if url.endswith('/v1') else '/v1/chat/completions')
            last=None
            for attempt in range(cfg.get('retries',1)+1):
                try:
                    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers=headers)
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({})) if urllib.parse.urlsplit(url).hostname in ('localhost','127.0.0.1') else urllib.request.build_opener()
                    with opener.open(request,timeout=cfg.get('timeout_seconds',180)) as response:raw=json.load(response)
                    write(directory/f'model_{names.index(name)}/response_{index:06d}_attempt_{attempt}.json',{'id':identity(row),'model':name,'response':raw,'attempt':attempt,'images_sent':len(media)})
                    answer=raw['choices'][0]['message'].get('content') or ''
                    answer=answer.strip()
                    if not answer:raise ValueError('Model returned an empty answer; check reasoning/output token budget. Raw response retained.')
                    try:answer=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',answer))
                    except ValueError:pass
                    predictions.append({'id':identity(row),'answer':answer,'model':name})
                    write(directory/f'model_{names.index(name)}/response_{index:06d}.json',{'id':identity(row),'model':name,'response':raw,'attempt':attempt,'images_sent':len(media)})
                    last=None;break
                except (OSError,ValueError,KeyError) as exc:
                    last=str(exc)
                    if attempt<cfg.get('retries',1):time.sleep(1)
            if last:failures.append({'id':identity(row),'error':last})
        out=directory/f'model_{names.index(name)}'
        jsonl(out/'predictions.jsonl',predictions);jsonl(out/'failures.jsonl',failures)
        result={'model':name,'predictions':str(out/'predictions.jsonl'),'failed':len(failures),'completed':len(predictions),'evaluation_mode':'real_model'}
        if args.get('items'):
            score=score_predictions(rows(args['items']),predictions,name)
            jsonl(out/'score_items.jsonl',score.pop('scores'));write(out/'metrics.json',score)
            result.update(scores=str(out/'score_items.jsonl'),overall=score['overall'])
        results.append(result)
    write(directory/'models.json',results)
    return {'models':results,'status':'completed' if all(not r['failed'] for r in results) else 'incomplete'}


def baselines(args,directory,config):
    items=rows(args['items']);rng=random.Random(args.get('seed',42))
    results=[]
    for name in ('first_choice','random_choice'):
        preds=[]
        for row in items:
            choices=row.get('options',row.get('choices',{}))
            values=list(choices) if choices else []
            # Responders see only choices, never the gold answer.
            pred=(values[0] if name=='first_choice' else rng.choice(values)) if values else None
            preds.append({'id':identity(row),'answer':pred})
        score=score_predictions(items,preds,name)
        out=directory/name
        jsonl(out/'predictions.jsonl',preds);jsonl(out/'score_items.jsonl',score.pop('scores'))
        write(out/'metrics.json',score)
        results.append({'model':name,'scores':str(out/'score_items.jsonl'),'overall':score['overall']})
    return {'models':results,'evaluation_mode':'proxy','note':'Deterministic/random controls are not independent model respondents or empirical evidence of IRT validity.'}


def report(args,directory,config):
    paths=args['scores'] if isinstance(args['scores'],list) else [args['scores']]
    matrix=[r for path in paths for r in rows(path)]
    seen=set()
    for r in matrix:
        key=(r['model'],identity(r))
        if key in seen:raise ValueError(f'Duplicate model/item response {key}')
        seen.add(key)
    jsonl(directory/'score_matrix.jsonl',matrix)
    grouped=defaultdict(list)
    for row in matrix:grouped[row['model']].append(row)
    summary={k:{'items':len(v),'mean_score':sum(float(r['score']) for r in v)/len(v),
                'missing':sum(not r.get('present',True) for r in v)} for k,v in grouped.items()}
    strata={}
    for model,model_rows in grouped.items():
        strata[model]={}
        for dimension in ('template_id','source','difficulty','capability_tags'):
            groups=defaultdict(list)
            for row in model_rows:
                values=row.get(dimension,'unspecified')
                for value in values if isinstance(values,list) else [values]:groups[str(value)].append(row)
            strata[model][dimension]={key:{'items':len(value),'mean_score':sum(r['score'] for r in value)/len(value)} for key,value in groups.items()}
    write(directory/'stratified_metrics.json',strata)
    write(directory/'metrics.json',summary)
    text='# Evaluation report\n\n| Model | Items | Mean score | Missing |\n|---|---:|---:|---:|\n'
    text+=''.join(f"| {k} | {v['items']} | {v['mean_score']:.4f} | {v['missing']} |\n" for k,v in summary.items())
    text+='\nScores describe this collection only. Proxy responders and small samples do not establish model ranking or diagnostic validity.\n'
    (directory/'report.md').write_text(text,encoding='utf-8')
    return {'report':str(directory/'report.md'),'matrix':str(directory/'score_matrix.jsonl'),'strata':str(directory/'stratified_metrics.json'),'models':summary}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--items',required=True);parser.add_argument('--predictions',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args()
    result=score_predictions(rows(args.items),rows(args.predictions));write(args.out,result)
    print(json.dumps(result['overall']))
