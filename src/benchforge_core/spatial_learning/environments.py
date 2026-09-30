"""Small executable environments; actions change state and return observations."""
import math
import random
from copy import deepcopy
from .graph_tasks import adjacency, shortest, path_cost


class Manipulation:
    def __init__(self,scene,objective='insert'):
        self.spec=deepcopy(scene['episode']);self.objective=objective
        if objective=='recover_rotation':self.spec['failure']='rotation_failure'
        if objective=='recover_grasp':self.spec['failure']='grasp_failure'
        self.state={'gripper':'home','holding':False,'part_location':'part','angle':self.spec['part_angle'],
            'container_open':objective!='open_container','inserted':False,'released':False,'inspected':False,
            'failure_used':False,'steps':0,'violations':0,'support_clear':objective!='stack','fastened':False,'placed':False}
        if objective=='retrieve':self.state.update(part_location='slot',container_open=False)
        self.sort_bin='bin' if scene['objects'][0]['shape'] in ['rectangle','triangle','cross','arrow'] else 'shelf'
        profile=self.spec['profile']
        if profile=='blocked_route':self.state['container_open']=False
        if profile=='reordered_goals':self.state['gripper']='shelf'
        if profile=='limited_budget':self.spec['budget']=12
        if profile=='distractor':self.state['part_location']='inspection'
        if profile=='multi_stage':self.state['support_clear']=False
        self.feedback='ready';self.trace=[]

    def observation(self):
        state={k:v for k,v in self.state.items() if k!='failure_used'}
        return {'state':state,'feedback':self.feedback,'objective':self.objective,
            'goal_location':self.destination,'required_angle':self.spec['slot_angle'],'symmetry':self.spec['symmetry'],
            'sorting_rule':'polygon classes rectangle/triangle/cross/arrow -> bin; other classes -> shelf' if self.objective=='sort' else None,
            'budget':self.spec['budget'],'actions':['move(home|part|slot|shelf|bin|inspection)','grasp','rotate(degrees)','wait','open','inspect','clear_support','fasten','insert','place','release'],
            'semantics':'Moves transport a held part. Grasp at the part; retrieving from a container requires open first. Rotate while holding. Insert needs open container, slot location, aligned angle and clear support. Place needs destination, alignment and clear support. Stack requires clear_support. Assembly requires fasten after insertion. Release follows insertion or placement. Inspect_then_act requires inspection before grasp. Feedback may report failed actions; pending motion requires wait.'}

    @property
    def destination(self):
        return self.sort_bin if self.objective=='sort' else 'shelf' if self.objective in ['stack','place','retrieve'] else 'bin' if self.objective=='transfer' else 'slot'

    @property
    def aligned(self):
        return abs((self.state['angle']-self.spec['slot_angle']+self.spec['symmetry']/2)%self.spec['symmetry']-self.spec['symmetry']/2)<1e-6

    def success(self):
        if self.objective=='align':return self.aligned and self.state['inspected']
        inserted=self.objective not in ['stack','place','retrieve','sort','transfer']
        return self.state['part_location']==self.destination and self.state['released'] and self.aligned and (self.state['inserted'] if inserted else self.state['placed']) and (self.objective!='inspect_then_act' or self.state['inspected']) and (self.objective!='assemble' or self.state['fastened'])

    def step(self,action):
        if self.state['steps']>=self.spec['budget']:raise ValueError('Episode budget exhausted')
        before=deepcopy(self.observation());s=self.state;s['steps']+=1;name=action['action'];self.feedback='ok';valid=True
        if name=='move':
            where=action.get('destination');valid=where in ['home','part','slot','shelf','bin','inspection']
            if valid:
                s['gripper']=where
                if s['holding']:s['part_location']=where
        elif name=='grasp':
            valid=not s['holding'] and s['gripper']==s['part_location'] and (self.objective!='retrieve' or s['container_open']) and (self.objective!='inspect_then_act' or s['inspected'])
            if valid and self.spec['failure']=='grasp_failure' and not s['failure_used']:
                s['failure_used']=True;self.feedback='grasp_failed'
            elif valid:s['holding']=True;s['released']=False
        elif name=='rotate':
            valid=s['holding'] and isinstance(action.get('degrees'),(int,float))
            if valid and self.spec['failure']=='rotation_failure' and not s['failure_used']:
                s['failure_used']=True;self.feedback='rotation_failed_angle_unchanged'
            elif valid and self.spec['profile']=='delayed_feedback':s['pending_angle']=(s['angle']+action['degrees'])%360;self.feedback='rotation_pending_wait'
            elif valid:s['angle']=(s['angle']+action['degrees'])%360
        elif name=='wait':
            valid='pending_angle' in s
            if valid:s['angle']=s.pop('pending_angle')
        elif name=='open':s['container_open']=True
        elif name=='clear_support':s['support_clear']=True
        elif name=='fasten':
            valid=s['inserted'] and s['holding']
            if valid:s['fastened']=True
        elif name=='inspect':s['inspected']=True;self.feedback=f'angle={s["angle"]}'
        elif name=='insert':
            valid=s['holding'] and s['gripper']=='slot' and self.aligned and s['container_open'] and s['support_clear']
            if valid:s['inserted']=True;s['part_location']='slot'
        elif name=='place':
            valid=s['holding'] and s['gripper']==self.destination and self.aligned and s['support_clear']
            if valid:s['part_location']=self.destination;s['placed']=True
        elif name=='release':
            valid=s['holding'] and self.aligned and s['part_location']==self.destination and (s['inserted'] or s['placed'])
            if valid:s['holding']=False;s['released']=True
        else:valid=False
        if not valid:s['violations']+=1;self.feedback='invalid_precondition'
        response=self.observation();response.update(done=self.success() or s['steps']>=self.spec['budget'],success=self.success())
        self.trace.append({'observation':before,'action':action,'response':deepcopy(response)})
        return response

    def expert_action(self):
        s=self.state
        if 'pending_angle' in s:return {'action':'wait'}
        if self.objective=='inspect_then_act' and not s['inspected']:return {'action':'inspect'}
        if self.objective=='retrieve' and not s['container_open']:return {'action':'open'}
        if not s['holding']:
            return {'action':'grasp'} if s['gripper']==s['part_location'] else {'action':'move','destination':s['part_location']}
        if not self.aligned:return {'action':'rotate','degrees':self.spec['slot_angle']-s['angle']}
        if self.objective=='align':return {'action':'inspect'}
        if not s['container_open']:return {'action':'open'}
        if not s['support_clear']:return {'action':'clear_support'}
        if s['gripper']!=self.destination:return {'action':'move','destination':self.destination}
        if self.destination=='slot' and not s['inserted']:return {'action':'insert'}
        if self.destination!='slot' and not s['placed']:return {'action':'place'}
        if self.objective=='assemble' and not s['fastened']:return {'action':'fasten'}
        return {'action':'release'}


