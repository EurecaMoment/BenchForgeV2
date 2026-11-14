"""Windowed local-model SFT with real development feedback and resumable state.

No provider endpoint is used: inference and parameter updates use the selected
checkpoint. Optional backend imports are deferred until training starts.
"""
import json
import os
import random
import time
import sys
import subprocess
import uuid
from collections import defaultdict
from pathlib import Path
from pipelines.spatial_learning.curriculum import allocate
from pipelines.spatial_learning.curriculum import update_state
from capabilities.evaluation.spatial.evaluation import read_rows
from capabilities.dataset_authoring.spatial.generation import write_json
from capabilities.training.solver import TransformersSolver
from capabilities.evaluation.spatial.scoring import score
from capabilities.dataset_authoring.spatial.environments import environment
from storage.training_runs import emit
from storage.training_runs import read_guidance


def development(solver,questions,truths,limit=None):
    rows=[]
    for question in questions[:limit] if limit else questions:
        start=time.monotonic();truth=truths[question['id']]
        if truth['scorer']=='environment':
            env=environment(truth['scene'],question['capabilities'][0],question['template_id'].split('.')[1]);parse_ok=True
            for _ in range(40):
                observation=env.observation()
                if question.get('assistance'):observation['assistance']=question['assistance']
                if question.get('assistance',{}).get('next_action_available'):observation['next_action']=env.expert_action()
                prompt={**question,'inputs':observation,'images':[]}
                try:
                    prediction=json.loads(solver.predict(prompt));response=env.step(prediction)
                except (ValueError,TypeError,KeyError,StopIteration):parse_ok=False;break
                if response['done']:break
            measured={'success':env.success(),'parse_ok':parse_ok,'score':float(env.success()),'error':None if env.success() else 'environment_goal_incomplete'}
        else:measured=score(truth,solver.predict(question))
        rows.append({**{k:question[k] for k in ['id','template_id','capabilities','scene_group','partition','input_mode','difficulty','condition']},
                     **measured,'cost':time.monotonic()-start})
    return rows


def resolve_media(rows,dataset):
    return [{**row,'images':[str((dataset/p).resolve()) for p in row.get('images',[])]} for row in rows]


def capability_scores(rows):
    bins=defaultdict(list)
    for row in rows:
        if row.get('condition','natural')=='natural':
            for cap in row['capabilities']:bins[cap].append(float(row['success']))
    return {cap:sum(v)/len(v) for cap,v in bins.items()}


def select_record(rows,recommendation,rng):
    assisted=rng.random()<recommendation['hint_fraction']
    condition='supplied_intermediate' if assisted else 'natural'
    eligible=[r for r in rows if r.get('condition','natural')==condition and r.get('difficulty',1)==recommendation['difficulty']]
    if not eligible:eligible=[r for r in rows if r.get('condition','natural')==condition]
    return rng.choice(eligible or rows)


