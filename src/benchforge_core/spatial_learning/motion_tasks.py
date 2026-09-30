"""Time-resolved observations, correspondence and history queries."""
import math
import random
from copy import deepcopy
from .scenes import rotate,bbox
from .geometry_tasks import result,distance


def observed_scenes(scene,nid):
    if nid=='N09':
        rng=random.Random(scene['seed']+19);permutation=list(range(len(scene['objects'])));rng.shuffle(permutation)
        second=deepcopy(scene);second['objects']=[]
        angle=rng.choice([90,180,270]);removed=set(rng.sample(permutation,rng.randrange(3)))
        permutation=[i for i in permutation if i not in removed or i==0]
        for local,original in enumerate(permutation):
            obj=deepcopy(scene['objects'][original]);obj['id']=f'object_{local}'
            obj['position']=[x+5 for x in rotate([v-5 for v in obj['position']],angle)];obj['heading']=(obj['heading']+angle)%360
            second['objects'].append(obj)
        for extra in range(scene['seed']%2):
            obj=deepcopy(scene['objects'][0]);obj.update(id=f'object_{len(second["objects"])}',color='black',shape='diamond',position=[8.8,8.8])
            second['objects'].append(obj)
        return [scene,second],{f'object_{original}':f'object_{local}' for local,original in enumerate(permutation)}
    frames=[];m=scene['motion']
    if nid=='N04':
        # Keep all calibrated landmarks inside the common field of view after
        # observer rotation and translation.
        scene=deepcopy(scene)
        for obj in scene['objects']:
            obj['position']=[5+(v-5)*.45 for v in obj['position']]
            obj['size']=[v*.65 for v in obj['size']]
    for step,t in enumerate(m['times']):
        frame=deepcopy(scene)
        if nid=='N04':
            pose=m['camera_poses'][step]
            for obj in frame['objects']:
                p=rotate([obj['position'][i]-5-pose[i] for i in range(2)],-pose[2])
                obj['position']=[v+5 for v in p];obj['heading']=(obj['heading']-pose[2])%360
        else:frame['objects'][0]['position']=m['positions'][step]
        frames.append(frame)
    return frames,None