class Navigation:
    def __init__(self,scene,objective='navigate'):
        self.graph=deepcopy(scene['graph']);self.objective=objective;self.position=self.graph['start'];self.steps=0;self.cost=0;self.feedback='ready';self.trace=[];self.visited={self.position}
        self.goals=[self.graph['goal']]
        if objective in ['waypoint','collect_delivery','explore_then_go']:self.goals=[self.graph['waypoint'],self.graph['goal']]
        if objective=='ordered_goals':self.goals=[self.graph['nodes'][-1],self.graph['waypoint'],self.graph['goal']]
        if objective=='return_home':self.goals=[self.graph['goal'],self.graph['start']]
        if objective=='visit_all':self.goals=[n for n in self.graph['nodes'] if n!=self.position]
        while self.goals and self.goals[0]==self.position:self.goals.pop(0)
        self.failure_edge=None;self.closed_once=False;self.impossible=False;self.picked_up=False
        self.scanned=set()
        self.initial_optimal=shortest(self.graph,start=self.position,goal=self.goals[0])[1] if self.goals else 0
        if objective in ['recover_closed_door','replan','avoid_blockage'] and self.graph['edges']:
            route,_=shortest(self.graph,start=self.position,goal=self.goals[0])
            if route and len(route)>1:
                edge=next(e for e in self.graph['edges'] if {e['a'],e['b']}==set(route[:2]));self.failure_edge=(edge['a'],edge['b'])

    def observation(self):
        outgoing=[{'to':e['b'] if e['a']==self.position else e['a'],'width':e['width'],'cost':e['cost'],'open':e['open']} for e in self.graph['edges'] if e['a']==self.position or not self.graph['directed'] and e['b']==self.position]
        return {'position':self.position,'goals':self.goals[:],'local_edges':outgoing,'feedback':self.feedback,
            'body_width':self.graph['body_width'],'steps':self.steps,'travel_cost':self.cost,'budget':self.graph['budget'],
            'known_map':self.graph,'carrying_delivery':self.picked_up,'scanned':sorted(self.scanned),'actions':['move(neighbor)','pickup','scan','declare_unreachable'],
            'semantics':'Move follows one traversable directed edge. Goal order matters. Collect_delivery requires pickup at the waypoint before leaving it. Explore_then_go requires scan at the waypoint. Shortest_navigation requires minimum travel cost. Budget_navigation requires total cost <= budget; declare_unreachable is valid when no path fits that remaining budget. Closed-door feedback updates the map. Other unreachable declarations need no legal path.'}

    def success(self):
        return self.impossible or not self.goals and (self.objective!='collect_delivery' or self.picked_up) and (self.objective!='shortest_navigation' or self.cost==self.initial_optimal) and (self.objective!='explore_then_go' or self.graph['waypoint'] in self.scanned)

    def step(self,action):
        before=deepcopy(self.observation());self.steps+=1;self.feedback='ok';valid=True
        if action['action']=='declare_unreachable':
            target=self.graph['waypoint'] if self.objective=='explore_then_go' and self.graph['waypoint'] not in self.scanned else self.goals[0]
            route,cost=shortest(self.graph,start=self.position,goal=target)
            self.impossible=route is None or self.objective=='budget_navigation' and cost>self.graph['budget']-self.cost;valid=self.impossible
        elif action['action']=='pickup':
            valid=self.objective=='collect_delivery' and self.position==self.graph['waypoint']
            if valid:self.picked_up=True
        elif action['action']=='scan':self.scanned.add(self.position)
        elif action['action']=='move':
            node=action.get('destination');edges=[e for e in self.graph['edges'] if (e['a'],e['b'])==(self.position,node) or not self.graph['directed'] and (e['b'],e['a'])==(self.position,node)]
            edge=edges[0] if edges else None
            if edge and self.failure_edge==(edge['a'],edge['b']) and not self.closed_once:
                edge['open']=False;self.closed_once=True;self.feedback='door_closed'
            elif edge and edge['open'] and edge['width']>=self.graph['body_width'] and (self.objective!='budget_navigation' or self.cost+edge['cost']<=self.graph['budget']):
                if self.objective=='collect_delivery' and self.position==self.graph['waypoint'] and not self.picked_up:
                    valid=False;self.feedback='pickup_required'
                    response=self.observation();response.update(success=False,done=False)
                    self.trace.append({'observation':before,'action':action,'response':deepcopy(response)});return response
                self.position=node;self.cost+=edge['cost'];self.visited.add(node)
                while self.goals and node==self.goals[0]:self.goals.pop(0)
            else:valid=False
        else:valid=False
        if not valid:self.feedback='invalid_or_blocked'
        response=self.observation();response.update(success=self.success(),done=self.success() or self.steps>=40)
        self.trace.append({'observation':before,'action':action,'response':deepcopy(response)})
        return response

    def expert_action(self):
        if self.objective=='explore_then_go' and self.graph['waypoint'] not in self.scanned:
            if self.position==self.graph['waypoint']:return {'action':'scan'}
            route,cost=shortest(self.graph,start=self.position,goal=self.graph['waypoint'])
            if route:return {'action':'move','destination':route[1]}
            return {'action':'declare_unreachable'}
        if self.objective=='collect_delivery' and self.position==self.graph['waypoint'] and not self.picked_up:return {'action':'pickup'}
        route,cost=shortest(self.graph,start=self.position,goal=self.goals[0])
        if self.objective=='budget_navigation' and cost is not None and cost>self.graph['budget']-self.cost:return {'action':'declare_unreachable'}
        return {'action':'move','destination':route[1]} if route and len(route)>1 else {'action':'declare_unreachable'}


