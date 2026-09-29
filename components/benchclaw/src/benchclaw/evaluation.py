from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from sqlalchemy import select

from .domain import AnswerRecord, Contract, HarnessError, Identifier, Nonempty, Prediction, VisibleEvalItem, uid, now
from .metadata import evaluations
from .release import get_release
from .store import write_json
from .metrics import score_answer,metric_details


class ModelTarget(Contract):
    model_id: str = Field(min_length=1,max_length=256,pattern=r'^[A-Za-z0-9][A-Za-z0-9_./-]*$')
    endpoint: str
    api_key_env: str | None = Field(default=None,pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')
    timeout_seconds: int = Field(default=60,ge=1,le=43200)
    max_tokens: int = Field(default=64,ge=1,le=393216)
    enable_thinking: bool | None = None
    preserve_thinking: bool | None = None
    reasoning_effort: Literal['none','minimal','low','medium','high','xhigh'] | None = None
    thinking_token_budget: int | None = Field(default=None,ge=1,le=262144)
    temperature: float = Field(default=0,ge=0,le=2)
    top_p: float | None = Field(default=None,gt=0,le=1)
    top_k: int | None = Field(default=None,ge=0)
    min_p: float | None = Field(default=None,ge=0,le=1)
    presence_penalty: float | None = Field(default=None,ge=-2,le=2)
    repetition_penalty: float | None = Field(default=None,gt=0)
    stream: bool = False

    @model_validator(mode='after')
    def endpoint_policy(self):
        parsed=urlsplit(self.endpoint)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Endpoint must be an HTTP(S) URL without credentials or query parameters')
        if self.thinking_token_budget is not None and self.thinking_token_budget>=self.max_tokens:
            raise ValueError('Thinking budget must leave output capacity for the answer')
        return self


class Roster(Contract):
    models: list[ModelTarget] = Field(min_length=1)

    @model_validator(mode='after')
    def unique(self):
        if len({x.model_id for x in self.models})!=len(self.models):
            raise ValueError('duplicate model_id')
        return self


def score(visible:list[VisibleEvalItem], gold:list[AnswerRecord], predictions:list[Prediction], roster:Roster):
    ids={x.item_id for x in visible}
    authority={x.item_id:x for x in gold}
    if len(ids)!=len(visible) or len(authority)!=len(gold) or ids!=set(authority):
        raise HarnessError('EVALUATION_IDS','Gold and visible IDs must match uniquely')
    targets={m.model_id:m for m in roster.models}
    matrix={}
    for pred in predictions:
        key=(pred.model_id,pred.item_id)
        if key in matrix:
            raise HarnessError('DUPLICATE_PREDICTION',str(key))
        if pred.item_id not in ids or pred.model_id not in targets:
            raise HarnessError('UNKNOWN_PREDICTION_ID',str(key))
        if pred.endpoint!=targets[pred.model_id].endpoint:
            raise HarnessError('MODEL_ENDPOINT_MISMATCH',pred.model_id)
        matrix[key]=pred
    models={}
    for model in targets:
        missing=[];failed=[];scores=[];processed=0;success=0
        for iid in sorted(ids):
            pred=matrix.get((model,iid))
            if pred is None:
                missing.append(iid);scores.append(0.0);continue
            processed+=1
            if pred.status!='succeeded':
                failed.append({'item_id':iid,'code':pred.error_code});scores.append(0.0);continue
            success+=1
            scores.append(score_answer(authority[iid].gold,pred.prediction,authority[iid].rubric_id,authority[iid].metric_parameters))
        models[model]={'expected':len(ids),'processed':processed,'successful':success,
                       'coverage':success/len(ids) if ids else 0,'processed_coverage':processed/len(ids) if ids else 0,
                       'mean_score':sum(scores)/len(ids) if ids else 0,'missing':missing,'failed':failed}
    diagnostics=analyze_scores(visible,authority,matrix,targets)
    return {'models':models,**diagnostics,'complete':all(v['coverage']==1 for v in models.values()),'recomputed_from_predictions':True}


def analyze_scores(visible,authority,matrix,targets):
    from collections import defaultdict
    import importlib.util
    rows=[];grouped={};usage={}
    for model in targets:
        groups=defaultdict(list);tokens=defaultdict(int)
        for item in visible:
            a=authority[item.item_id];pred=matrix.get((model,item.item_id))
            value=score_answer(a.gold,pred.prediction,a.rubric_id,a.metric_parameters) if pred and pred.status=='succeeded' else 0.0
            row={'model':model,'item_id':item.item_id,'score':value,'template_id':a.template_id,'source_file':'database_predictions','row_index':len(rows),
                 'answer_type':item.answer_type,'capabilities':a.capability_ids or ['relative_position_2d'],
                 'response_status':pred.status if pred else 'missing'}
            rows.append(row)
            row['metrics']=metric_details(a.gold,pred.prediction,a.rubric_id,a.metric_parameters) if pred and pred.status=='succeeded' else {'score':0}
            for group in [f'template:{a.template_id}',f'answer_type:{item.answer_type}']+[f'capability:{c}' for c in row['capabilities']]:groups[group].append(value)
            if pred and isinstance(pred.raw_response,dict):
                for k,v in pred.raw_response.get('usage',{}).items():
                    if isinstance(v,int):tokens[k]+=v
        grouped[model]={k:{'items':len(v),'mean_score':sum(v)/len(v)} for k,v in groups.items()};usage[model]=dict(tokens)
        f1=[r['metrics']['f1'] for r in rows if r['model']==model and 'f1' in r['metrics']]
        if f1:grouped[model]['metric:macro_f1']={'items':len(f1),'mean_score':sum(f1)/len(f1)}
    path=Path(__file__).resolve().parents[2]/'BenchClaw/tools/cdm_irt_analysis.py'
    spec=importlib.util.spec_from_file_location('benchclaw_irt',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Failed/missing calls remain visible above; they are not respondent ability data.
    valid=[r for r in rows if r['response_status']=='succeeded']
    partial,binary=module.response_tables(valid,.5);meta=module.item_metadata(valid)
    item_rows=module.item_parameter_rows(partial,binary,meta,.1)
    status=module.analysis_status(len(partial),len(meta),len(valid),5,30)
    return {'per_item':rows,'grouped_scores':grouped,'model_usage':usage,'cdm_irt':{
        'method':'original Rasch proxy and capability mastery diagnostics; not a fitted IRT model',
        'full_irt_fitted':False,'sample_sufficiency':status,'items':item_rows,
        'model_ability':module.model_ability_rows(partial,binary),'capability_mastery':module.capability_rows(partial,binary,meta,.7)}}


def save_evaluation(repo,release_id,roster,predictions,mode,request_artifacts_uri=None):
    release,visible,gold=get_release(repo,release_id)
    report=score([VisibleEvalItem.model_validate(x) for x in visible],[AnswerRecord.model_validate(x) for x in gold],predictions,roster)
    eid=uid('eval')
    record={'evaluation_id':eid,'release_id':release_id,'created_at':now(),'mode':mode,
            'roster':roster.model_dump(mode='json'),**report}
    if request_artifacts_uri is not None:
        record['request_artifacts_uri']=str(request_artifacts_uri)
    with repo.transaction() as conn:
        conn.execute(evaluations.insert().values(id=eid,release_id=release_id,record=record,predictions=[p.model_dump(mode='json') for p in predictions]))
        repo.event(conn,release['run_id'],None,'evaluation.recorded',{'evaluation_id':eid,'complete':report['complete'],'mode':mode})
    return record


def report_evaluation(repo,eid):
    with repo.engine.connect() as conn:
        row=conn.execute(select(evaluations).where(evaluations.c.id==eid)).mappings().first()
    if not row:
        raise HarnessError('EVALUATION_NOT_FOUND',eid)
    _,visible,gold=get_release(repo,row['release_id'])
    report=score([VisibleEvalItem.model_validate(x) for x in visible],[AnswerRecord.model_validate(x) for x in gold],
                 [Prediction.model_validate(x) for x in row['predictions']],Roster.model_validate(row['record']['roster']))
    return {**row['record'],**report}


def evaluate_isolated(repo,store,release_id,roster,image='python:3.11-slim',mode='isolated_live_model'):
    release,_,_=get_release(repo,release_id)
    output=store.root/'evaluations'/uid('calls')
    output.mkdir(parents=True,mode=0o700)
    write_json(output/'roster.json',roster.model_dump(mode='json'))
    script=Path(__file__).with_name('model_worker.py')
    cmd=['docker','run','--rm','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
         '--network=host','--tmpfs','/tmp:rw,noexec,nosuid,size=16m','--user',f'{os.getuid()}:{os.getgid()}',
         '--mount',f'type=bind,src={release["visible_bundle_uri"]},dst=/model,readonly',
         '--mount',f'type=bind,src={script},dst=/worker.py,readonly',
         '--mount',f'type=bind,src={script.with_name("chat_transport.py")},dst=/chat_transport.py,readonly',
         '--mount',f'type=bind,src={output},dst=/out']
    for model in roster.models:
        if model.api_key_env:
            if model.api_key_env not in os.environ:
                raise HarnessError('MISSING_CREDENTIAL',model.api_key_env)
            cmd+=['--env',model.api_key_env]
    cmd += [image,'python','/worker.py']
    # Only model_bundle is mounted. No authority directory, DB URL or docker socket is present.
    result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                          timeout=sum(m.timeout_seconds+2 for m in roster.models)*release['item_count']+60)
    if result.returncode:
        raise HarnessError('ISOLATED_WORKER_FAILED',result.stderr[-2000:])
    rows=[Prediction.model_validate(json.loads(line)) for line in (output/'predictions.jsonl').read_text().splitlines() if line]
    return save_evaluation(repo,release_id,roster,rows,mode,request_artifacts_uri=output)
