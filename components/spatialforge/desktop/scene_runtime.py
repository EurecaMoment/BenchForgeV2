"""Small, dependency-free scene execution helpers.

This module keeps v2 declarative metadata separate from Isaac USD authoring.
Rooms describe spatial context only; geometry is always supplied by scene
objects (walls, floors, doors, windows, etc.).
"""
import math

SUPPORTED_RENDERERS = {'RaytracedLighting', 'PathTracing'}
LIGHT_MAPPING = {'point': 'sphere', 'spot': 'sphere', 'area': 'rect',
                 'directional': 'distant', 'sun': 'distant', 'environment': 'dome'}


def render_options(program, capture, *, has_gaussians=False):
    environment = program.get('render_environment') or {}
    options = dict(environment)
    options.update({key: value for key, value in (capture or {}).items() if key in {'renderer', 'samples_per_pixel', 'exposure'}})
    renderer = options.get('renderer', 'PathTracing' if has_gaussians else 'RaytracedLighting')
    if has_gaussians and renderer == 'PathTracing':
        options.setdefault('samples_per_pixel', 128)
    if renderer not in SUPPORTED_RENDERERS:
        raise ValueError('unsupported Isaac renderer: '+str(renderer))
    if 'samples_per_pixel' in options and (type(options['samples_per_pixel']) is not int or not 16 <= options['samples_per_pixel'] <= 512):
        raise ValueError('samples_per_pixel must be 16..512')
    if 'exposure' in options:_number(options['exposure'], -10, 10, 'exposure')
    return {'renderer': renderer, **{key: options[key] for key in ('samples_per_pixel', 'exposure') if key in options}}


def room_metadata(program):
    """Return room records without creating an implicit envelope."""
    portals = program.get('portals', [])
    return [
        {
            'room_id': room['id'],
            'kind': 'metadata_only',
            'bounds': room['bounds'],
            'portal_count': sum(1 for portal in portals if room['id'] in {portal.get('from_room'), portal.get('to_room')}),
            'geometry_source': 'explicit_scene_objects',
        }
        for room in program.get('rooms', [])
    ]


def material_for(program, obj):
    """Merge a named v2 material with object-local appearance overrides."""
    material_id = obj.get('material_id')
    materials = {item['id']: item for item in program.get('materials', [])}
    material = dict(materials.get(material_id) or {})
    appearance = dict(material.get('appearance') or {})
    appearance.update(obj.get('appearance') or {})
    for key in ('roughness', 'metallic', 'specular', 'ior'):
        if key in material and key not in appearance:
            appearance[key] = material[key]
    color = material.get('base_color', obj.get('color', [.7, .7, .7]))
    return {'id': material_id, 'record': material, 'appearance': appearance, 'color': list(color[:3])}


def part_material_for(program, parent_material, part):
    """A named part material replaces inheritance; local appearance overrides it."""
    if 'material_id' in part:
        return material_for(program, part)
    return {'id':parent_material['id'], 'record':parent_material['record'],
            'appearance':{**parent_material['appearance'], **part.get('appearance', {})},
            'color':list(part['color'])}


def light_specs(program):
    """Normalize user lights; defaults are only used for an empty light list."""
    lights = program.get('lights') or []
    if not lights:
        return [
            {'id': 'default_sky', 'kind': 'dome', 'source_kind': 'environment', 'position': [0, 0, 0], 'intensity': 600, 'color': [1, 1, 1]},
            {'id': 'default_sun', 'kind': 'distant', 'source_kind': 'sun', 'position': [0, 0, 0], 'intensity': 1600, 'color': [1, 1, 1], 'direction': [.4, -.3, -1]},
        ]
    result = []
    for light in lights:
        source_kind = light['kind'].lower()
        if source_kind not in LIGHT_MAPPING:
            raise ValueError('unsupported light kind: '+source_kind)
        if not light.get('enabled', True):continue
        if 'direction' in light and sum(v*v for v in light['direction']) < 1e-12:
            raise ValueError('light direction must be nonzero')
        if source_kind == 'spot':
            outer=light.get('outer_cone_deg', 45);inner=light.get('inner_cone_deg', 0)
            if not 0 <= inner <= outer <= 180 or outer == 0:raise ValueError('invalid spot cone angles')
        result.append(dict(light, kind=LIGHT_MAPPING[source_kind], source_kind=source_kind))
    return result


