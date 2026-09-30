"""Program-only grading with equivalent route and environment replay support."""
import json
import math
from .graph_tasks import path_cost
from .environments import environment


def close(actual,expected,atol=.08):
    if isinstance(expected,bool):return type(actual) is bool and actual==expected
    if expected is None or isinstance(expected,str):return actual==expected
    if isinstance(expected,(int,float)):
        return type(actual) in (int,float) and math.isfinite(actual) and abs(actual-expected)<=atol
    if isinstance(expected,list):return isinstance(actual,list) and len(actual)==len(expected) and all(close(a,b,atol) for a,b in zip(actual,expected))
    if isinstance(expected,dict):return isinstance(actual,dict) and set(actual)==set(expected) and all(close(actual[k],v,atol) for k,v in expected.items())
    return actual==expected


def score(authority,prediction):
    if isinstance(prediction,str):
        try:prediction=json.loads(prediction)
        except json.JSONDecodeError:return {'success':False,'score':0.,'parse_ok':False,'error':'invalid_json'}
    kind=authority['scorer'];expected=authority['answer'];success=False
    if kind=='path':
        rule=authority['path_rule'];g=authority['path_graph']
        if expected is None:success=prediction is None
        elif isinstance(prediction,list) and prediction:
            cost=path_cost(g,prediction,rule['feasible'])
            success=prediction[0]==rule['start'] and prediction[-1]==rule['goal'] and cost==rule['optimal_cost']
            success=success and (not rule.get('waypoint') or rule['waypoint'] in prediction)
            success=success and not any(n in prediction for n in rule.get('avoid',[]))
            success=success and (not rule.get('budget') or cost is not None and cost<=rule['budget'])
    elif kind=='plan':
        env=environment(authority['scene'],'N22',authority.get('objective','insert'))
        if isinstance(prediction,list):
            try:
                for action in prediction:env.step(action)
                success=env.success() and env.state['violations']==0
            except (KeyError,ValueError,TypeError):success=False
    elif kind=='constraints':
        if expected is None:success=prediction is None
        elif isinstance(prediction,dict) and set(prediction)==set(expected):
            success=all(type(x) in (int,float) and math.isfinite(x) for x in prediction.values())
            if success:success=all(prediction[a]<prediction[b] for a,relation,b in authority['facts'] if relation=='left_of')
    elif kind=='ordering':
        if expected is None:success=prediction is None
        elif isinstance(prediction,list) and all(isinstance(x,str) for x in prediction) and len(set(prediction))==len(expected) and set(prediction)==set(expected):
            positions={n:i for i,n in enumerate(prediction)}
            success=all(positions[a]<positions[b] for a,relation,b in authority['facts'] if relation=='left_of')
    else:success=close(prediction,expected,authority.get('tolerance',.08 if kind=='numeric' else 0))
    return {'success':bool(success),'score':float(success),'parse_ok':True,'error':None if success else 'task_mismatch'}
