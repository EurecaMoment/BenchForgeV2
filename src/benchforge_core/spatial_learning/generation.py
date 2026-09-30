"""Split grouped worlds before producing task variants and public media."""
import json
import random
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
from .registry import templates
from .scenes import create_scene,render
from .geometry_tasks import task as geometry_task
from .motion_tasks import task as motion_task,observed_scenes
from .reasoning_tasks import task as reasoning_task
from .graph_tasks import task as graph_task
from .environments import environment,demonstration
from .conditions import apply_condition

PARTITIONS=('train','curriculum_dev','selection_dev','sealed_test')


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def build_task(scene,template):
    nid=template['primary_capabilities'][0];op=template['query']
    if nid in ['N04','N05','N09','N14','N18']:spec=motion_task(scene,nid,op)
    elif nid in ['N15','N16','N19','N20','N21']:spec=reasoning_task(scene,nid,op)
    elif nid in ['N17','N23']:spec=graph_task(scene,nid,op)
    elif nid in ['N24','N25','N26','N27']:
        env=environment(scene,nid,op);demo=demonstration(env)
        spec={'question':'Complete this interactive objective using observations and action feedback. Return one JSON action at a time.',
              'inputs':demo['initial_observation'],'answer':None,'scorer':'environment','demonstration':demo}
    elif nid=='N22':
        nominal=deepcopy(scene);nominal['episode']['failure']=None;env=environment(nominal,nid,'insert');demo=demonstration(env)
        actions=[row['action'] for row in demo['trajectory']]
        proposed=deepcopy(actions)
        if scene['seed']%2:proposed=[a for a in proposed if a['action']!='rotate']
        trial=environment(nominal,nid,'insert')
        for action in proposed:trial.step(action)
        valid=trial.success() and trial.state['violations']==0
        progress=scene['seed']%min(4,len(actions));partial=environment(nominal,nid,'insert')
        for action in actions[:progress]:partial.step(action)
        action_name=['grasp','rotate','insert','release'][scene['seed']%4]
        preconditions={'grasp':['at_part','not_holding'],'rotate':['holding'],'insert':['holding','at_slot','aligned','container_open','support_clear'],'release':['holding','aligned','at_destination','inserted_or_placed']}
        effects={'grasp':{'holding':True},'rotate':{'angle_changed':True},'insert':{'inserted':True},'release':{'holding':False,'released':True}}
        values={'plan':('Return a valid action sequence reaching insertion and release.',actions,'plan'),
            'shortest_plan':('Return a valid insertion-and-release sequence without invalid actions.',actions,'plan'),
            'alternate_plan':('Return any valid insertion-and-release sequence.',actions,'plan'),
            'repair_plan':('The proposed plan omits rotation. Return a repaired complete plan.',actions,'plan'),
            'remove_redundancy':('Return an insertion plan with no unnecessary repeated inspections.',actions,'plan'),
            'valid_plan':('Is the proposed plan executable and successful?',valid,'exact'),
            'next_action':('Give the next action from the current state.',partial.expert_action(),'exact'),
            'preconditions':(f'Which conditions are required for {action_name}? Return sorted names.',sorted(preconditions[action_name]),'exact'),
            'effects':(f'Give the specified state effects of a successful {action_name}.',effects[action_name],'exact'),
            'plan_cost':('What is the proposed plan action count?',len(proposed),'exact'),
            'goal_state':('After the proposed plan, is inserted and released true?',trial.success(),'exact'),
            'recovery_plan':('Return a complete plan from this state; rotation is currently unaligned.',actions,'plan')}
        question,answer,kind=values[op];inputs=demo['initial_observation']
        if op in ['valid_plan','plan_cost','goal_state','repair_plan','remove_redundancy']:
            proposal=[a for a in actions if a['action']!='rotate'] if op=='repair_plan' else [{'action':'inspect'},{'action':'inspect'}]+actions if op=='remove_redundancy' else proposed
            inputs={**inputs,'proposed_plan':proposal}
        if op=='next_action':inputs=partial.observation()
        spec={'question':question,'answer':answer,'scorer':kind,'inputs':inputs,'scene':nominal,'objective':'insert'}
    else:
        scene['show_gravity']=nid=='N06';scene['show_bounds']=nid in ['N08','N12','N13'];spec=geometry_task(scene,nid,op)
    return spec