def run(config,run_directory,solver=None):
    root=Path(run_directory);root.mkdir(parents=True,exist_ok=True);dataset=Path(config['dataset'])
    rng=random.Random(config.get('seed',11));condition=config.get('condition','C')
    training=resolve_media(read_rows(dataset/'train/sft.jsonl'),dataset);by_template=defaultdict(list)
    for row in training:by_template[row['template_id']].append(row)
    dev=resolve_media(read_rows(dataset/'curriculum_dev/questions.jsonl'),dataset);selection=resolve_media(read_rows(dataset/'selection_dev/questions.jsonl'),dataset)
    dev_truth={r['id']:r for r in read_rows(dataset/'curriculum_dev/authority.jsonl')};selection_truth={r['id']:r for r in read_rows(dataset/'selection_dev/authority.jsonl')}
    enabled=set(config.get('template_ids',by_template));by_template={k:v for k,v in by_template.items() if k in enabled}
    dev=[q for q in dev if q['template_id'] in enabled];selection=[q for q in selection if q['template_id'] in enabled]
    if not by_template or not dev or not selection:raise ValueError('Training needs nonempty train, curriculum_dev and selection_dev in the selected task pool')
    # A fixed, stratified development sample is reused across windows and arms.
    def sample_dev(rows,limit):
        buckets=defaultdict(list)
        for row in rows:buckets[(row['capabilities'][0],row['condition'])].append(row)
        for values in buckets.values():rng.shuffle(values)
        ordered=[]
        while any(buckets.values()):
            for values in buckets.values():
                if values:ordered.append(values.pop())
        return ordered[:limit] if limit else ordered
    dev=sample_dev(dev,config.get('dev_limit'));selection=sample_dev(selection,config.get('selection_limit'))
    solver=solver or TransformersSolver(config);state={'config':config.get('curriculum',{})};step=0;start_window=0
    if config.get('resume'):
        resume=Path(config['resume']);solver.restore(resume)
        saved=json.loads((resume/'run-state.json').read_text(encoding='utf8'));state=saved['curriculum'];step=saved['step'];start_window=saved['next_window']
        def tuple_tree(value):return tuple(tuple_tree(v) for v in value) if isinstance(value,list) else value
        rng.setstate(tuple_tree(saved['sampler_state']))
        if saved['accepted_checkpoint']!=str(resume):solver.restore(saved['accepted_checkpoint'])
    else:
        emit(root,'baseline_started',condition=condition,model=config.get('model'),backend=config.get('backend','transformers'))
        baseline=development(solver,dev,dev_truth)
        state=update_state(state,baseline,'base','baseline')
    reference=saved['reference_selection'] if config.get('resume') else development(solver,selection,selection_truth)
    reference_caps=capability_scores(reference);reference_score=sum(reference_caps.values())/len(reference_caps)
    accepted=Path(saved['accepted_checkpoint']) if config.get('resume') else root/'base'
    if not config.get('resume'):solver.save(accepted)
    write_json(root/'config.json',config)
    def save_state(path,next_window):
        write_json(path/'run-state.json',{'curriculum':state,'step':step,'next_window':next_window,'sampler_state':rng.getstate(),
            'accepted_checkpoint':str(accepted.resolve()),'reference_selection':reference,'reference_selection_score':reference_score})
    save_state(accepted,start_window)
    emit(root,'development',window='baseline',mastery=state['mastery'],selection_score=reference_score)
    for window in range(start_window,config.get('windows',3)):
        batches=config.get('steps_per_window',20);batch_size=config.get('batch_size',1)
        categories={tid:'interactive' if rows[0].get('input_mode')=='interactive' else 'joint' if any(len(r['capabilities'])>1 for r in rows) else 'single' for tid,rows in by_template.items()}
        stages=config.get('stages',[]);stage=stages[min(window,len(stages)-1)] if stages else None
        allocation=allocate(state,batches*batch_size,condition,list(by_template),seed=config.get('seed',11)+window,categories=categories,stage=stage)
        recommendations={r['template_id']:r for r in allocation['allocation']}
        if condition=='A':
            for row in recommendations.values():row.update(hint_fraction=config.get('fixed_hint_fraction',.5),difficulty=1+window%3)
        plan=[row['template_id'] for row in allocation['allocation'] for _ in range(row['count'])];rng.shuffle(plan)
        applied_guidance=None
        write_json(root/f'window_{window}/allocation.json',allocation)
        emit(root,'allocation',window=window,condition=condition,counts={r['template_id']:r['count'] for r in allocation['allocation'] if r['count']})
        for offset in range(0,len(plan),batch_size):
            guidance=read_guidance(root)
            if guidance.get('pause'):emit(root,'paused',step=step)
            while guidance.get('pause'):
                time.sleep(.5);guidance=read_guidance(root)
            if guidance!=applied_guidance and guidance:
                emit(root,'guidance_applied',step=step,settings=guidance);applied_guidance=guidance
            if 'learning_rate' in guidance:
                for group in solver.optimizer.param_groups:group['lr']=guidance['learning_rate']
            for recommendation in recommendations.values():
                for key in ['hint_fraction','difficulty']:
                    if key in guidance:recommendation[key]=guidance[key]
            batch=[select_record(by_template[t],recommendations[t],rng) for t in plan[offset:offset+batch_size]];started=time.monotonic();metrics=solver.update(batch);step+=1
            elapsed=time.monotonic()-started
            for row in batch:state.setdefault('training_cost',{})[row['template_id']]=elapsed/len(batch)
            emit(root,'update',window=window,step=step,seconds=elapsed,conditions=[r.get('condition','natural') for r in batch],difficulty=[r.get('difficulty',1) for r in batch],categories=[categories[r['template_id']] for r in batch],**metrics)
        checkpoint=root/f'window_{window}/checkpoint';solver.save(checkpoint)
        feedback=development(solver,dev,dev_truth)
        candidate=update_state(state,feedback,str(checkpoint),f'window_{window}')
        selected=development(solver,selection,selection_truth);candidate_caps=capability_scores(selected);selected_score=sum(candidate_caps.values())/len(candidate_caps)
        retention={cap:candidate_caps[cap]-value for cap,value in reference_caps.items()}
        rollback=any(drop < -state['config']['retention_drop'] for drop in retention.values())
        if rollback:
            solver.restore(accepted);emit(root,'rollback',window=window,reference_score=reference_score,candidate_score=selected_score)
        else:
            state=candidate;accepted=checkpoint
            # Retention uses the initial reference, not an ever-lowering moving reference.
            emit(root,'checkpoint_accepted',window=window,checkpoint=str(checkpoint),selection_score=selected_score)
        emit(root,'retention',window=window,by_capability=retention)
        save_state(checkpoint,window+1)
        save_state(accepted,window+1)
        write_json(root/'state.json',state)
        (root/f'window_{window}/feedback.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in feedback),encoding='utf8')
        emit(root,'development',window=window,mastery=candidate['mastery'],selection_score=selected_score,accepted=not rollback)
        if guidance.get('stop_after_window'):
            emit(root,'stopped_after_window',window=window,checkpoint=str(accepted));break
    emit(root,'completed',step=step,checkpoint=str(accepted),sealed_test_used=False)
    return {'run':str(root),'checkpoint':str(accepted),'steps':step,'state':str(root/'state.json'),'events':str(root/'events.jsonl'),'sealed_test_used':False}


def _start_training_process(command, *, cwd, log, env=None):
    """Keep background jobs outside a managed tool's cancellation scope.

    Ordinary CLI use keeps the existing detached-process behavior. Inside DSH,
    a user service owns the new job before the short-lived CLI returns.
    """
    cwd = str(Path(cwd).resolve())
    log = Path(log).resolve()
    environment = {**os.environ, **(env or {})}
    managed = environment.pop('BENCHFORGE_MANAGED_SUBPROCESS', None) == '1'
    if managed and os.name != 'nt':
        service = 'benchforge-job-' + uuid.uuid4().hex[:12] + '.service'
        request = ['systemd-run', '--user', '--collect', '--quiet', '--unit=' + service,
                   '--property=Type=exec', '--working-directory=' + cwd,
                   '--property=StandardInput=null', '--property=StandardOutput=append:' + str(log),
                   '--property=StandardError=append:' + str(log)]
        request.extend('--setenv=' + key + '=' + value for key, value in environment.items())
        launch = subprocess.run([*request, '--', *command], capture_output=True, text=True)
        if launch.returncode:
            raise RuntimeError('Background service could not start: ' + launch.stderr.strip())
        pid = int(subprocess.check_output(['systemctl', '--user', 'show', service,
                                          '--property=MainPID', '--value'], text=True).strip())
        return {'pid': pid, 'service': service, 'owner': 'systemd-user'}
    kwargs = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    with log.open('ab') as output:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, **kwargs)
    return {'pid': process.pid, 'owner': 'detached-process'}


def train(args,directory,config=None):
    if args.get('action')=='start':
        run_dir=Path(args.get('run',Path(directory)/'training')).resolve();run_dir.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-m','pipelines.spatial_learning.training','--config',str(Path(args['config']).resolve()),'--run',str(run_dir)]
        process=_start_training_process(command,cwd=Path.cwd(),log=run_dir/'process.log')
        result={**process,'run':str(run_dir),'log':str(run_dir/'process.log')};write_json(run_dir/'job.json',result)
        return result
    settings=json.loads(Path(args['config']).read_text(encoding='utf8'))
    return run(settings,args.get('run',Path(directory)/'training'))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--run',required=True)
    args=parser.parse_args();print(json.dumps(train(vars(args),Path(args.run))))
