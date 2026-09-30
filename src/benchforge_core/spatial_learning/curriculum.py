"""Observed, condition-specific mastery and cost-aware branch curricula."""
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from .registry import graph,templates
from .generation import write_json

DEFAULTS={'promotion_success':.9,'joint_success':.8,'parse_rate':.99,'retention_drop':.03,
          'promotion_windows':2,'min_scenes':20,'min_samples':100,'coverage_floor':.1,'retention_fraction':.25,
          'alpha':1.,'beta':2.,'gamma':.5,'delta':.5,'threshold_status':'provisional_until_baseline_calibration'}
STAGE_FRACTIONS={'S1':(.85,.15,0),'S2':(.6,.4,0),'S3':(.3,.6,.1),'S4':(.25,.25,.5),'S5':(.25,.15,.6)}


def condition_key(row):
    return '|'.join([row['template_id'],row.get('input_mode','structured'),row.get('condition','natural'),str(row.get('difficulty',1))])


def summarize(rows):
    bins=defaultdict(list)
    for row in rows:
        if row['partition'] not in ['curriculum_dev','selection_dev']:raise ValueError('Curriculum feedback must come from development partitions')
        bins[condition_key(row)].append(row)
    result={}
    for key,values in bins.items():
        groups=defaultdict(list)
        for row in values:groups[row['scene_group']].append(float(row['success']))
        means=[sum(v)/len(v) for v in groups.values()]
        mean=sum(means)/len(means);se=(sum((v-mean)**2 for v in means)/(len(means)-1)/len(means))**.5 if len(means)>1 else None
        result[key]={'template_id':values[0]['template_id'],'capabilities':values[0]['capabilities'],
            'input_mode':values[0].get('input_mode','structured'),'condition':values[0].get('condition','natural'),
            'difficulty':values[0].get('difficulty',1),'success_rate':mean,'sample_count':len(values),'scene_count':len(groups),
            'parse_rate':sum(r.get('parse_ok',True) for r in values)/len(values),'standard_error_by_scene':se,
            'average_cost':sum(r.get('cost',1) for r in values)/len(values),'error_counts':dict((e,sum(r.get('error')==e for r in values)) for e in {r.get('error') for r in values} if e)}
    return result


def update_state(state,observations,checkpoint,window_id):
    if window_id in state.get('windows',[]):return state
    current=summarize(observations);cfg={**DEFAULTS,**state.get('config',{})};previous=state.get('mastery',{});reference=state.get('reference',{})
    for key,row in current.items():
        old=previous.get(key,{})
        row['recent_gain']=max(0,row['success_rate']-old.get('success_rate',row['success_rate']))
        row['regression']=max(0,reference.get(key,row['success_rate'])-row['success_rate'])
        eligible=row['condition']=='natural' and row['parse_rate']>=cfg['parse_rate'] and row['scene_count']>=cfg['min_scenes'] and row['sample_count']>=cfg['min_samples']
        threshold=cfg['joint_success'] if len(row['capabilities'])>1 else cfg['promotion_success']
        row['passing_windows']=(old.get('passing_windows',0)+1) if eligible and row['success_rate']>=threshold else 0
        row['promote']=row['passing_windows']>=cfg['promotion_windows']
        row['hint_fraction']=0 if row['promote'] else .2 if row['success_rate']>=.8 else .5 if row['success_rate']>=.5 else 1.
        row['checkpoint']=checkpoint;row['window']=window_id
        if key not in reference:reference[key]=row['success_rate']
    return {**state,'config':cfg,'mastery':{**previous,**current},'reference':reference,'checkpoint':checkpoint,
            'windows':state.get('windows',[])+[window_id]}