def make_item(template,seed,difficulty,group,media_directory=None):
    scene=create_scene(template,seed,difficulty,group);spec=build_task(scene,template)
    nid=template['primary_capabilities'][0];images=[]
    if media_directory is not None and template['input_mode'] in ['image','image_sequence']:
        media_directory=Path(media_directory);media_directory.mkdir(parents=True,exist_ok=True)
        frames,_=observed_scenes(scene,nid) if template['input_mode']=='image_sequence' else ([scene],None)
        for i,frame in enumerate(frames):
            path=media_directory/f'{i}.png'
            if not path.exists():render(frame,path)
            images.append(str(path.resolve()))
    inputs=spec.get('inputs',{})
    if template['input_mode']=='image':inputs={'target_id':scene['target_id'],'reference_id':scene['reference_id'],
        'label_format':'number k in image means object_k','category':scene['category'],'grid_spacing':1,
        'heading_marker':'white line from center to black dot','coordinate_units':'grid units unless question asks pixels',
        'bounding_regions':'thin labeled rectangle outlines show complete object bounds' if scene.get('show_bounds') else 'infer the outer silhouette bounds from the image'}
    public={'template_id':template['id'],'capabilities':template['primary_capabilities'],'scene_group':group,
            'input_mode':template['input_mode'],'difficulty':difficulty,'condition':'natural',
            'question':spec['question']+' Return only the JSON answer.','inputs':inputs,'images':images,
            'interaction':template['input_mode']=='interactive'}
    authority={k:v for k,v in spec.items() if k not in ['question','inputs']}
    authority['scene']=spec.get('scene',scene);authority['provenance']='program_generated_world'
    if template['query'] in ['center_pixels','bbox_pixels']:authority['tolerance']=2
    if nid=='N07' and template['query'] in ['heading','clockwise_turn','counterclockwise_turn','relative_heading','rotate_to','face_reference']:authority['tolerance']=5
    if nid=='N06' and template['query'] in ['down_angle','camera_roll','gravity_rotation']:authority['tolerance']=3
    if nid=='N04' and template['query'] in ['rotation','heading']:authority['tolerance']=3
    if spec.get('path_rule'):authority['path_graph']=inputs.get('map',scene['graph'])
    return public,authority


