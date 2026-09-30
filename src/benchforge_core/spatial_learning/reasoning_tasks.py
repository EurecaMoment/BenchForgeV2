"""Explicit frames, geometric constraints and deterministic prediction rules."""
import math
import random
from .scenes import rotate,bbox
from .geometry_tasks import result,distance,intersection,area
from .graph_tasks import task as graph_task


def task(scene,nid,op):
    a,b=scene['objects'][:2];p,q=a['position'],b['position'];w,h=a['size'];rw,rh=b['size']
    trans=scene['transform'];angle=trans['angle'];origin=trans['origin']
    tf=lambda point:rotate([point[i]-origin[i] for i in range(2)],angle)
    m=scene['motion'];v=m['velocity'];acc=m['acceleration'];time=m['prediction_t']
    future=lambda t:[m['initial'][i]+v[i]*t+.5*acc[i]*t*t for i in range(2)]
    inputs={'point_A':p,'reference_A':q,'object_size':a['size'],'reference_size':b['size'],
            'frame':'right-handed abstract 2D coordinates; x right, y forward; positive transform rotates vector counterclockwise',
            'transform':{'R_BA_degrees':angle,'origin_B_in_A':origin}}
    if nid=='N15':
        corners=[[x,y] for x in [p[0]-w/2,p[0]+w/2] for y in [p[1]-h/2,p[1]+h/2]];rc=[tf(c) for c in corners]
        inputs['motion']={'initial_A':m['initial'],'velocity_A':v,'acceleration_A':acc,'t':time,'rule':'constant acceleration'}
        values={'point':('Express point_A in frame B.',tf(p)),
          'vector':('Express vector reference_A-point_A in B (translation does not apply to vectors).',rotate([q[i]-p[i] for i in range(2)],angle)),
          'inverse_point':('Given coordinates point_A as a B-frame point instead, convert it to A.',[rotate(p,-angle)[i]+origin[i] for i in range(2)]),
          'relative_point':('Express point_A relative to reference_A, with axes rotated into B.',rotate([p[i]-q[i] for i in range(2)],angle)),
          'compose_points':('Transform [point_A, reference_A] into B, preserving order.',[tf(p),tf(q)]),
          'transform_angle':('Give the direction angle of reference_A-point_A in B, degrees [0,360).',(math.degrees(math.atan2(q[1]-p[1],q[0]-p[0]))+angle)%360),
          'transformed_bbox':('Give the axis-aligned bounding rectangle in B of the A rectangle centered at point_A with object_size.',[min(c[0] for c in rc),min(c[1] for c in rc),max(c[0] for c in rc),max(c[1] for c in rc)]),
          'relative_distance':('Give the Euclidean distance between the two transformed points.',distance(tf(p),tf(q))),
          'camera_origin':('Express the A origin [0,0] in B.',tf([0,0])),
          'future_point':('Predict motion position at t, then express it in B.',tf(future(time))),
          'trajectory':('Predict positions at t=0,1,2,3 and express each in B.',[tf(future(t)) for t in range(4)]),
          'change_observer':('Express point_A in a frame C whose origin is reference_A and whose vector rotation from A is -R_BA_degrees.',rotate([p[i]-q[i] for i in range(2)],-angle))}
    elif nid=='N16':
        reach=random.Random(scene['seed']+601).uniform(.3,5)
        inputs={'target_size':a['size'],'space_size':b['size'],'mass_kg':a['mass'],'lift_limit_kg':1.5,
                'reach_distance':distance(p,q),'arm_reach':reach,'tool_length':w,'gap_width':rw,'body_width':.6,
                'load_center':p,'support_center':q,'support_size':b['size'],'friction':.4,'slope_degrees':angle%45,
                'turn_radius':h/2,'door_width':rw,'height_limit':rh,'orientation_degrees':a['heading']}
        r=bbox(b);feasible={'lift':a['mass']<=1.5,'reach':distance(p,q)<=reach,'pass':rw>=.6,'insert':w<=rw and h<=rh}
        values={'door_pass':('Can a 0.6-wide body pass the specified door with no extra margin?',rw>=.6),
          'clearance':('Give door width minus body width; negative means infeasible.',rw-.6),
          'fit_container':('Can target fit the space axis-aligned, permitting a 90-degree turn?',(w<=rw and h<=rh) or (h<=rw and w<=rh)),
          'reach':('Can the arm reach the target under the given radial reach model?',distance(p,q)<=reach),
          'lift':('Can the stated lift limit lift the target mass?',a['mass']<=1.5),
          'support':('Is the load center inside the rectangular support footprint?',r[0]<=p[0]<=r[2] and r[1]<=p[1]<=r[3]),
          'stack':('Can the target footprint fit the support without rotation?',w<=rw and h<=rh),
          'insert':('Can the target pass the axis-aligned slot without rotation?',feasible['insert']),
          'turn_space':('Can a circle of the stated turn radius fit in the space?',2*inputs['turn_radius']<=min(rw,rh)),
          'tool_length':('Can the straight tool bridge the gap?',w>=rw),
          'traversable_edges':('Which edges in this map admit the specified body?',None),
          'feasible_actions':('Return the feasible names among lift, reach, pass, insert.',sorted(k for k,v in feasible.items() if v))}
        if op=='traversable_edges':return graph_task(scene,'N23','feasible_subgraph')
    elif nid=='N19':
        inputs={'initial_position':m['initial'],'velocity':v,'acceleration':acc,'time':time,'mass':a['mass'],
                'other_mass':b['mass'],'other_velocity':[-.2,.1],'friction':.25,'gravity':9.81,
                'wall_x':7,'radius':w/2,'motion_rule':'constant acceleration, except explicit collision/friction questions'}
        speed=math.hypot(*v);mu=.25;g=9.81
        values={'future_position':('Predict position at time under constant acceleration.',future(time)),
          'future_velocity':('Predict velocity at time under constant acceleration.',[v[i]+acc[i]*time for i in range(2)]),
          'future_distance':('Give displacement magnitude at time under constant acceleration.',distance(future(time),m['initial'])),
          'intercept':('Ignoring acceleration, when does x reach wall_x? null if not in the future.',(7-m['initial'][0])/v[0] if v[0]>0 else None),
          'collision_time':('The target is a disc of the stated radius. For constant velocity, give its first future wall contact time; null if never reached.',(7-w/2-m['initial'][0])/v[0] if v[0]>0 else None),
          'bounce':('Give velocity immediately after a perfectly elastic collision with the vertical wall; ignore acceleration.',[-v[0],v[1]]),
          'friction_stop':('On a horizontal plane with kinetic friction, give [stopping_time, stopping_distance] from the stated speed.',[speed/(mu*g),speed*speed/(2*mu*g)]),
          'acceleration':('Give net force vector under the stated constant acceleration.',[a['mass']*x for x in acc]),
          'trajectory':('Return positions at times 0,1,2,3 under constant acceleration.',[future(t) for t in range(4)]),
          'momentum':('Give total momentum of target and other object.',[a['mass']*v[i]+b['mass']*inputs['other_velocity'][i] for i in range(2)]),
          'energy':('Give target kinetic energy at time 0.',.5*a['mass']*speed*speed),
          'force':('Give force required to cancel the current acceleration.',[-a['mass']*x for x in acc])}
    elif nid=='N20':
        ba,bb=bbox(a),bbox(b);inter=intersection(a,b);vertices=[[0,0],[w,0],[w,h],[0,h]]
        inputs={'point':p,'reference':q,'rectangle_a':ba,'rectangle_b':bb,'angle_degrees':angle,
            'translation':origin,'scale':1.5,'polygon_vertices':vertices,'box_dimensions':[w,h,1.2],
            'line':{'a':[0,0],'b':q}}
        values={'rotate':('Rotate point about the origin by angle_degrees counterclockwise.',rotate(p,angle)),
          'reflect':('Reflect point across the line x=y.',[p[1],p[0]]),
          'translate':('Translate point by the given vector.',[p[i]+origin[i] for i in range(2)]),
          'scale':('Scale point by the given scale about reference.',[q[i]+1.5*(p[i]-q[i]) for i in range(2)]),
          'area_union':('Compute area of union of the two rectangles.',area(a)+area(b)-inter),
          'area_intersection':('Compute rectangle intersection area.',inter),
          'bbox_union':('Give the bounding rectangle enclosing both rectangles.',[min(ba[0],bb[0]),min(ba[1],bb[1]),max(ba[2],bb[2]),max(ba[3],bb[3])]),
          'centroid':('Give the polygon area centroid.',[w/2,h/2]),
          'polygon_area':('Give the polygon area.',w*h),
          'distance_to_line':('Give perpendicular distance from point to the infinite line.',abs(q[0]*p[1]-q[1]*p[0])/math.hypot(*q)),
          'volume':('Give box volume.',w*h*1.2),'surface_area':('Give box surface area.',2*(w*h+w*1.2+h*1.2))}
    elif nid=='N21':
        order=sorted(scene['objects'],key=lambda o:o['position'][0]);names=[o['id'] for o in order]
        facts=[[names[i],'left_of',names[i+1]] for i in range(len(names)-1)]
        if scene['seed']%3==0:facts.append([names[-1],'left_of',names[0]])
        vertical_known=scene['seed']%2==0
        if vertical_known:facts.append([names[0],'above',names[-1]])
        inputs={'facts':facts,'semantics':'left_of is strict and transitive; only logical consequences count','target':names[0],'reference':names[-1]}
        consistent=scene['seed']%3!=0
        values={'transitive':('If facts are consistent, is target left of reference? Otherwise answer inconsistent.',True if consistent else 'inconsistent'),
          'inverse':('Express the inverse of the first fact.',[facts[0][2],'right_of',facts[0][0]]),
          'consistent':('Can all strict ordering facts be true?',consistent),
          'entailed':('List all entailed left_of pairs if consistent; otherwise answer inconsistent.',[[names[i],names[j]] for i in range(len(names)) for j in range(i+1,len(names))] if consistent else 'inconsistent'),
          'unknown_relation':('Can the vertical ordering of target and reference be determined from an explicit vertical fact?',vertical_known),
          'relation_chain':('Give the chain of IDs from target to reference if consistent; otherwise inconsistent.',names if consistent else 'inconsistent'),
          'ordering':('Give a left-to-right ordering satisfying all facts, or null if impossible.',names if consistent else None),
          'between':('List IDs strictly between target and reference, or inconsistent.',names[1:-1] if consistent else 'inconsistent'),
          'contradiction':('Does the fact set contain a contradiction?',not consistent),
          'reachable':('Is target reachable from reference following only left_of facts?',not consistent),
          'relation_set':('Give deduplicated original facts sorted lexicographically.',sorted(facts)),
          'constraint_solution':('Give {ID: integer x} satisfying all facts, or null.',{n:i for i,n in enumerate(names)} if consistent else None)}
    else:raise KeyError((nid,op))
    text,answer=values[op]
    if nid=='N21' and op in ['constraint_solution','ordering']:
        return result(text,answer,'constraints' if op=='constraint_solution' else 'ordering',inputs=inputs,facts=facts)
    return result(text,answer,'numeric',inputs=inputs)