def task(scene,nid,op):
    m=scene['motion'];positions=m['positions'];times=m['times'];delta=[positions[-1][i]-positions[0][i] for i in range(2)]
    velocities=[[(b[j]-a[j])/(times[i+1]-times[i]) for j in range(2)] for i,(a,b) in enumerate(zip(positions,positions[1:]))]
    speeds=[round(math.hypot(*v),6) for v in velocities];path=sum(distance(a,b) for a,b in zip(positions,positions[1:]))
    inputs={'times_seconds':times,'target':'object_0','coordinate_convention':'image x right, y down; each grid spacing is one unit'}
    if nid=='N04':
        poses=m['camera_poses'];d=poses[-1][:2];angle=poses[-1][2];camera_path=sum(distance(a[:2],b[:2]) for a,b in zip(poses,poses[1:]))
        inputs.update(scene_static=True,calibrated_orthographic_view=True,rotation_center_grid=[5,5],first_camera_pose={'position':[0,0],'heading':0})
        values={'translation':('Infer total camera translation from the static landmarks, in initial axes.',d),
          'rotation':('Infer total signed camera rotation in degrees (positive clockwise in image axes).',angle),
          'heading':('Give final camera heading modulo 360 degrees.',angle%360),
          'travel_distance':('Give the camera displacement magnitude.',math.hypot(*d)),
          'displacement_x':('Give camera x displacement.',d[0]),'displacement_y':('Give camera y displacement.',d[1]),
          'inverse_translation':('Give initial origin position in final camera axes.',rotate([-x for x in d],-angle)),
          'endpoint':('Give final camera pose [x,y,heading] in the initial frame.',poses[-1]),
          'path_length':('Give the translation polyline length over the observed camera poses.',camera_path),
          'return_to_start':('Give the displacement in initial axes needed to return the camera to its initial position.',[-x for x in d]),
          'turn_direction':('Is the net camera rotation clockwise, counterclockwise, or zero?', 'clockwise' if angle>0 else 'counterclockwise' if angle<0 else 'zero'),
          'pose_sequence':('Give camera poses as [[x,y,heading_degrees],...] for each observation.',poses)}
    elif nid=='N05':
        ref=scene['objects'][1]['position'];ds=[distance(p,ref) for p in positions]
        values={'displacement':('Give target last minus first position.',delta),
          'velocity':('Give average target velocity over the whole observation interval.',[x/(times[-1]-times[0]) for x in delta]),
          'speed':('Give target average path speed.',path/(times[-1]-times[0])),
          'acceleration':('Give change from first to last segment velocity divided by the time between their midpoint timestamps.',[(velocities[-1][i]-velocities[0][i])/((times[-1]+times[-2]-times[0]-times[1])/2) for i in range(2)]),
          'direction':('Give net movement angle clockwise from image +x, [0,360).',math.degrees(math.atan2(delta[1],delta[0]))%360),
          'path_length':('Give total observed polyline length.',path),
          'approaching':('Is target nearer object_1 at the last observation than at the first?',ds[-1]<ds[0]),
          'separating':('Is target farther from object_1 at the last observation?',ds[-1]>ds[0]),
          'fastest':('Which observed time interval index (zero based) has maximum speed? Earliest on ties.',max(range(len(speeds)),key=lambda i:speeds[i])),
          'slowest':('Which interval index has minimum speed? Earliest on ties.',min(range(len(speeds)),key=lambda i:speeds[i])),
          'crossing':('Does the observed target polyline cross or touch the vertical line x=5?',min(p[0] for p in positions)<=5<=max(p[0] for p in positions)),
          'motion_sequence':('Give target displacement vectors between each consecutive pair.',[[b[i]-a[i] for i in range(2)] for a,b in zip(positions,positions[1:])])}
    elif nid=='N14':
        ds=[distance(p,[5,5]) for p in positions];cross=sum((a[0]-5)*(b[1]-5)-(a[1]-5)*(b[0]-5) for a,b in zip(positions,positions[1:]))
        reverse=any(sum(a*b for a,b in zip(u,v))<0 for u,v in zip(velocities,velocities[1:]));stopped=any(s<.01 for s in speeds)
        event='stationary' if path<.01 else 'reverse' if reverse else 'stop_start' if stopped else 'approach' if ds[-1]<ds[0] else 'depart'
        values={'event':('Classify the sequence: stationary if path<.01; else reverse if consecutive displacements oppose; else stop_start if any segment speed<.01; else approach/depart relative to (5,5).',event),
          'approach':('Does distance to (5,5) decrease from first to last frame?',ds[-1]<ds[0]),
          'depart':('Does distance to (5,5) increase from first to last frame?',ds[-1]>ds[0]),
          'clockwise':('Is summed signed cross product around (5,5) positive? This is clockwise circulation in image axes.',cross>0),
          'counterclockwise':('Is summed signed cross product around (5,5) negative?',cross<0),
          'stationary':('Is total observed path shorter than .01 units?',path<.01),
          'accelerate':('Is last segment speed greater than first by more than .01?',speeds[-1]>speeds[0]+.01),
          'decelerate':('Is last segment speed less than first by more than .01?',speeds[-1]<speeds[0]-.01),
          'reverse':('Do any consecutive nonzero displacement vectors have negative dot product?',reverse),
          'stop_start':('Is there a segment below .01 speed and a later segment above .01?',any(speeds[i]<.01 and any(s>.01 for s in speeds[i+1:]) for i in range(len(speeds)))),
          'crossing':('Does the observed path cross or touch x=5?',min(p[0] for p in positions)<=5<=max(p[0] for p in positions)),
          'following':('Are all consecutive nonzero displacement directions consistent (nonnegative dot products)?',not reverse)}
    elif nid=='N18':
        inputs['history_setting']='All previous observations remain in the provided history. This measures retrieval from context, not persistent external memory.'
        cells=[[min(2,int(p[0]/(10/3))),min(2,int(p[1]/(10/3)))] for p in positions]
        event_index=len(times)//2;inputs['marked_event_time']=times[event_index]
        values={'initial_position':('Recall object_0 position in the first observation.',positions[0]),
          'last_position':('Recall object_0 position in the last observation.',positions[-1]),
          'previous_position':('Recall its position in the penultimate observation.',positions[-2]),
          'visited_nodes':('List distinct 3x3 cells visited, sorted; cells are [column,row] from top left.',sorted([list(c) for c in set(tuple(c) for c in cells)])),
          'visit_order':('Recall the sequence of 3x3 cells occupied.',cells),
          'last_seen':('Give the final observed timestamp.',times[-1]),
          'first_seen':('Give the earliest observed timestamp.',times[0]),
          'observation_count':('How many distinct observation timestamps are in the history?',len(times)),
          'recalled_edges':('Give pairs of consecutive visited 3x3 cells, including repeats.',[[a,b] for a,b in zip(cells,cells[1:])]),
          'recalled_heading':('Recall object_0 heading in the first observation.',scene['objects'][0]['heading']),
          'event_before':('Recall the position immediately before marked_event_time.',positions[event_index-1]),
          'event_after':('Recall the position immediately after marked_event_time.',positions[event_index+1])}
    elif nid=='N09':
        frames,matches=observed_scenes(scene,nid);target='object_0';local=matches[target];b=next(o for o in frames[1]['objects'] if o['id']==local)
        inputs={'view_A_target':target,'labels':'Numeric labels are independent within each view. Match by visible shape and color; no shared entity labels.'}
        values={'target_match':('Which B-local ID is the A target?',local),
          'all_matches':('Give {A-local ID: B-local ID} for every object.',matches),
          'unmatched_a':('List A-local IDs that have no corresponding B object.',sorted(o['id'] for o in scene['objects'] if o['id'] not in matches)),
          'unmatched_b':('List B-local IDs that have no corresponding A object.',sorted(o['id'] for o in frames[1]['objects'] if o['id'] not in matches.values())),
          'match_count':('How many shared entities appear in both views?',len(matches)),
          'correspondence_pairs':('Give [A-local ID,B-local ID] pairs sorted by A ID.',sorted([a,b] for a,b in matches.items())),
          'target_bbox':('Give the bounding box of the A target in B grid coordinates.',bbox(b)),
          'target_center':('Give the A target center in B grid coordinates.',b['position']),
          'changed_position':('Give B minus A center coordinates for the same target.',[b['position'][i]-scene['objects'][0]['position'][i] for i in range(2)]),
          'changed_orientation':('Give clockwise heading change modulo 360 for the target.',(b['heading']-scene['objects'][0]['heading'])%360),
          'same_entity':('Do local ID object_0 in A and local ID object_0 in B identify the same entity?',local=='object_0'),
          'permutation':('For A IDs in ascending order, give their B-local IDs.',[matches[k] for k in sorted(matches)])}
    else:raise KeyError((nid,op))
    question,answer=values[op]
    return result(question,answer,'numeric',inputs=inputs)
