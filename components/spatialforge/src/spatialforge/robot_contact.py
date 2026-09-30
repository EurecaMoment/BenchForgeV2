"""Declarative Franka contact actions and simulator-only outcome measurement."""
import math


def validate_robot_action(action, objects):
    required = {'id', 'action', 'object_id', 'robot_id', 'robot_base_position', 'waypoints'}
    optional = {'robot_base_orientation_wxyz', 'end_effector_orientation_wxyz',
                'witness_object_ids', 'observe_seconds', 'camera_id', 'recording', 'contact_object_ids'}
    if not required <= set(action) <= required | optional:
        raise ValueError('robot_push needs id, object_id, robot_id, robot_base_position and waypoints')
    if not objects[action['object_id']]['dynamic']:
        raise ValueError('robot_push needs a dynamic target')
    def vector(value, length):
        if not isinstance(value, list) or len(value) != length or not all(type(v) in (int, float) and math.isfinite(v) for v in value):
            raise ValueError('invalid robot vector')
        if length == 4 and abs(sum(v*v for v in value)-1) > .001:
            raise ValueError('robot orientation must be a unit wxyz quaternion')
    vector(action['robot_base_position'], 3)
    for key in ['robot_base_orientation_wxyz', 'end_effector_orientation_wxyz']:
        if key in action: vector(action[key], 4)
    if not isinstance(action['waypoints'], list) or not action['waypoints']:
        raise ValueError('robot_push needs at least one end-effector waypoint')
    for waypoint in action['waypoints']:
        if set(waypoint) != {'id', 'position', 'duration_s'}:
            raise ValueError('robot waypoint needs id, position and duration_s')
        vector(waypoint['position'], 3)
        duration = waypoint['duration_s']
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('robot waypoint duration_s must be positive')
    witnesses = action.get('witness_object_ids', [])
    if not isinstance(witnesses, list) or len(set(witnesses)) != len(witnesses):
        raise ValueError('robot witness_object_ids must be unique object ids')
    if any(w == action['object_id'] or w not in objects or not objects[w]['dynamic'] for w in witnesses):
        raise ValueError('robot witnesses must name other dynamic objects')
    contacts = action.get('contact_object_ids', [])
    if not isinstance(contacts, list) or len(set(contacts)) != len(contacts) or any(c == action['object_id'] or c not in objects for c in contacts):
        raise ValueError('contact_object_ids must name distinct other scene objects')
    observe = action.get('observe_seconds', 1.5)
    if type(observe) not in (int, float) or not math.isfinite(observe) or observe <= 0:
        raise ValueError('robot observe_seconds must be positive')


def robot_step_count(action):
    return 120 + sum(math.ceil(w['duration_s']*120) for w in action['waypoints']) + math.ceil(action.get('observe_seconds', 1.5)*120)


def object_contact_filters(entity):
    # Tensor filters each name one body/shape. A wildcard over a static assembly
    # can match several entries and prevent the contact view from initializing.
    return [entity['prim_path']] if entity['dynamic'] else entity['collision']['paths']


def contact_observation(step, dt, phase, target_position, contact_positions, forces, robot_filter_count, object_filter_counts=None):
    """Keep robot columns separate from named scene-object contact columns."""
    objects={};offset=robot_filter_count
    for name,position in contact_positions.items():
        count=object_filter_counts[name] if object_filter_counts is not None else 1
        objects[name]={'position':position,'force_on_target_N':[sum(f[axis] for f in forces[offset:offset+count]) for axis in range(3)]}
        offset+=count
    return {'step':step, 'timestamp_sim':step*dt, 'phase':phase, 'target_position':target_position,
            'robot_contact_forces_N':forces[:robot_filter_count],
            'objects':objects}


def summarize_object_contacts(trace):
    """Observed contact and motion, without imposing a manipulation objective."""
    result = {}
    for name, initial in trace[0]['objects'].items():
        magnitudes = [math.sqrt(sum(v*v for v in row['objects'][name]['force_on_target_N'])) for row in trace]
        nonzero = [i for i, force in enumerate(magnitudes) if force > 0]
        final = trace[-1]['objects'][name]['position']
        result[name] = {'nonzero_contact_steps':len(nonzero), 'peak_contact_force_N':max(magnitudes),
                        'first_nonzero_contact_step':trace[nonzero[0]]['step'] if nonzero else None,
                        'last_nonzero_contact_step':trace[nonzero[-1]]['step'] if nonzero else None,
                        'displacement_vector_m':[a-b for a,b in zip(final,initial['position'])]}
    return result


def evaluate_robot_trajectory(samples):
    """Measure contact; a push must retain its support height even if upright."""
    norm = lambda values: math.sqrt(sum(v*v for v in values))
    distance = lambda a,b: norm([x-y for x,y in zip(a,b)])
    contacts = [i for i,r in enumerate(samples) if max((norm(f) for f in r['robot_contact_forces_N']), default=0) > .05]
    first = contacts[0] if contacts else len(samples)-1
    initial, final = samples[0], samples[-1]
    drift = max(distance(r['position'], initial['position']) for r in samples[:first+1])
    witness_moves = {key: distance(final['witnesses'][key], value) for key,value in initial['witnesses'].items()}
    _,x,y,_ = final['orientation_wxyz']
    tilt = math.degrees(math.acos(max(-1., min(1., 1-2*(x*x+y*y)))))
    translation = distance(final['position'], initial['position'])
    vertical = max(abs(r['position'][2]-initial['position'][2]) for r in samples)
    checks = {'target_moved':translation >= .04, 'robot_contact_measured':len(contacts) >= 3,
              'no_early_drift':drift <= .005,
              'witnesses_stationary':all(value <= .01 for value in witness_moves.values()),
              'target_upright':tilt <= 20, 'target_height_maintained':vertical <= .02}
    return {'success':all(checks.values()), 'checks':checks, 'translation_m':translation,
            'target_displacement_vector_m':[a-b for a,b in zip(final['position'],initial['position'])],
            'robot_contact_sample_count':len(contacts), 'pre_contact_drift_m':drift,
            'peak_filtered_robot_force_N':max(norm(f) for r in samples for f in r['robot_contact_forces_N']),
            'witness_displacements_m':witness_moves, 'final_target_axis_tilt_deg':tilt,
            'max_vertical_displacement_m':vertical,
            'first_contact_step':samples[first]['step'] if contacts else None,
            'criteria':{'min_translation_m':.04,'contact_force_threshold_N':.05,'min_contact_samples':3,
                        'max_pre_contact_drift_m':.005,'max_witness_translation_m':.01,'max_final_root_axis_tilt_deg':20,
                        'max_vertical_displacement_m':.02}}


def evaluate_robot_visibility(measured, before, after):
    measured['checks']['target_visible_before_after'] = before['visible_pixels'] > 0 and after['visible_pixels'] > 0
    measured['success'] = all(measured['checks'].values())
    return measured
