"""Matched controls use the same world and final goal, with explicit assistance."""
from copy import deepcopy
from .scenes import rotate


def apply_condition(public, authority, condition):
    public=deepcopy(public);authority=deepcopy(authority)
    public['condition']=condition
    nid=public['capabilities'][0];query=public['template_id'].split('.')[1]
    scene=authority['scene'];inputs=public['inputs']
    if nid=='N15' and query=='future_point':
        public['course']='XVP';public['capabilities']=['N15','N19']
        m=scene['motion'];t=m['prediction_t']
        future=[m['initial'][i]+t*m['velocity'][i]+.5*t*t*m['acceleration'][i] for i in range(2)]
        if condition=='supplied_intermediate':
            inputs['future_position_A']=future
            public['question']='Convert the supplied future_position_A to frame B. Return JSON.'
            public['capabilities']=['N15']
        elif condition=='isolated':
            public['question']='Predict the position at time t in frame A. Return JSON.'
            authority['answer']=future;public['capabilities']=['N19']
    elif nid=='N23' and query=='route':
        public['course']='MAP';public['capabilities']=['N17','N16','N23']
        g=scene['graph']
        if condition=='natural':
            inputs.pop('map',None)
            inputs['visits']=[{'node':n,'outgoing':[{'to':e['b'] if e['a']==n else e['a'],**{k:e[k] for k in ['cost','width','open']}}
                for e in g['edges'] if e['a']==n or not g['directed'] and e['b']==n]} for n in g['nodes']]
            public['question']='Integrate these local visits, account for body width and open doors, and return a minimum-cost feasible start-goal path, or null.'
        elif condition=='supplied_intermediate':
            public['capabilities']=['N16','N23']
        else:
            inputs['map']={**g,'edges':[e for e in g['edges'] if e['open'] and e['width']>=g['body_width']]}
            public['capabilities']=['N23']
    elif nid=='N24' and query=='insert':
        public['course']='INS';public['capabilities']=['N07','N22','N24']
        if condition=='supplied_intermediate':
            public['assistance']={'nominal_plan':['move to part','grasp','rotate to required angle','move to slot','insert','release'],
                                  'instruction':'Use feedback to recover failed actions; a nominal plan does not imply execution success.'}
        elif condition=='isolated':
            # An execution control has the required angle and the next action
            # available at each step; evaluation supplies it from current state.
            public['assistance']={'next_action_available':True}
            public['capabilities']=['N24']
    elif nid=='N11' and query in ['center','bbox','correction']:
        public['course']='LOC'
        if condition=='supplied_intermediate':
            inputs['target_bounding_rectangle_grid']=next(o for o in scene['objects'] if o['id']==scene['target_id'])
        elif condition=='isolated':
            target=next(o for o in scene['objects'] if o['id']==scene['target_id'])
            inputs['object_geometry']=target
            public['images']=[];public['input_mode']='structured'
    elif condition!='natural':
        inputs['observation_geometry']={k:scene[k] for k in ['objects','extent']}
        public['assistance']={'kind':'supplied_geometry','scope':'oracle-independent world observation; this is an assisted condition'}
        if condition=='isolated':public['images']=[];public['input_mode']='structured'
    authority['condition']=condition
    return public,authority
