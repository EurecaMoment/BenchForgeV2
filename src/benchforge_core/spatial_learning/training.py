"""Windowed local-model SFT with real development feedback and resumable state.

No provider endpoint is used: inference and parameter updates use the selected
checkpoint. Optional backend imports are deferred until training starts.
"""
import json
import random
import time
import subprocess
import sys
import os
from collections import defaultdict
from pathlib import Path
from .curriculum import allocate,update_state
from .evaluation import read_rows
from .generation import write_json
from .monitor import emit
from .scoring import score
from .environments import environment


class TransformersSolver:
    def __init__(self,config):
        import torch
        import transformers
        self.torch=torch;self.config=config;self.multimodal=config.get('multimodal',False)
        model=config['model'];kwargs={'local_files_only':config.get('local_files_only',True)}
        self.device=config.get('device','cpu')
        if self.multimodal:
            self.processor=transformers.AutoProcessor.from_pretrained(model,**kwargs)
            self.model=transformers.AutoModelForImageTextToText.from_pretrained(model,**kwargs)
            self.tokenizer=self.processor.tokenizer
        else:
            self.tokenizer=transformers.AutoTokenizer.from_pretrained(model,**kwargs)
            self.model=transformers.AutoModelForCausalLM.from_pretrained(model,**kwargs)
        if self.tokenizer.pad_token_id is None:self.tokenizer.pad_token=self.tokenizer.eos_token
        if config.get('lora'):
            from peft import LoraConfig,get_peft_model
            self.model=get_peft_model(self.model,LoraConfig(task_type='CAUSAL_LM',**config['lora']))
        self.model.to(self.device)
        self.optimizer=torch.optim.AdamW((p for p in self.model.parameters() if p.requires_grad),lr=config.get('learning_rate',2e-5))
        self.max_length=config.get('max_length',2048)

    def encode(self,messages,images,assistant=False):
        from PIL import Image
        if images and not self.multimodal:raise ValueError('This dataset has images; select a multimodal checkpoint or a structured-only task subset')
        if self.multimodal:
            messages=[dict(m) for m in messages]
            messages[0]['content']=[*[{'type':'image'} for _ in images],{'type':'text','text':messages[0]['content']}]
            text=self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=assistant)
            pixels=[Image.open(p).convert('RGB') for p in images]
            encoded=self.processor(text=[text],images=pixels or None,return_tensors='pt')
            for image in pixels:image.close()
        else:
            text=self.tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=assistant)
            encoded=self.tokenizer(text,return_tensors='pt',add_special_tokens=False)
        if encoded['input_ids'].shape[1]>self.max_length:raise ValueError('Sample exceeds max_length; increase the configured limit or shorten its actual evidence')
        return {k:v.to(self.device) for k,v in encoded.items()}

    def update(self,records):
        self.model.train();self.optimizer.zero_grad();losses=[];tokens=0;input_tokens=0
        for record in records:
            messages=record['messages'];images=record.get('images',[])
            encoded=self.encode(messages,images);prefix=self.encode(messages[:-1],images,assistant=True)
            labels=encoded['input_ids'].clone();labels[:,:prefix['input_ids'].shape[1]]=-100
            input_tokens+=int(encoded['input_ids'].numel())
            tokens+=int((labels!=-100).sum().item())
            if not (labels!=-100).any():raise ValueError('No assistant training tokens')
            loss=self.model(**encoded,labels=labels).loss
            (loss/len(records)).backward();losses.append(float(loss.detach().cpu()))
        self.torch.nn.utils.clip_grad_norm_(self.model.parameters(),self.config.get('max_grad_norm',1.))
        self.optimizer.step();return {'loss':sum(losses)/len(losses),'supervised_tokens':tokens,'input_tokens':input_tokens,'examples':len(records)}

    def predict(self,question):
        self.model.eval();messages=[{'role':'user','content':question['question']+'\n'+json.dumps(question['inputs'],ensure_ascii=False)}]
        encoded=self.encode(messages,question.get('images',[]),assistant=True)
        with self.torch.no_grad():generated=self.model.generate(**encoded,max_new_tokens=self.config.get('max_new_tokens',256),do_sample=False,pad_token_id=self.tokenizer.pad_token_id)
        return self.tokenizer.decode(generated[0,encoded['input_ids'].shape[1]:],skip_special_tokens=True)

    def save(self,path):
        path=Path(path);path.mkdir(parents=True,exist_ok=True)
        self.model.save_pretrained(path);(self.processor if self.multimodal else self.tokenizer).save_pretrained(path)
        self.torch.save({'model':self.model.state_dict(),'optimizer':self.optimizer.state_dict(),'torch_rng':self.torch.get_rng_state(),
                        'cuda_rng':self.torch.cuda.get_rng_state_all() if self.torch.cuda.is_available() else None},path/'training-state.pt')

    def restore(self,path):
        state=self.torch.load(Path(path)/'training-state.pt',map_location=self.device,weights_only=False)
        self.model.load_state_dict(state['model']);self.optimizer.load_state_dict(state['optimizer']);self.torch.set_rng_state(state['torch_rng'].cpu())
        if state['cuda_rng'] is not None:self.torch.cuda.set_rng_state_all(state['cuda_rng'])


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
            guidance_path=root/'guidance.json'
            guidance=json.loads(guidance_path.read_text(encoding='utf8')) if guidance_path.exists() else {}
            if guidance.get('pause'):emit(root,'paused',step=step)
            while guidance.get('pause'):
                time.sleep(.5);guidance=json.loads(guidance_path.read_text(encoding='utf8'))
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


def train(args,directory,config=None):
    if args.get('action')=='start':
        run_dir=Path(args.get('run',Path(directory)/'training')).resolve();run_dir.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-m','benchforge_core.spatial_learning.training','--config',str(Path(args['config']).resolve()),'--run',str(run_dir)]
        with (run_dir/'process.log').open('ab') as log:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
        result={'pid':process.pid,'run':str(run_dir),'log':str(run_dir/'process.log')};write_json(run_dir/'job.json',result)
        return result
    settings=json.loads(Path(args['config']).read_text(encoding='utf8'))
    return run(settings,args.get('run',Path(directory)/'training'))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--run',required=True)
    args=parser.parse_args();print(json.dumps(train(vars(args),Path(args.run))))
