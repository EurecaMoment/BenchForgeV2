"""Geometric oracle programs. Prompts never contain their queried answer."""
import math
from itertools import combinations
from .scenes import bbox, rotate


def distance(a,b):return math.dist(a,b)
def area(o):return math.prod(o['size'])
def center(o):return o['position']


def intersection(a,b):
    a,b=bbox(a),bbox(b)
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def relation(a,b):
    x,y=bbox(a),bbox(b)
    if all([x[0]>=y[0],x[1]>=y[1],x[2]<=y[2],x[3]<=y[3]]):return 'inside'
    if all([y[0]>=x[0],y[1]>=x[1],y[2]<=x[2],y[3]<=x[3]]):return 'contains'
    if intersection(a,b)>1e-8:return 'overlap'
    if max(x[0],y[0])<=min(x[2],y[2])+1e-8 and max(x[1],y[1])<=min(x[3],y[3])+1e-8:return 'touch'
    return 'disjoint'


def result(text,answer,kind='numeric',**extra):
    return {'question':text,'answer':answer,'scorer':kind,**extra}


def task(scene,nid,op):
    obs=scene['objects'];target=next(o for o in obs if o['id']==scene['target_id']);ref=next(o for o in obs if o['id']==scene['reference_id'])
    t,r=target['id'],ref['id'];p,q=center(target),center(ref);others=[o for o in obs if o['id']!=t]
    title=f'Target {t}; reference {r}. Coordinates x right, y down; grid spacing = 1 unit. '
    ordered=sorted(others,key=lambda o:(distance(p,center(o)),o['id']))
    ids=lambda a:[o['id'] for o in a]
    if nid=='N01':
        ds=[distance(p,center(o)) for o in ordered];pairs=sorted(combinations(obs,2),key=lambda x:(distance(center(x[0]),center(x[1])),x[0]['id'],x[1]['id']))
        values={
          'distance':('What is the center-to-center Euclidean distance to the reference?',distance(p,q)),
          'nearest':('Which other object is nearest?',ordered[0]['id']),
          'farthest':('Which other object is farthest?',ordered[-1]['id']),
          'rank':('Order all other object IDs by increasing center distance; break ties by ID.',ids(ordered)),
          'compare':(f'Is the reference closer than {others[-1]["id"]}?',distance(p,q)<distance(p,center(others[-1]))),
          'within_count':('How many other centers are at most 3 units away?',sum(d<=3 for d in ds)),
          'within_set':('List other IDs whose centers are at most 3 units away.',ids([o for o in ordered if distance(p,center(o))<=3])),
          'distance_ratio':(f'Give distance to reference divided by distance to {others[-1]["id"]}.',distance(p,q)/max(distance(p,center(others[-1])),1e-9)),
          'distance_difference':('Give farthest minus nearest center distance.',ds[-1]-ds[0]),
          'pair_nearest':('Give the pair of object IDs with smallest center distance, IDs sorted.',sorted(ids(pairs[0]))),
          'pair_farthest':('Give the pair with largest center distance, IDs sorted.',sorted(ids(pairs[-1]))),
          'equidistant':('List other IDs whose center distance differs from the reference distance by at most 0.25.',sorted(o['id'] for o in others if abs(distance(p,center(o))-distance(p,q))<=.25)),
        }
    elif nid=='N02':
        w,h=target['size'];rank=sorted(obs,key=lambda o:(area(o),o['id']))
        values={'width':('Give the target bounding width.',w),'height':('Give the target bounding height.',h),
          'area':('Give the target bounding rectangle area.',w*h),'perimeter':('Give its bounding rectangle perimeter.',2*(w+h)),
          'diagonal':('Give its bounding rectangle diagonal length.',math.hypot(w,h)),'aspect':('Give width divided by height.',w/h),
          'largest':('Which object has the largest bounding rectangle area?',rank[-1]['id']),
          'smallest':('Which object has the smallest bounding rectangle area?',rank[0]['id']),
          'size_rank':('Order IDs by bounding rectangle area, then ID.',ids(rank)),
          'area_compare':('Is the target bounding area larger than the reference bounding area?',area(target)>area(ref)),
          'width_ratio':('Give target bounding width divided by reference bounding width.',w/ref['size'][0]),
          'fits':('Can the target bounding rectangle fit inside the reference bounding rectangle without rotation?',all(a<=b for a,b in zip(target['size'],ref['size'])))}
    elif nid=='N03':
        shape=target['shape'];sides={'rectangle':4,'triangle':3,'pentagon':5,'hexagon':6,'cross':12,'arrow':7,'ellipse':0,'ring':0}
        sym={'rectangle':2,'triangle':1,'pentagon':1,'hexagon':2,'cross':2,'arrow':1,'ellipse':2,'ring':2}
        values={'shape':('Name the target outer shape (ignore its heading marker).',shape),
            'sides':('How many straight sides does the target boundary have? Curved boundaries count as 0.',sides[shape]),
            'concave_vertices':('How many concave vertices are in the unmarked target boundary?',4 if shape=='cross' else 2 if shape=='arrow' else 0),
            'convex':('Is the filled target region convex, ignoring the heading marker?',shape not in ['cross','ring','arrow']),
            'symmetry_axes':('How many reflection axes does this axis-scaled shape have, ignoring heading?',sym[shape]),
            'shape_match':('Does the reference have the same shape class?',shape==ref['shape']),
            'shape_count':('How many objects have the target shape class?',sum(o['shape']==shape for o in obs)),
            'shape_set':('List all IDs with the target shape class.',sorted(o['id'] for o in obs if o['shape']==shape)),
            'perimeter_class':('Is the outer boundary curved or polygonal?', 'curved' if shape in ['ellipse','ring'] else 'polygonal'),
            'reflected_match':('Does reflection across a horizontal line through its center preserve the unmarked target geometry?',shape in ['rectangle','ellipse','hexagon','cross','ring','arrow']),
            'rotated_match':('Does a half-turn preserve the unmarked target geometry?',shape in ['rectangle','ellipse','hexagon','cross','ring']),
            'holes':('How many enclosed holes are in the unmarked target shape? Ignore the heading marker.',int(shape=='ring'))}
    elif nid=='N06':
        angle=scene['gravity_angle'];down=rotate([0,1],angle);up=[-v for v in down]
        values={'down_vector':('Give the unit gravity direction [x,y] indicated by the plumb line.',down),
            'up_vector':('Give the unit direction opposite gravity.',up),
            'down_angle':('Give gravity angle clockwise from image +x, in [0,360).',(angle+90)%360),
            'camera_roll':('Give the signed rotation from image +y to gravity, positive clockwise, in [-180,180).',(angle+180)%360-180),
            'downhill_step':('Starting at target center, give the endpoint after traveling 2 units along gravity.',[p[i]+2*down[i] for i in range(2)]),
            'fall_direction':('Which cardinal image direction is nearest gravity?', ['right','down','left','up'][int(((angle+90)%360+45)//90)%4]),
            'projection_x':('Give the gravity unit vector x component.',down[0]),'projection_y':('Give its y component.',down[1]),
            'gravity_projection':('Give the signed projection of the target-to-reference displacement onto the gravity direction.',sum((q[i]-p[i])*down[i] for i in range(2))),
            'lower_object':('Which is lower along gravity: target or reference? Return the object ID.',t if sum(p[i]*down[i] for i in range(2))>sum(q[i]*down[i] for i in range(2)) else r),
            'settled_side':('Which side of the square frame receives a freely falling point first from its center?', ['right','bottom','left','top'][int(((angle+90)%360+45)//90)%4]),
            'downhill_rank':('Order object centers by projection onto gravity, lowest projection first; ties by ID.',ids(sorted(obs,key=lambda o:(sum(a*b for a,b in zip(center(o),down)),o['id']))))}
    elif nid=='N07':
        heading=target['heading'];other=ref['heading'];diff=(other-heading)%360
        bearing=math.degrees(math.atan2(q[1]-p[1],q[0]-p[0]))%360
        values={'heading':('Give target heading clockwise from +x, [0,360).',heading),
          'heading_vector':('Give the unit vector of the target heading marker.',rotate([1,0],heading)),
          'clockwise_turn':('Give the clockwise turn required to match reference heading.',diff),
          'counterclockwise_turn':('Give the counterclockwise turn magnitude to match reference heading.',(-diff)%360),
          'relative_heading':('Give signed reference minus target heading in [-180,180).',(diff+180)%360-180),
          'aligned':('Do their headings agree within 5 degrees?',min(diff,360-diff)<=5),
          'parallel':('Are their heading axes parallel within 5 degrees?',min(diff%180,180-diff%180)<=5),
          'perpendicular':('Are their heading axes perpendicular within 5 degrees?',abs(diff%180-90)<=5),
          'heading_rank':('Sort all IDs by clockwise heading, then ID.',ids(sorted(obs,key=lambda o:(o['heading'],o['id'])))),
          'nearest_heading':('Which other object heading is nearest target heading? Ties by ID.',min(others,key=lambda o:(abs((o['heading']-heading+180)%360-180),o['id']))['id']),
          'rotate_to':('Give clockwise rotation needed for target to face +x.',(-heading)%360),
          'face_reference':('Give signed turn in [-180,180) to face reference center.',(bearing-heading+180)%360-180)}
    elif nid=='N08':
        rel=relation(target,ref);pairs=[(a['id'],b['id']) for a,b in combinations(obs,2) if relation(a,b)!='disjoint']
        components=[];remaining=set(ids(obs))
        while remaining:
            todo=[min(remaining)];visited=set()
            while todo:
                n=todo.pop()
                if n in visited:continue
                visited.add(n);todo.extend(b if a==n else a for a,b in pairs if a==n or b==n)
            remaining-=visited;components.append(sorted(visited))
        values={'relation':('Give target bounding-region relation to reference: inside, contains, overlap, touch, disjoint.',rel),
          'touching':('Do their bounding regions touch at the boundary without positive area overlap?',rel=='touch'),
          'overlapping':('Do their bounding regions have positive intersection area?',intersection(target,ref)>0),
          'contained':('Is the target bounding region inside the reference?',rel=='inside'),
          'disjoint':('Are their bounding regions disjoint, including boundaries?',rel=='disjoint'),
          'connected':('Are target and reference connected through touching/overlapping bounding regions?',any(t in c and r in c for c in components)),
          'components':('Give connected components of bounding regions, each sorted by ID, components sorted.',sorted(components)),
          'adjacent_set':('List IDs whose bounding regions touch or intersect target.',sorted(o['id'] for o in others if relation(target,o)!='disjoint')),
          'containment_chain':('List all IDs whose bounding regions contain target, smallest area first.',ids(sorted([o for o in others if relation(target,o)=='inside'],key=lambda o:(area(o),o['id'])))),
          'intersection_area':('Give target/reference bounding intersection area.',intersection(target,ref)),
          'contact_count':('How many other bounding regions touch or intersect target?',sum(relation(target,o)!='disjoint' for o in others)),
          'reachable_set':('List IDs connected to target through bounding region intersections, including target.',next(c for c in components if t in c))}
    elif nid=='N10':
        category=scene['category'];matches=[o for o in obs if o['shape']==category];key=lambda o:o['id']
        boxes=lambda a:{o['id']:bbox(o) for o in a}
        values={'all_boxes':('Give {object_id: [xmin,ymin,xmax,ymax]} for every labeled bounding rectangle.',boxes(obs)),
          'category_boxes':(f'Give bounding boxes for all {category} objects.',boxes(matches)),
          'category_count':(f'Count {category} objects.',len(matches)),
          'category_centers':(f'Give {{object_id:[x,y]}} for all {category} centers.',{o['id']:center(o) for o in matches}),
          'largest_box':('Give the bounding box of the object with largest bounding area.',bbox(max(obs,key=lambda o:(area(o),o['id'])))),
          'smallest_box':('Give the box of the object with smallest bounding area.',bbox(min(obs,key=lambda o:(area(o),o['id'])))),
          'leftmost_box':('Give the leftmost center object bounding box.',bbox(min(obs,key=lambda o:(center(o)[0],o['id'])))),
          'rightmost_box':('Give the rightmost center object bounding box.',bbox(max(obs,key=lambda o:(center(o)[0],o['id'])))),
          'topmost_box':('Give the topmost center object bounding box.',bbox(min(obs,key=lambda o:(center(o)[1],o['id'])))),
          'bottommost_box':('Give the bottommost center object bounding box.',bbox(max(obs,key=lambda o:(center(o)[1],o['id'])))),
          'region_boxes':('Give boxes of all objects whose centers are in x<5 and y<5.',boxes([o for o in obs if center(o)[0]<5 and center(o)[1]<5])),
          'missing_category':(f'Is category {category} absent?',not matches)}
    elif nid=='N11':
        b=bbox(target);px=lambda v:[20+60*x for x in v];corners={'top_left':[0,0],'top_right':[10,0],'bottom_left':[0,10],'bottom_right':[10,10]}
        values={'center':('Give target center [x,y] in grid units.',p),'bbox':('Give its bounding rectangle [xmin,ymin,xmax,ymax] in grid units.',b),
          'center_pixels':('Give target center in pixels, origin at top left.',px(p)),
          'bbox_pixels':('Give target bounding rectangle in pixels.',px(b)),
          'x_coordinate':('Give target center x.',p[0]),'y_coordinate':('Give target center y.',p[1]),
          'quadrant':('Name target quadrant relative to (5,5), using top_left/top_right/bottom_left/bottom_right.',('top_' if p[1]<5 else 'bottom_')+('left' if p[0]<5 else 'right')),
          'nearest_corner':('Which grid corner is nearest the target center?',min(corners,key=lambda k:distance(p,corners[k]))),
          'visible_area':('Give the area of the target bounding rectangle.',area(target)),
          'correction':(f'Correct this erroneous bounding box to the actual one: {[round(v+(.3 if i%2==0 else -.4),3) for i,v in enumerate(b)]}.',b),
          'translation_to_center':('Give [dx,dy] to move the target center to (5,5).',[5-p[0],5-p[1]]),
          'region':('Give its 3x3 grid cell as [column,row], zero based from top left.',[min(2,int(p[0]/(10/3))),min(2,int(p[1]/(10/3)))])}
    elif nid=='N12':
        fact=lambda a,b:[a['id'],'left_of' if center(a)[0]<center(b)[0] else 'right_of',b['id']]
        vf=lambda a,b:[a['id'],'above' if center(a)[1]<center(b)[1] else 'below',b['id']]
        facts=[fact(a,b) for a,b in combinations(obs,2)]
        values={'horizontal_fact':('Express target/reference horizontal relation as [subject,relation,object].',fact(target,ref)),
          'vertical_fact':('Express vertical relation using above/below.',vf(target,ref)),
          'distance_fact':('Express nearest-object fact as [target,nearest,other].',[t,'nearest',ordered[0]['id']]),
          'size_fact':('Express bounding area comparison using larger_than/smaller_than.',[t,'larger_than' if area(target)>area(ref) else 'smaller_than',r]),
          'direction_fact':('Express target heading as [target,heading_degrees,value].',[t,'heading_degrees',target['heading']]),
          'topology_fact':('Express bounding-region relation as [subject,relation,object].',[t,relation(target,ref),r]),
          'all_pair_facts':('Give horizontal facts for all ID-ordered pairs.',facts),
          'target_facts':('Give horizontal facts from target to each other object in ID order.',[fact(target,o) for o in sorted(others,key=lambda o:o['id'])]),
          'scene_facts':('Give horizontal then vertical facts for target/reference.',[fact(target,ref),vf(target,ref)]),
          'ranked_description':('Give IDs in left-to-right order, ties by ID.',ids(sorted(obs,key=lambda o:(center(o)[0],o['id'])))),
          'motion_facts':('Describe the direction the target marker faces using right/down/left/up.', ['right','down','left','up'][int((target['heading']+45)//90)%4]),
          'bounded_description':('Give horizontal facts only for other centers within 3 units of target.',[fact(target,o) for o in sorted(others,key=lambda o:o['id']) if distance(p,center(o))<=3])}
    elif nid=='N13':
        candidates={'resolve_left':[o for o in others if center(o)[0]<p[0]],'resolve_right':[o for o in others if center(o)[0]>p[0]],
            'resolve_above':[o for o in others if center(o)[1]<p[1]],'resolve_below':[o for o in others if center(o)[1]>p[1]],
            'resolve_nearest':ordered[:1],'resolve_farthest':ordered[-1:],
            'resolve_between':[o for o in others if min(p[0],q[0])<center(o)[0]<max(p[0],q[0])],
            'resolve_inside':[o for o in others if relation(o,target)=='inside'],
            'resolve_largest':[max(obs,key=lambda o:(area(o),o['id']))],'resolve_smallest':[min(obs,key=lambda o:(area(o),o['id']))],
            'role_swap':[o for o in obs if center(o)[0]<q[0]],
            'conjunction':[o for o in others if center(o)[0]>p[0] and center(o)[1]<p[1]]}
        descriptions={'resolve_left':'left of target','resolve_right':'right of target','resolve_above':'above target','resolve_below':'below target',
            'resolve_nearest':'nearest to target, ties by ID','resolve_farthest':'farthest from target, ties by ID',
            'resolve_between':'strictly between target and reference along x','resolve_inside':'with bounding rectangle inside target',
            'resolve_largest':'with largest bounding area, ties by ID','resolve_smallest':'with smallest bounding area, ties by ID',
            'role_swap':'left of reference (reference, not target, is the anchor)','conjunction':'right of and above target'}
        values={op:(f'Return sorted IDs satisfying: {descriptions[op]}.',sorted(ids(candidates[op])))}
    else:raise KeyError((nid,op))
    text,answer=values[op]
    return result(title+text,answer)