class Inquiry:
    """Finite hypothesis observations with actual budget and terminal diagnosis."""
    def __init__(self,scene,objective='identify'):
        rng=random.Random(scene['seed']);self.objective=objective;profile=scene['episode']['profile']
        profile_index=['reliable','rotation_failure','grasp_failure','blocked_route','reordered_goals','limited_budget','symmetry','distractor','delayed_feedback','multi_stage'].index(profile)
        count=4+scene['difficulty']+profile_index%4
        self.hypotheses=[{'id':i,'location':[rng.randint(0,9),rng.randint(0,9)],'door':rng.choice(['open','closed']),
                         'shape':rng.choice(['round','keyed','square']),'fault':rng.choice(['grip','angle','blocked'])} for i in range(count)]
        self.hidden=rng.randrange(count);self.remaining=list(range(count));self.spent=0;self.budget=count*3;self.queried=[];self.done=False;self.correct=False;self.feedback='ready';self.trace=[]
        self.repeats={};self.profile=profile
        self.sensors=[]
        for axis in range(2):
            for threshold in [2,5,7]:self.sensors.append({'id':f'axis_{axis}_below_{threshold}','cost':1,'positive':[h['id'] for h in self.hypotheses if h['location'][axis]<threshold]})
        for field,values in [('door',['open']),('shape',['round','keyed']),('fault',['grip','angle'])]:
            self.sensors.extend({'id':f'{field}_{v}','cost':1,'positive':[h['id'] for h in self.hypotheses if h[field]==v]} for v in values)
        self.sensors.extend({'id':f'close_inspect_{i}','cost':2,'positive':[i]} for i in range(count))
        if objective in ['costly_sensor','compare_sensors','budget_query']:
            for sensor in self.sensors:sensor['cost']=rng.randint(1,3)
        self.reveal_after=2 if objective=='two_stage_query' else 0
        self.noise=objective=='noisy_repeat'
        if profile=='limited_budget':self.budget=count*2
        if profile=='delayed_feedback':self.noise=True
        if profile=='multi_stage':self.reveal_after=2
        if profile=='distractor':self.sensors.append({'id':'irrelevant_always_yes','cost':1,'positive':list(range(count))})
        if profile=='symmetry':
            for sensor in self.sensors:
                if sensor['id'].startswith('axis_'):sensor['positive']=[h for h in range(count) if h not in sensor['positive']]
        if profile=='reordered_goals':self.sensors.reverse()
        if profile=='blocked_route':self.sensors=[s for s in self.sensors if not s['id'].startswith('axis_')]
        if profile=='grasp_failure':
            for s in self.sensors:
                if s['id'].startswith('close_inspect_'):s['cost']=3
        if profile=='rotation_failure':
            for s in self.sensors:
                if s['id'].startswith('shape_'):s['cost']=2
        self.goal_field={'hidden_door':'door','hidden_target':'location','discover_edge':'door','locate_change':'location','diagnose_failure':'fault'}.get(objective)
        if objective=='budget_query':self.budget=count*2

    def observation(self):
        visible=self.sensors if self.spent>=self.reveal_after else self.sensors[:6]
        return {'objective':self.objective,'hypotheses':self.hypotheses,'sensors':visible,'remaining':self.remaining[:],
            'queried':self.queried[:],'spent':self.spent,'budget':self.budget,'feedback':self.feedback,
            'answer_field':self.goal_field or 'id','confirmation_required':self.noise,'inspection_available_after_cost':self.reveal_after,'actions':['observe(sensor_id)','answer(hypothesis)','answer(value)'],
            'semantics':'A sensor reports membership in its positive set. Identify the hidden hypothesis, or its requested answer_field. Noisy-repeat tasks require two observations of a sensor before a confirmed reading; the first is explicitly unconfirmed. Two-stage tasks reveal close inspection after two cost units. All observations consume budget.'}

    def step(self,action):
        if self.done:raise ValueError('Episode ended')
        before=deepcopy(self.observation())
        if action['action']=='answer':
            self.correct=action.get('value')==self.hypotheses[self.hidden][self.goal_field] if self.goal_field else action.get('hypothesis')==self.hidden
            self.done=True;self.feedback='correct' if self.correct else 'incorrect'
        elif action['action']=='observe':
            sensor=next(s for s in self.observation()['sensors'] if s['id']==action['sensor_id']);self.spent+=sensor['cost']
            if self.spent>self.budget:self.done=True;self.feedback='budget_exceeded'
            else:
                yes=self.hidden in sensor['positive'];self.repeats[sensor['id']]=self.repeats.get(sensor['id'],0)+1
                confirmed=not self.noise or self.repeats[sensor['id']]>=2
                if confirmed:self.remaining=[h for h in self.remaining if (h in sensor['positive'])==yes]
                self.queried.append(sensor['id']);self.feedback={'sensor':sensor['id'],'positive':yes if confirmed else None,'confirmed':confirmed}
        else:raise ValueError('Unknown inquiry action')
        response={**self.observation(),'done':self.done,'success':self.correct}
        self.trace.append({'observation':before,'action':action,'response':deepcopy(response)});return response

    def success(self):return self.correct

    def expert_action(self):
        if self.goal_field and len({str(self.hypotheses[h][self.goal_field]) for h in self.remaining})==1:
            return {'action':'answer','value':self.hypotheses[self.remaining[0]][self.goal_field]}
        if len(self.remaining)==1:return {'action':'answer','hypothesis':self.remaining[0]}
        def gain(sensor):
            p=sum(h in sensor['positive'] for h in self.remaining)/len(self.remaining)
            entropy=-(p*math.log2(p)+(1-p)*math.log2(1-p)) if 0<p<1 else 0
            return entropy/sensor['cost']
        return {'action':'observe','sensor_id':max(self.observation()['sensors'],key=gain)['id']}