def camera_up(position, target):
    """USD look-at needs an up vector not parallel to the viewing direction."""
    delta=[target[i]-position[i] for i in range(3)]
    norm=math.sqrt(sum(v*v for v in delta))
    if norm < 1e-8:raise ValueError('camera position equals target')
    return [0, 1, 0] if abs(delta[2])/norm > .999 else [0, 0, 1]


def _number(value, minimum, maximum, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('invalid '+name)
    return float(value)


def interaction_plan(program):
    """Compile only explicit supported actions; never turn affordances into success."""
    declarations=program.get('interactions', program.get('affordances', []))
    if not isinstance(declarations, list):raise ValueError('interactions must be a list')
    if len(declarations)>16:raise ValueError('desktop supports at most 16 interaction attempts')
    objects={obj['id']:obj for obj in program['objects']}
    result=[];ids=set();total_steps=0
    defaults={'min_displacement_m':.02, 'max_displacement_m':1., 'max_vertical_displacement_m':.1,
              'max_final_speed_m_s':.1, 'max_initial_speed_m_s':.03, 'max_drift_m':.005}
    for declaration in declarations:
        item=dict(declaration)
        if item.get('id') in ids:raise ValueError('duplicate interaction ID')
        ids.add(item.get('id'))
        if item.get('action')=='robot_push':
            from spatialforge.robot_contact import robot_step_count
            total_steps+=robot_step_count(item)
            result.append({**item,'supported':True})
            continue
        if item.get('action')!='apply_force':
            result.append({**item, 'supported':False, 'reason':'no desktop executor for this declared action'})
            continue
        obj=objects.get(item.get('object_id'))
        if not obj or not obj['dynamic']:raise ValueError('apply_force requires an existing dynamic object')
        force=item.get('force_newtons')
        if not isinstance(force, list) or len(force)!=3:raise ValueError('force_newtons must be a three-vector')
        force=[_number(v,-1000,1000,'force_newtons') for v in force]
        if not 0 < math.sqrt(sum(v*v for v in force)) <= 1000:raise ValueError('force magnitude must be nonzero and <=1000 N')
        item.update(force_newtons=force,supported=True)
        for key,default in [('duration_steps',30),('observe_steps',90)]:
            value=item.get(key,default)
            if type(value) is not int or not 1 <= value <= 600:raise ValueError('invalid '+key)
            item[key]=value
        for key,default in defaults.items():item[key]=_number(item.get(key,default),0,100,key)
        if not 0 < item['min_displacement_m'] <= item['max_displacement_m']:raise ValueError('invalid displacement interval')
        total_steps+=item['duration_steps']+item['observe_steps']
        result.append(item)
    if total_steps>10000:raise ValueError('desktop interaction step budget exceeded')
    return result


def select_interaction_camera(cameras, action, center):
    """Use the requested view, otherwise the authored view aimed closest to the object."""
    if 'camera_id' in action:
        return next(camera for camera in cameras if camera.get('id')==action['camera_id'])
    def aim(camera):
        forward=[t-p for t,p in zip(camera['target'],camera['position'])]
        offset=[t-p for t,p in zip(center,camera['position'])]
        distance=math.sqrt(sum(v*v for v in offset))
        if distance==0:return (2.,0.)
        alignment=sum(a*b for a,b in zip(forward,offset))/(math.sqrt(sum(v*v for v in forward))*distance)
        return (1.-alignment,distance)
    return min(cameras,key=aim)


def evaluate_force_trajectory(action, samples, initial_drift_m):
    """Assess observed physics only, including no-op, falling and drift failures."""
    norm=lambda vector:math.sqrt(sum(v*v for v in vector))
    expected=action['duration_steps']+action['observe_steps']+1
    if len(samples)!=expected:raise ValueError('incomplete interaction trajectory')
    for sample in samples:
        for key,length in [('position',3),('orientation_wxyz',4),('linear_velocity_m_s',3)]:
            if len(sample[key])!=length or not all(math.isfinite(v) for v in sample[key]):raise ValueError('nonfinite interaction state')
    delta=[samples[-1]['position'][i]-samples[0]['position'][i] for i in range(3)]
    force_norm=norm(action['force_newtons'])
    projected=sum(delta[i]*action['force_newtons'][i]/force_norm for i in range(3))
    peak_vertical=max(abs(row['position'][2]-samples[0]['position'][2]) for row in samples)
    initial_speed=norm(samples[0]['linear_velocity_m_s']);final_speed=norm(samples[-1]['linear_velocity_m_s'])
    checks={'initially_stable':math.isfinite(initial_drift_m) and initial_drift_m<=action['max_drift_m'] and initial_speed<=action['max_initial_speed_m_s'],
            'moved_in_force_direction':projected>=action['min_displacement_m'],
            'within_displacement_bound':norm(delta)<=action['max_displacement_m'],
            'within_vertical_bound':peak_vertical<=action['max_vertical_displacement_m'],
            'stopped_after_force':final_speed<=action['max_final_speed_m_s']}
    return {'success':all(checks.values()),'checks':checks,'translation_m':norm(delta),'projected_displacement_m':projected,
            'peak_vertical_displacement_m':peak_vertical,'initial_drift_m':initial_drift_m,
            'initial_speed_m_s':initial_speed,'final_speed_m_s':final_speed}


def mesh_import_plan(record):
    """Describe imported material fallback without requiring pxr in unit tests."""
    materials = record.get('materials') or []
    textures = sum(bool(material.get('textures', {}).get('base_color')) for material in materials)
    return {
        'materials': len(materials),
        'textured_materials': textures,
        'uses_vertex_color_fallback': True,
        'coordinate_frame': record.get('coordinate_frame'),
    }


def box_mesh_with_metric_uv(size, uv_scale_m):
    """Six outward-wound quad faces with hard normals and meter-based UVs."""
    if not isinstance(size,list) or len(size)!=3:raise ValueError('invalid textured box size')
    if not isinstance(uv_scale_m,list) or len(uv_scale_m)!=2:raise ValueError('invalid uv_scale_m')
    sx,sy,sz=[_number(value,0,1000,'textured box size') for value in size]
    if min(sx,sy,sz)<=0:raise ValueError('textured box dimensions must be positive')
    su,sv=[_number(value,.01,100,'uv_scale_m') for value in uv_scale_m]
    x,y,z=sx/2,sy/2,sz/2
    faces=[
        ([(x,-y,-z),(x,y,-z),(x,y,z),(x,-y,z)],(1,0,0),sy,sz),
        ([(-x,y,-z),(-x,-y,-z),(-x,-y,z),(-x,y,z)],(-1,0,0),sy,sz),
        ([(x,y,-z),(-x,y,-z),(-x,y,z),(x,y,z)],(0,1,0),sx,sz),
        ([(-x,-y,-z),(x,-y,-z),(x,-y,z),(-x,-y,z)],(0,-1,0),sx,sz),
        ([(-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)],(0,0,1),sx,sy),
        ([(-x,y,-z),(x,y,-z),(x,-y,-z),(-x,-y,-z)],(0,0,-1),sx,sy),
    ]
    points=[];uv=[];normals=[]
    for vertices,normal,width,height in faces:
        points.extend(vertices);normals.append(normal)
        uv.extend([(0,0),(width/su,0),(width/su,height/sv),(0,height/sv)])
    return {'points':points,'face_vertex_counts':[4]*6,'face_vertex_indices':list(range(24)),
            'normals':normals,'st':uv,'uv_scale_m':[su,sv]}


def transform_mesh_geometry(vertices, requested_size, coordinate_frame, mesh_transform=None):
    # Shared with task-code previews; callers use the same exact vertex transform.
    from spatialforge.mesh_geometry import transform_mesh_geometry as transform
    return transform(vertices,requested_size,coordinate_frame,mesh_transform)
