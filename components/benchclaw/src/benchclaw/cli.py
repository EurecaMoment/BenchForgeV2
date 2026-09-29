from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from .compiler import compile_spec
from .domain import (Annotation, AnswerRecord, Bundle, DatasetSpec, Evidence, HarnessError,
                     MediaAsset, Prediction, SpatialContext, VisibleEvalItem, DataFile, SourceRecord, TemplateEvidence)
from .evaluation import Roster, evaluate_isolated, report_evaluation, save_evaluation
from .metadata import Repository
from .plugins import Registry
from .release import build_release, validate_run
from .store import ArtifactStore, write_json
from .workflow import LocalWorkflowBackend


def load(path):
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))


def load_spec(path):
    spec=DatasetSpec.model_validate(load(path))
    sources=[]
    for source in spec.sources:
        params=dict(source.parameters)
        if 'path' in params:
            params['path']=str((Path(path).resolve().parent/params['path']).resolve())
        sources.append(source.model_copy(update={'parameters':params}))
    return spec.model_copy(update={'sources':sources})


def emit(value):
    print(json.dumps(value,ensure_ascii=False,indent=2,default=str),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(prog='benchclaw',description='Deterministic embodied dataset harness')
    parser.add_argument('--home',default=os.environ.get('BENCHCLAW_HOME','.harness'))
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('plan','run'):
        p=sub.add_parser(name);p.add_argument('spec')
    p=sub.add_parser('init');p.add_argument('path')
    p=sub.add_parser('doctor');p.add_argument('--spec')
    p=sub.add_parser('plugins');p.add_argument('action',choices=['list','inspect','probe']);p.add_argument('plugin',nargs='?');p.add_argument('--parameters')
    for name in ('status','logs','resume','cancel','release','review'):
        p=sub.add_parser(name);p.add_argument('run_id')
    p=sub.add_parser('retry');p.add_argument('run_id');p.add_argument('--task')
    p=sub.add_parser('validate');p.add_argument('run_id');p.add_argument('--policy',choices=['development-v1','production-v1'])
    p=sub.add_parser('evaluate');p.add_argument('release_id');p.add_argument('--roster',required=True);p.add_argument('--predictions');p.add_argument('--image',default='python:3.11-slim')
    p=sub.add_parser('report');p.add_argument('evaluation_id')
    sub.add_parser('catalogue',help='Show executable templates, metrics and registered capabilities')
    p=sub.add_parser('pilot',help='Run an explicit small recipe through quality gates and roster evaluation')
    p.add_argument('spec');p.add_argument('--roster',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('schemas');p.add_argument('directory')
    p=sub.add_parser('training',help='Generate reviewed SFT data; never run benchmark evaluation')
    train=p.add_subparsers(dest='training_action',required=True)
    p=train.add_parser('run');p.add_argument('spec')
    p=train.add_parser('export');p.add_argument('run_id')
    p=sub.add_parser('agent',help='Run a bounded local Qwen workflow from a natural-language request')
    agent=p.add_subparsers(dest='agent_action',required=True)
    for action in ('plan','run'):
        a=agent.add_parser(action);a.add_argument('--profile',required=True)
        request=a.add_mutually_exclusive_group(required=True)
        request.add_argument('--request');request.add_argument('--request-file')
        a.add_argument('--image',help='Explicit user-selected local RGB image, overriding the single source image')
    for action in ('resume','status','export'):
        a=agent.add_parser(action);a.add_argument('session_id')
        if action=='export':
            a.add_argument('path')
    types={c.__name__:c for c in (DatasetSpec,MediaAsset,DataFile,SourceRecord,SpatialContext,Annotation,Evidence,TemplateEvidence,VisibleEvalItem,AnswerRecord,Prediction,Bundle)}
    p=sub.add_parser('validate-record');p.add_argument('type',choices=types);p.add_argument('path')
    args=parser.parse_args(argv)
    try:
        registry=Registry()
        if args.command=='catalogue':
            from .template_engine import catalogue
            emit({'templates':catalogue(),'plugins':[p.describe().model_dump() for p in registry.plugins.values()],
                  'answer_types':['single_choice','multi_choice','ordering','numeric','interval','json','text'],
                  'execution':'DatasetSpec -> deterministic DAG -> database state -> validated release -> isolated evaluation'})
            return 0
        if args.command=='schemas':
            for name,model in types.items():
                write_json(Path(args.directory)/f'{name}.schema.json',model.model_json_schema())
            emit({'schemas':list(types)});return 0
        if args.command=='validate-record':
            model=types[args.type]
            content=Path(args.path).read_text()
            records=[json.loads(line) for line in content.splitlines() if line] if args.path.endswith('.jsonl') else [json.loads(content)]
            for record in records:
                model.model_validate(record)
            emit({'valid':True,'count':len(records)});return 0
        if args.command=='init':
            source=Path(__file__).resolve().parents[2]/'examples/minimal/dataset.yaml'
            target=Path(args.path)
            if target.exists():
                raise HarnessError('FILE_EXISTS',str(target))
            spec=load_spec(source)
            target.write_text(yaml.safe_dump(spec.model_dump(mode='json'),allow_unicode=True,sort_keys=False),encoding='utf-8')
            emit({'path':str(target.resolve())});return 0
        if args.command=='plugins':
            if args.action=='list':
                emit([p.describe().model_dump() for p in registry.plugins.values()]);return 0
            plugin=registry.get(args.plugin)
            if args.action=='inspect':
                emit(plugin.describe().model_dump());return 0
            params=load(args.parameters) if args.parameters else {}
            plugin.validate_parameters(params)
            health=plugin.healthcheck(params)
            emit({'probe':'readiness','functional_execution':False,**health.model_dump()})
            return 0 if health.ready else 2
        if args.command=='plan':
            emit(compile_spec(load_spec(args.spec),registry).model_dump(mode='json'));return 0
        home=Path(args.home).resolve();home.mkdir(parents=True,exist_ok=True)
        repo=Repository(os.environ.get('BENCHCLAW_DATABASE_URL',f'sqlite:///{home}/metadata.sqlite3'))
        store=ArtifactStore(home/'artifacts')
        backend=LocalWorkflowBackend(repo,store,registry)
        if args.command=='training':
            from .training import build_training_release
            if args.training_action=='run':
                spec=load_spec(args.spec)
                if spec.purpose!='training':raise HarnessError('TRAINING_PURPOSE','Spec must declare purpose: training')
                run_id=backend.submit(spec);emit({'run_id':run_id,'purpose':'training'})
                result=backend.resume(run_id)
                if result['state']!='SUCCEEDED':emit({'run_id':run_id,'state':result['state']});return 2
            else:run_id=args.run_id
            emit(build_training_release(repo,store,run_id));return 0
        if args.command=='pilot':
            spec=load_spec(args.spec)
            if spec.quality_policy!='development-v1':raise HarnessError('PILOT_POLICY','Pilot requires a development recipe')
            run_id=backend.submit(spec);result=backend.resume(run_id)
            if result['state']!='SUCCEEDED':
                emit({'run_id':run_id,'state':result['state']});return 2
            release=build_release(repo,store,run_id)
            report=evaluate_isolated(repo,store,release['release_id'],Roster.model_validate(load(args.roster)))
            write_json(Path(args.output),{'run_id':run_id,'release':release,'evaluation':report,'promotion':'requires review of pilot findings and a separate explicit full recipe'})
            emit({'run_id':run_id,'release_id':release['release_id'],'evaluation_id':report['evaluation_id'],'complete':report['complete'],'report':args.output})
            return 0 if report['complete'] else 2
        if args.command=='agent':
            from .local_agent import AgentProfile,LocalAgent,public_status
            local=LocalAgent(repo,store)
            if args.agent_action in {'run','plan'}:
                profile_path=Path(args.profile).resolve()
                profile=AgentProfile.model_validate(load(profile_path))
                template_path=(profile_path.parent/profile.template).resolve()
                profile=profile.model_copy(update={'template':str(template_path)})
                template=load_spec(template_path)
                if args.image:
                    image=Path(args.image).resolve(strict=True)
                    if len(template.sources)!=1 or template.sources[0].plugin!='source.default_annotation':
                        raise HarnessError('AGENT_IMAGE_OVERRIDE','Image override requires one default_annotation source')
                    source=template.sources[0]
                    params={**source.parameters,'path':str(image.parent),'image':image.name,'source_uri':image.as_uri(),
                            'license_id':'unverified','review_status':'needs_human_review'}
                    template=DatasetSpec.model_validate({**template.model_dump(),'sources':[source.model_copy(update={'parameters':params}).model_dump()]})
                request=Path(args.request_file).read_text(encoding='utf-8') if args.request_file else args.request
                sid=local.create(request,profile,template)
                emit({'session_id':sid,'state':'PLANNING','model':profile.model.model_id})
                result=local.advance(sid,execute=args.agent_action=='run')
            elif args.agent_action=='resume':
                result=local.advance(args.session_id)
            else:
                result=local.status(args.session_id)
                if args.agent_action=='export':
                    write_json(Path(args.path),result)
            emit(public_status(result))
            return 0 if result['state'] in {'COMPLETE','PLANNED'} or args.agent_action in {'status','export'} else 2
        if args.command=='doctor':
            checks={'python':sys.version.split()[0],'database':repo.engine.dialect.name,'artifact_store':str(store.root),'plugins':len(registry.plugins),'ready':True}
            if args.spec:
                spec=load_spec(args.spec);compile_spec(spec,registry)
                checks['sources']={s.source_id:registry.get(s.plugin).healthcheck(s.parameters).model_dump() for s in spec.sources}
                checks['ready']=all(v['ready'] for v in checks['sources'].values())
                if spec.quality_policy=='production-v1' and repo.engine.dialect.name!='postgresql':
                    checks.update(ready=False,error='PRODUCTION_REQUIRES_POSTGRESQL')
            emit(checks);return 0 if checks['ready'] else 2
        if args.command=='run':
            spec=load_spec(args.spec)
            if spec.quality_policy=='production-v1' and repo.engine.dialect.name!='postgresql':
                raise HarnessError('PRODUCTION_REQUIRES_POSTGRESQL','SQLite is development-only')
            run_id=backend.submit(spec)
            result=backend.resume(run_id)
            emit({'run_id':run_id,'state':result['state'],'tasks':[{k:t[k] for k in ('task_id','state','attempt','failure')} for t in result['tasks']]})
            return 0 if result['state']=='SUCCEEDED' else 2
        if args.command=='status':
            result=backend.status(args.run_id)
            emit({'run_id':args.run_id,'state':result['state'],'tasks':[{k:t[k] for k in ('task_id','state','attempt','failure','lease_expires_at')} for t in result['tasks']]});return 0
        if args.command=='logs':
            emit(repo.logs(args.run_id));return 0
        if args.command=='cancel':
            backend.cancel(args.run_id);emit({'state':'CANCELED'});return 0
        if args.command=='retry':
            backend.retry(args.run_id,args.task)
        if args.command in {'resume','retry'}:
            result=backend.resume(args.run_id);emit({'run_id':args.run_id,'state':result['state']});return 0 if result['state']=='SUCCEEDED' else 2
        if args.command=='validate':
            result=validate_run(repo,store,args.run_id,args.policy);emit(result);return 0 if result['passed'] else 2
        if args.command=='release':
            emit(build_release(repo,store,args.run_id));return 0
        if args.command=='review':
            emit([{'task_id':t['task_id'],'issues':t['result'].get('issues',[]),'failure':t['failure']} for t in repo.status(args.run_id)['tasks'] if t['state']=='QUARANTINED']);return 0
        if args.command=='evaluate':
            roster=Roster.model_validate(load(args.roster))
            if args.predictions:
                preds=[Prediction.model_validate(json.loads(line)) for line in Path(args.predictions).read_text().splitlines() if line]
                result=save_evaluation(repo,args.release_id,roster,preds,'imported_predictions_unverified_origin')
            else:
                result=evaluate_isolated(repo,store,args.release_id,roster,args.image)
            emit(result);return 0 if result['complete'] else 2
        if args.command=='report':
            emit(report_evaluation(repo,args.evaluation_id));return 0
    except (HarnessError,ValidationError,ValueError,OSError,KeyError) as exc:
        if isinstance(exc,HarnessError):
            failure=exc.failure.model_dump()
        else:
            failure={'code':'VALIDATION_ERROR' if isinstance(exc,(ValidationError,ValueError,KeyError)) else 'IO_ERROR','message':str(exc)}
        emit({'status':'failed','failure':failure});return 2


if __name__=='__main__':
    raise SystemExit(main())