class Goals:
    """Select a useful reachable goal, then execute its path to earn utility."""
    def __init__(self,scene,objective='utility'):
        self.graph=deepcopy(scene['graph']);rng=random.Random(scene['seed']+91);self.objective=objective
        self.position=self.graph['start'];self.budget=24;self.cost=0;self.steps=0;self.selected=None;self.done=False;self.earned=0;self.feedback='ready';self.trace=[];self.completed=[]
        self.goals=[{'node':n,'reward':rng.randint(2,12),'novelty':rng.randint(0,4),'coverage':rng.randint(1,8),'information':rng.randint(0,6),
                    'risk':rng.choice([.1,.3,.6]),'deadline':rng.randint(3,20),'prerequisite':rng.choice([True,False])} for n in self.graph['nodes'] if n!=self.position]
        self.required_goals=2 if objective=='multi_goal' else 1
        if objective=='budget_goal':self.budget=8

    def utilities(self):
        result={}
        for goal in self.goals:
            if goal['node'] in self.completed:continue
            _,cost=shortest(self.graph,start=self.position,goal=goal['node'])
            if cost is None or cost>self.budget-self.cost:continue
            if self.objective=='prerequisite_goal' and not goal['prerequisite']:continue
            if self.objective=='delivery_goal' and cost>goal['deadline']:continue
            reward=goal['reward'];rule=self.objective
            value={'utility':reward-.1*cost,'reward_per_cost':reward/(1+cost),'reachable_goal':-cost,'budget_goal':reward,
                'coverage_goal':goal['coverage']-.1*cost,'novelty_goal':goal['novelty']-.1*cost,
                'information_goal':goal['information']/(1+cost),'balanced_goal':reward*(1-goal['risk'])-.1*cost,
                'prerequisite_goal':reward-.1*cost,'delivery_goal':reward-.1*cost,
                'adaptive_goal':reward*(1-goal['risk'])+goal['novelty']-cost*.2,'multi_goal':reward+goal['coverage']-.1*cost}[rule]
            result[goal['node']]=value
        return result

    def observation(self):
        return {'map':self.graph,'goals':self.goals,'position':self.position,'selected':self.selected,'remaining_budget':self.budget-self.cost,
            'objective':self.objective,'feedback':self.feedback,'actions':['select(goal_node)','move(neighbor)','finish'],
            'completed_goals':self.completed,'required_goals':self.required_goals,
            'utility_rule':{'utility':'reward-.1*cost','reward_per_cost':'reward/(1+cost)','reachable_goal':'-cost','budget_goal':'reward',
                'coverage_goal':'coverage-.1*cost','novelty_goal':'novelty-.1*cost','information_goal':'information/(1+cost)',
                'balanced_goal':'reward*(1-risk)-.1*cost','prerequisite_goal':'reward-.1*cost; prerequisite must be true',
                'delivery_goal':'reward-.1*cost; cost <= deadline','adaptive_goal':'reward*(1-risk)+novelty-.2*cost',
                'multi_goal':'reward+coverage-.1*cost'}[self.objective],
            'semantics':'Select a maximum-utility reachable goal within remaining budget and execute a feasible route to it. Finish records arrival; multi_goal repeats this until two goals, or until no further goal fits the remaining budget. If none is reachable, finish without selecting.'}

    def step(self,action):
        before=deepcopy(self.observation());self.steps+=1;self.feedback='ok'
        if action['action']=='select':
            utilities=self.utilities();node=action['goal_node']
            if node not in utilities or utilities[node]<max(utilities.values())-1e-9:self.feedback='suboptimal_or_infeasible'
            else:self.selected=node;self.earned=utilities[node]
        elif action['action']=='move':
            node=action['destination'];cost=path_cost(self.graph,[self.position,node])
            if cost is None or self.cost+cost>self.budget:self.feedback='invalid_or_over_budget'
            else:self.position=node;self.cost+=cost
        elif action['action']=='finish':
            if self.selected==self.position:
                self.completed.append(self.selected);self.selected=None
                self.done=len(self.completed)>=self.required_goals or not self.utilities()
                self.feedback='goal_recorded'
            elif self.selected is None:self.done=not self.utilities()
            else:self.feedback='goal_not_completed'
        else:raise ValueError('Unknown goal action')
        response={**self.observation(),'done':self.done or self.steps>=40,'success':self.done,'utility':self.earned if self.done else 0}
        self.trace.append({'observation':before,'action':action,'response':deepcopy(response)});return response

    def success(self):return self.done

    def expert_action(self):
        if self.selected is None:
            choices=self.utilities()
            return {'action':'select','goal_node':max(choices,key=choices.get)} if choices else {'action':'finish'}
        if self.position==self.selected:return {'action':'finish'}
        route,_=shortest(self.graph,start=self.position,goal=self.selected)
        return {'action':'move','destination':route[1]}


def environment(scene,nid,query):
    return {'N22':Manipulation,'N24':Manipulation,'N25':Navigation,'N26':Inquiry,'N27':Goals}[nid](scene,query)


def demonstration(env):
    initial=deepcopy(env.observation())
    for _ in range(40):
        if env.success():break
        response=env.step(env.expert_action())
        if response['done']:break
    return {'initial_observation':initial,'trajectory':env.trace,'final_observation':env.observation(),'success':env.success()}