def allocate(state,budget,condition='C',eligible_ids=None,seed=None,categories=None,stage=None):
    cfg={**DEFAULTS,**state.get('config',{})};mastery=state.get('mastery',{});pool=templates()
    if eligible_ids is not None:pool=[t for t in pool if t['id'] in eligible_ids]
    if not pool:raise ValueError('No eligible training templates')
    by_template=defaultdict(list)
    for row in mastery.values():by_template[row['template_id']].append(row)
    deficits=defaultdict(float)
    if condition=='C':
        caps=defaultdict(list)
        for row in mastery.values():
            if row['condition']=='natural':
                for n in row['capabilities']:caps[n].append(row['success_rate'])
        for edge in graph()['edges']:
            if edge['target'] in caps: deficits[edge['source']]=max(deficits[edge['source']],1-sum(caps[edge['target']])/len(caps[edge['target']]))
    weights=[];reasons={}
    for t in pool:
        measured=[r for r in by_template[t['id']] if r['condition']=='natural']
        row=max(measured,key=lambda r:r['difficulty']) if measured else {}
        m=row.get('success_rate',.5);gain=row.get('recent_gain',0);drop=row.get('regression',0);coverage=max(0,1-row.get('scene_count',0)/cfg['min_scenes'])
        learnable=max(.1,1-abs(m-.55)/.55);cost=max(.01,state.get('training_cost',{}).get(t['id'],row.get('average_cost',1)))
        priority=1 if condition=='A' else (learnable+cfg['alpha']*gain+cfg['beta']*drop+cfg['gamma']*coverage+cfg['delta']*max((deficits[n] for n in t['primary_capabilities']),default=0))/math.sqrt(cost)
        if condition!='A' and m>=cfg['promotion_success']:priority=max(priority,cfg['retention_fraction'])
        weights.append(priority);reasons[t['id']]={'success_rate':row.get('success_rate'),'recent_gain':gain,'regression':drop,'coverage_gap':coverage,'cost':cost,
            'downstream_deficit':max((deficits[n] for n in t['primary_capabilities']),default=0),'hint_fraction':row.get('hint_fraction',0),
            'difficulty':min(3,row.get('difficulty',1)+int(row.get('promote',False))),'decision':'repair_format' if row.get('parse_rate',1)<cfg['parse_rate'] else 'retention' if drop>cfg['retention_drop'] else 'promote' if row.get('promote') else 'practice'}
    # Sampling does not break equal priorities by catalog order. Reserve one
    # rotating sample per ability when the budget permits, then sample weights.
    total=sum(weights);fractions=[cfg['coverage_floor']/len(pool)+(1-cfg['coverage_floor'])*w/total for w in weights]
    rng=random.Random(seed if seed is not None else len(state.get('windows',[])))
    quotas=[0]*len(pool);by_cap=defaultdict(list)
    for i,t in enumerate(pool):by_cap[t['primary_capabilities'][0]].append(i)
    capabilities=list(by_cap);rng.shuffle(capabilities)
    for cap in capabilities[:budget]:
        choices=by_cap[cap];i=rng.choices(choices,weights=[fractions[j] for j in choices])[0];quotas[i]+=1
    for i in rng.choices(range(len(pool)),weights=fractions,k=budget-sum(quotas)):quotas[i]+=1
    if stage:
        category_ids={kind:[i for i,t in enumerate(pool) if categories[t['id']]==kind] for kind in ['single','joint','interactive']}
        requested=STAGE_FRACTIONS[stage];available=sum(f for kind,f in zip(category_ids,requested) if category_ids[kind])
        if available==0:raise ValueError('The selected stage has no available task category')
        quotas=[0]*len(pool)
        # Convert cost shares to example counts with observed per-template update
        # costs. The realized cost shares are logged for calibration next window.
        stage_weights=[fractions[i]*requested[['single','joint','interactive'].index(categories[t['id']])] for i,t in enumerate(pool)]
        for kind,f in zip(category_ids,requested):
            indices=category_ids[kind]
            if not indices or not f:continue
            normalizer=sum(fractions[i] for i in indices)
            for i in indices:stage_weights[i]=f*fractions[i]/normalizer/max(.01,reasons[pool[i]['id']]['cost'])
        for i in rng.choices(range(len(pool)),weights=stage_weights,k=budget):quotas[i]+=1
    return {'condition':condition,'budget':budget,'allocation':[{'template_id':t['id'],'count':n,'probability':f,**reasons[t['id']]} for t,n,f in zip(pool,quotas,fractions)],
        'graph_role':'conditional prior; no prerequisite locks' if condition=='C' else 'unused for allocation',
        'source_windows':state.get('windows',[]),'sealed_test_used':False,'stage':stage,
        'missing_stage_categories':[k for k,v in category_ids.items() if not v] if stage else []}


def curriculum(args,directory,config=None):
    state_path=Path(args['state']);state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {'config':args.get('settings',{})}
    if args.get('feedback'):
        observations=[json.loads(line) for line in Path(args['feedback']).read_text(encoding='utf8').splitlines() if line]
        state=update_state(state,observations,args['checkpoint'],args['window_id']);write_json(state_path,state)
    result=allocate(state,int(args.get('budget',1000)),args.get('condition','C'),args.get('template_ids'))
    write_json(Path(directory)/'allocation.json',result)
    return {'state':str(state_path),'allocation':str(Path(directory)/'allocation.json'),**{k:v for k,v in result.items() if k!='allocation'}}