def generate(args,directory,config=None):
    root=Path(directory)/'dataset'
    selected=templates(args.get('capability'))
    if args.get('template_ids'):selected=[t for t in selected if t['id'] in args['template_ids']]
    excluded=set(args.get('exclude_template_ids', []))
    selected=[t for t in selected if t['id'] not in excluded]
    if not selected:raise ValueError('No matching templates')
    profiles=sorted({t['scene_profile'] for t in templates()})
    # World identity is independent of query and capability. Repeated tasks
    # inherit partition membership; there is no random per-row split.
    groups_per_profile=int(args.get('groups_per_profile',20));seed=int(args.get('seed',42000))
    counts=Counter();groups={};failures=[];handles={};template_counts=Counter();answer_counts=defaultdict(Counter)
    heldout=set(args.get('heldout_profiles',[]));conditions=args.get('conditions',['natural'])
    render_media=args.get('render',True)
    if not render_media and any(t['input_mode'] in ['image','image_sequence'] for t in selected):
        raise ValueError('Visual training items require rendered observations. Select structured tasks to generate without images.')
    root.mkdir(parents=True)
    for partition in PARTITIONS:
        folder=root/partition;folder.mkdir()
        handles[partition]=[(folder/name).open('w',encoding='utf8') for name in ['questions.jsonl','authority.jsonl','sft.jsonl']]
    for ti,template in enumerate(selected):
        family=template['scene_family'];profile=template['scene_profile']
        profile_index=profiles.index(profile)
        for gi in range(groups_per_profile):
            partition=PARTITIONS[0 if gi%20<12 else 1 if gi%20<15 else 2 if gi%20<17 else 3]
            if profile in heldout:partition='sealed_test'
            group=f'{family}/{profile}/world_{seed+gi:06d}';groups[group]=partition
            row_seed=seed+gi+profile_index*10000;difficulty=1+gi%3
            media=root/partition/'media'/family/profile/f'{seed+gi:06d}'/template['primary_capabilities'][0]
            base,truth=make_item(template,row_seed,difficulty,group,media if render_media else None)
            base['images']=[Path(p).relative_to(root.resolve()).as_posix() for p in base['images']]
            if truth['scorer']=='environment' and not truth['demonstration']['success']:
                failures.append({'id':f'{template["id"]}.{seed+gi}','reason':'expert_episode_failed'})
                continue
            matched=(template['primary_capabilities'][0],template['query']) in [('N15','future_point'),('N23','route'),('N24','insert'),('N11','center'),('N11','bbox'),('N11','correction')]
            for condition in conditions if matched or args.get('all_controls') else ['natural']:
                public,private=apply_condition(base,truth,condition)
                item_id=f'{template["id"]}.{seed+gi}.{condition}'
                public.update(id=item_id,partition=partition,holdout='structural_profile' if profile in heldout else 'world')
                private.update(id=item_id,template_id=template['id'],scene_group=group)
                for index,row in enumerate([public,private]):handles[partition][index].write(json.dumps(row,ensure_ascii=False)+'\n')
                common={k:public[k] for k in ['capabilities','template_id','scene_group','condition','difficulty','input_mode']}
                if partition=='train':
                    if private['scorer']=='environment':
                        for step,row in enumerate(private['demonstration']['trajectory']):
                            observation=deepcopy(row['observation'])
                            if public.get('assistance'):observation['assistance']=public['assistance']
                            if public.get('assistance',{}).get('next_action_available'):observation['next_action']=row['action']
                            training={**common,'id':item_id+f'.step{step}',
                                'messages':[{'role':'user','content':public['question']+'\n'+json.dumps(observation,ensure_ascii=False)},
                                            {'role':'assistant','content':json.dumps(row['action'],ensure_ascii=False)}], 'images':[]}
                            handles[partition][2].write(json.dumps(training,ensure_ascii=False)+'\n')
                    else:
                        training={**common,'id':item_id,'messages':[
                            {'role':'user','content':public['question']+'\n'+json.dumps(public['inputs'],ensure_ascii=False)},
                            {'role':'assistant','content':json.dumps(private['answer'],ensure_ascii=False)}], 'images':public['images']}
                        handles[partition][2].write(json.dumps(training,ensure_ascii=False)+'\n')
                counts[partition]+=1;template_counts[template['id']]+=1
                if condition=='natural':answer_counts[template['id']][json.dumps(private['answer'],sort_keys=True)]+=1
    for files in handles.values():
        for handle in files:handle.close()
    report={'templates':len(selected),'excluded_template_ids':sorted(excluded),'per_capability_templates':dict(Counter(t['primary_capabilities'][0] for t in selected)),
        'items':dict(counts),'scene_groups':len(groups),'group_partitions':groups,'template_counts':dict(template_counts),
        'failed_demonstrations':failures,'source':'program','model_api_calls':0,'rendered':render_media,
        'conditions':conditions,'structural_heldout_profiles':sorted(heldout),
        'split_semantics':'Shared base-world membership; heldout profiles are exclusively sealed_test.',
        'quality':{'constant_answer_templates':[tid for tid,bins in answer_counts.items() if len(bins)==1 and sum(bins.values())>=5 and not bins.get('null') and not (tid.split('.')[1]=='cycle' and bins.most_common(1)[0][0]=='false')],
                   'answer_cardinality':{tid:len(bins) for tid,bins in answer_counts.items()},
                   'dominant_answer_templates':[{'template_id':tid,'answer':bins.most_common(1)[0][0],'fraction':bins.most_common(1)[0][1]/sum(bins.values())} for tid,bins in answer_counts.items() if sum(bins.values())>=5 and bins.most_common(1)[0][1]/sum(bins.values())>=.9],
                   'largest_answer_fraction':{tid:max(bins.values())/sum(bins.values()) for tid,bins in answer_counts.items()},
                   'failed_episodes_excluded':len(failures),'image_paths':'relative to dataset root'}}
    write_json(root/'manifest.json',report)
    return {'dataset':str(root),'manifest':str(root/'manifest.json'),'templates':len(selected),'items':dict(counts),'failed_demonstrations':len(failures)}
