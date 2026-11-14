"""Model proposals are data; only these bounded operations reach Isaac."""
from scene_production.contracts.scene_program import SCENE_V2_MAX_OBJECTS
from scene_production.contracts.scene_program import SCENE_SCHEMAS
from scene_production.contracts.scene_program import SCENE_MAX_ROOMS
from scene_production.contracts.scene_program import SCENE_MAX_ZONES
from scene_production.contracts.scene_program import SCENE_MAX_PORTALS
from scene_production.contracts.scene_program import SCENE_MAX_ASSETS
from scene_production.contracts.scene_program import LIGHT_KINDS
from scene_production.contracts.scene_program import LIGHT_FIELDS
from scene_production.contracts.scene_program import RENDER_ENVIRONMENT_FIELDS
from scene_production.contracts.scene_program import RENDERERS
from scene_production.contracts.scene_program import SPATIALTREE_RECORDING_FIELDS
from scene_production.contracts.scene_program import APPEARANCE_FIELDS
from scene_production.contracts.scene_program import SCENE_SCHEMA_DESCRIPTION
import math
import json
import re
from copy import deepcopy
from scene_production.server.scene_program.catalog.native import ASSETS
from scene_production.server.scene_program.catalog.native import NATIVE_MATERIALS
from scene_production.server.scene_program.catalog.environments import ENVIRONMENTS
from scene_production.server.scene_program.geometry.support_graph import objects_in_support_order
def require(ok, message):
    if not ok: raise ValueError(message)
def ident(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value),
            f'invalid ID {value!r}: use letters, digits and underscores, starting with a letter or underscore')
    return value
def numbers(value, length, lo, hi, context='vector'):
    label = 'invalid vector' if context == 'vector' else context
    require(isinstance(value, list) and len(value) == length, f'{label}: expected {length} numbers; got {value!r}')
    require(all(type(v) in (float, int) and math.isfinite(v) and lo <= v <= hi for v in value),
            f'{label}: expected finite numbers in [{lo}, {hi}]; got {value!r}')
def dimensions(value, context='size'):
    numbers(value, 3, 0, 1000, context)
    require(all(v > 0 for v in value), f'{context}: dimensions must be positive; got {value!r}')
def validate_appearance(appearance,context='appearance'):
    require(isinstance(appearance,dict),f'{context}: appearance must be an object')
    unknown=set(appearance)-APPEARANCE_FIELDS
    require(not unknown,f'{context}: unsupported appearance fields {sorted(unknown)}; allowed={sorted(APPEARANCE_FIELDS)}. Replace the complete appearance record with supported fields; generic opacity/transmission are not implemented. native_opacity_multiplier only works on explicitly registered capable native assets. Do not move unsupported fields into metadata and claim a rendering effect.')
    for key in ('roughness','metallic','specular','native_opacity_multiplier'):
        if key in appearance:numbers([appearance[key]],1,0,1)
    if 'ior' in appearance:numbers([appearance['ior']],1,1,3,'appearance.ior')
    if 'texture_id' in appearance:
        require(isinstance(appearance['texture_id'],str) and appearance['texture_id'] in NATIVE_MATERIALS,'texture_id must be an operator-registered material ID')
    if 'uv_scale_m' in appearance:numbers(appearance['uv_scale_m'],2,.01,100)
    if 'texture_tint' in appearance:numbers(appearance['texture_tint'],3,0,1,'appearance.texture_tint')
def _merge_extension_value(base, added, path):
    """Append new metadata while retaining the identity of existing records."""
    if isinstance(base, dict) and isinstance(added, dict):
        merged = deepcopy(base)
        for key, value in added.items():
            merged[key] = _merge_extension_value(base[key], value, f'{path}.{key}') if key in base else deepcopy(value)
        return merged
    if isinstance(base, list) and isinstance(added, list):
        merged = deepcopy(base)
        by_id = {item['id']: item for item in base if isinstance(item, dict) and 'id' in item}
        for item in added:
            if isinstance(item, dict) and item.get('id') in by_id:
                require(item == by_id[item['id']], f'extension overwrites existing metadata: {path}.{item["id"]}')
            elif item not in merged:
                merged.append(deepcopy(item))
        return merged
    require(base == added, f'extension overwrites existing metadata: {path}')
    return deepcopy(base)
def merge_scene_extension(base, added):
    """Merge a planner delta without mutating the base or the raw proposal."""
    require(isinstance(added, dict), 'scene must be an object')
    require(isinstance(added.get('objects'), list), 'extension needs new objects')
    original = {obj['id'] for obj in base['objects']}
    for obj in added['objects']:
        require(isinstance(obj, dict), 'invalid object')
        require(obj.get('id') not in original, 'extension overwrites existing entities; return only new objects')
    merged = deepcopy(base)
    for key, value in added.items():
        if key == 'objects':
            merged[key] = deepcopy(base[key]) + deepcopy(value)
        elif key in {'scene_id', 'title', 'cameras'}:
            merged[key] = deepcopy(value)
        elif key == 'schema':
            require(value in SCENE_SCHEMAS, 'unsupported scene schema')
            merged[key] = 'benchforge.scene/v2' if base[key].endswith('/v2') else value
        else:
            merged[key] = _merge_extension_value(base[key], value, key) if key in base else deepcopy(value)
    merged['schema'] = merged['schema']
    return merged
def _validate_force_action(action, objects):
    required = {'id', 'action', 'object_id', 'force_newtons'}
    optional = {'duration_steps', 'observe_steps', 'min_displacement_m', 'max_displacement_m',
                'max_vertical_displacement_m', 'max_final_speed_m_s', 'max_initial_speed_m_s', 'max_drift_m', 'camera_id', 'recording', 'contact_object_ids'}
    require(required <= set(action) <= required | optional, 'invalid apply_force fields')
    require(action['object_id'] in objects and objects[action['object_id']]['dynamic'], 'apply_force needs a dynamic object')
    numbers(action['force_newtons'], 3, -1000, 1000)
    magnitude_sq = sum(value * value for value in action['force_newtons'])
    require(1e-12 < magnitude_sq <= 1000000, 'apply_force magnitude must be nonzero and <= 1000 N')
    for key, default in (('duration_steps', 30), ('observe_steps', 90)):
        value = action.get(key, default)
        require(type(value) is int and 1 <= value <= 600, f'{key} must be 1..600')
    contacts = action.get('contact_object_ids', [])
    require(isinstance(contacts, list) and all(isinstance(c, str) and c in objects and c != action['object_id'] for c in contacts)
            and len(set(contacts)) == len(contacts), 'contact_object_ids must name distinct other scene objects')
    for key in optional - {'duration_steps', 'observe_steps', 'camera_id', 'recording', 'contact_object_ids'}:
        if key in action:
            numbers([action[key]], 1, 0, 100)
    minimum = action.get('min_displacement_m', .02)
    maximum = action.get('max_displacement_m', 1)
    require(0 < minimum <= maximum, 'apply_force displacement bounds must satisfy 0 < min <= max')
def _optional_string(value, message='invalid string', max_len=200):
    require(isinstance(value, str) and 0 < len(value) <= max_len, message)
def _bounded_list(value, max_len, message):
    require(isinstance(value, list) and len(value) <= max_len, message)
def _validate_spatialtree_recording(recording):
    """Validate the opt-in native trajectory recording settings."""
    require(isinstance(recording, dict), 'recording.spatialtree must be an object')
    require(set(recording) <= SPATIALTREE_RECORDING_FIELDS,
            'recording.spatialtree accepts scenario_id and split; image size and fps come from actual capture settings')
    if 'scenario_id' in recording:
        _optional_string(recording['scenario_id'], 'recording.spatialtree.scenario_id must be a non-empty string', 160)
    if 'split' in recording:
        require(isinstance(recording['split'], str) and recording['split'] in {'train', 'dev', 'test', 'sealed'},
                'recording.spatialtree.split must be train, dev, test or sealed')
def _validate_camera_path(path):
    require(isinstance(path, list) and len(path) >= 2, 'recording.camera_path needs at least two keyframes')
    previous = -1
    for frame in path:
        require(isinstance(frame, dict) and set(frame) == {'step', 'position', 'target'},
                'camera path keyframes need step, position and target')
        require(type(frame['step']) is int and previous < frame['step'] <= 10000,
                'camera path steps must increase within 0..10000')
        numbers(frame['position'], 3, -1000, 1000, 'camera path position')
        numbers(frame['target'], 3, -1000, 1000, 'camera path target')
        require(sum((p-t)**2 for p,t in zip(frame['position'], frame['target'])) > 1e-8,
                'camera path position and target must differ')
        previous = frame['step']
    require(path[0]['step'] == 0, 'camera path must begin at step 0 relative to the first recording sample')
def _validate_bounds(value, message='invalid bounds'):
    """Accept either [x, y, z] size or {center, size} room-style bounds."""
    if isinstance(value, list):
        dimensions(value)
        return
    require(isinstance(value, dict) and set(value) <= {'center', 'size'}, message)
    require({'center', 'size'} <= set(value), message)
    numbers(value['center'], 3, -1000, 1000)
    dimensions(value['size'])
def _validate_scene_extensions(p):
    """Validate open-ended v2 scene metadata without constraining generators.

    These fields describe intent and provenance.  Isaac-specific validity is
    established later by the desktop simulator and remains separate from this
    lightweight contract.
    """
    object_ids = {o.get('id') for o in p.get('objects', []) if isinstance(o, dict)}
    rooms = p.get('rooms', [])
    _bounded_list(rooms, SCENE_MAX_ROOMS, 'too many rooms')
    room_ids = set()
    for room in rooms:
        require(isinstance(room, dict), 'invalid room')
        require({'id', 'name', 'bounds'} <= set(room), 'room needs id, name and bounds')
        require(set(room) <= {'id', 'name', 'bounds', 'floor_z', 'representation', 'geometry', 'semantic_role'}, 'invalid room fields')
        ident(room['id']); require(room['id'] not in room_ids, 'duplicate room ID')
        _optional_string(room['name'], 'invalid room name')
        _validate_bounds(room['bounds'])
        if 'floor_z' in room:
            require(type(room['floor_z']) in (int, float) and math.isfinite(room['floor_z']) and -100 <= room['floor_z'] <= 100, 'invalid room floor')
        representation = room.get('representation', 'bounds_only')
        require(representation in {'bounds_only', 'explicit_objects', 'imported_geometry'}, 'invalid room representation')
        if 'semantic_role' in room: _optional_string(room['semantic_role'], 'invalid room semantic role')
        if representation == 'explicit_objects':
            geometry = room.get('geometry')
            require(isinstance(geometry, dict) and set(geometry) <= {'object_ids', 'notes'} and 'object_ids' in geometry, 'explicit room geometry needs object_ids')
            _bounded_list(geometry['object_ids'], SCENE_V2_MAX_OBJECTS, 'too many room geometry objects')
            require(all(item in object_ids for item in geometry['object_ids']), 'room geometry object must exist')
        elif 'geometry' in room:
            require(isinstance(room['geometry'], dict), 'invalid room geometry')
        room_ids.add(room['id'])

    zones = p.get('zones', [])
    _bounded_list(zones, SCENE_MAX_ZONES, 'too many zones')
    zone_ids = set()
    for zone in zones:
        require(isinstance(zone, dict), 'invalid zone')
        require({'id', 'name', 'bounds'} <= set(zone), 'zone needs id, name and bounds')
        ident(zone['id']); require(zone['id'] not in zone_ids, 'duplicate zone ID')
        _optional_string(zone['name'], 'invalid zone name')
        _validate_bounds(zone['bounds'])
        if 'room_id' in zone:
            require(zone['room_id'] in room_ids, 'zone room must reference a room')
        if 'purpose' in zone:
            _optional_string(zone['purpose'], 'invalid zone purpose')
        zone_ids.add(zone['id'])

    portals = p.get('portals', [])
    _bounded_list(portals, SCENE_MAX_PORTALS, 'too many portals')
    portal_ids = set()
    for portal in portals:
        require(isinstance(portal, dict), 'invalid portal')
        require({'id', 'kind', 'position', 'size'} <= set(portal), 'portal needs id, kind, position and size')
        ident(portal['id']); require(portal['id'] not in portal_ids, 'duplicate portal ID')
        _optional_string(portal['kind'], 'invalid portal kind', 40)
        numbers(portal['position'], 3, -1000, 1000); numbers(portal['size'], 3, .001, 100)
        for key in ('from_room', 'to_room'):
            if key in portal:
                require(portal[key] in room_ids, 'portal room must reference a room')
        if 'passable' in portal: require(type(portal['passable']) is bool, 'invalid portal passability')
        portal_ids.add(portal['id'])

    assets = p.get('assets', [])
    _bounded_list(assets, SCENE_MAX_ASSETS, 'too many assets')
    asset_ids = set()
    asset_kinds = {'builtin', 'usd', 'mesh', 'generated', 'diffusion', 'sam3d', 'procedural', 'imported', 'unknown'} | set(ASSETS)
    for asset in assets:
        require(isinstance(asset, dict), 'invalid asset record')
        require({'id', 'kind'} <= set(asset), 'asset needs id and kind')
        ident(asset['id']); require(asset['id'] not in asset_ids, 'duplicate asset ID')
        require(asset['kind'] in asset_kinds, f'asset {asset["id"]}: unsupported asset kind {asset["kind"]!r}; use a source category or registered native asset kind')
        if 'uri' in asset: _optional_string(asset['uri'], 'invalid asset URI', 1000)
        if 'size' in asset: dimensions(asset['size'])
        if 'provenance' in asset:
            require(isinstance(asset['provenance'], dict), 'invalid asset provenance')
            require(set(asset['provenance']) <= {'source', 'generator', 'prompt_id', 'license', 'measured'}, 'invalid asset provenance fields')
        asset_ids.add(asset['id'])

    materials = p.get('materials', [])
    _bounded_list(materials, SCENE_MAX_ASSETS, 'too many materials')
    material_ids = set()
    for material in materials:
        require(isinstance(material, dict) and {'id', 'name'} <= set(material), 'material needs id and name')
        ident(material['id']); require(material['id'] not in material_ids, 'duplicate material ID')
        _optional_string(material['name'], 'invalid material name')
        if 'base_color' in material: numbers(material['base_color'], 3, 0, 1)
        if 'appearance' in material:validate_appearance(material['appearance'])
        for key in ('roughness', 'metallic', 'specular', 'ior'):
            if key in material:
                lo, hi = ((1, 3) if key == 'ior' else (0, 1))
                require(type(material[key]) in (int, float) and math.isfinite(material[key]) and lo <= material[key] <= hi, 'invalid material parameter')
        material_ids.add(material['id'])

    lights = p.get('lights', [])
    _bounded_list(lights, 256, 'too many lights')
    light_ids = set()
    for light in lights:
        require(isinstance(light, dict) and {'id', 'kind'} <= set(light), 'light needs id and kind')
        require(set(light) <= LIGHT_FIELDS, 'invalid light fields')
        ident(light['id']); require(light['id'] not in light_ids, 'duplicate light ID')
        _optional_string(light['kind'], 'invalid light kind', 40)
        require(light['kind'] in LIGHT_KINDS, 'unsupported light kind')
        require('position' in light or light['kind'] in {'environment','directional','sun'}, f'light {light["id"]}: local {light["kind"]} light needs position:[x,y,z]')
        if 'position' in light:numbers(light['position'], 3, -1000, 1000)
        if 'direction' in light:
            numbers(light['direction'], 3, -math.inf, math.inf)
            require(sum(value*value for value in light['direction']) >= 1e-12, 'light direction must be nonzero')
        if 'color' in light: numbers(light['color'], 3, 0, 1)
        if 'angle' in light:
            require(light['kind'] in {'sun','directional'} and type(light['angle']) in (int,float) and math.isfinite(light['angle']) and 0 <= light['angle'] <= 180,
                    f'light {light["id"]}: angle is the sun/directional angular diameter in degrees (0..180)')
        if 'size' in light:
            require(isinstance(light['size'],list) and len(light['size'])==2, f'light {light["id"]}: size must be [width,height], exactly two numbers (not a 3D geometry size)')
            numbers(light['size'], 2, .001, 1000)
        for key in ('intensity', 'temperature', 'inner_cone_deg', 'outer_cone_deg'):
            if key in light: require(type(light[key]) in (int, float) and math.isfinite(light[key]) and 0 <= light[key] <= 100000, 'invalid light parameter')
        if 'inner_cone_deg' in light: require(light['inner_cone_deg'] <= 180, 'invalid inner cone')
        if 'outer_cone_deg' in light: require(light['outer_cone_deg'] <= 180, 'invalid outer cone')
        if light['kind'] == 'spot': require(0 <= light.get('inner_cone_deg', 0) <= light.get('outer_cone_deg', 45) <= 180 and light.get('outer_cone_deg', 45) > 0, 'invalid spot cone angles')
        if 'cast_shadows' in light: require(type(light['cast_shadows']) is bool, 'invalid cast_shadows')
        if 'enabled' in light: require(type(light['enabled']) is bool, 'invalid light enabled')
        if 'environment_id' in light:
            require(light['kind']=='environment', 'environment_id only applies to environment lights')
            require(isinstance(light['environment_id'],str) and light['environment_id'] in ENVIRONMENTS,'environment_id must be a registered sky ID')
        light_ids.add(light['id'])

    render_environment = p.get('render_environment')
    if render_environment is not None:
        require(isinstance(render_environment, dict), 'invalid render environment')
        require(set(render_environment) <= RENDER_ENVIRONMENT_FIELDS, 'invalid render environment fields')
        if 'renderer' in render_environment:
            require(render_environment['renderer'] in RENDERERS, 'unsupported renderer')
        if 'samples_per_pixel' in render_environment:
            spp = render_environment['samples_per_pixel']
            require(type(spp) is int and 16 <= spp <= 512, 'samples_per_pixel must be 16..512')
        if 'exposure' in render_environment:
            exposure = render_environment['exposure']
            require(type(exposure) in (int, float) and math.isfinite(exposure) and -10 <= exposure <= 10, 'exposure must be -10..10')

    navigation = p.get('navigation')
    if navigation is not None:
        require(isinstance(navigation, dict), 'invalid navigation')
        require(set(navigation) <= {'agents', 'waypoints', 'edges', 'clearance_m', 'source'}, 'invalid navigation fields')
        for key in ('waypoints', 'edges', 'agents'):
            if key in navigation: _bounded_list(navigation[key], 4096, 'navigation graph too large')
        if 'clearance_m' in navigation:
            require(type(navigation['clearance_m']) in (int, float) and math.isfinite(navigation['clearance_m']) and 0 <= navigation['clearance_m'] <= 10, 'invalid navigation clearance')

    objects = {obj['id']: obj for obj in p['objects']}
    for field in ('affordances', 'interactions'):
        actions = p.get(field, [])
        _bounded_list(actions, 16 if field == 'interactions' else 4096, 'too many interaction affordances')
        action_ids = set()
        for action in actions:
            require(isinstance(action, dict) and {'id', 'action'} <= set(action), 'affordance needs id and action')
            ident(action['id']); _optional_string(action['action'], 'invalid affordance action', 80)
            require(action['id'] not in action_ids, 'duplicate interaction ID'); action_ids.add(action['id'])
            if 'object_id' in action: require(action['object_id'] in objects, 'affordance object must exist')
            if 'target_id' in action: require(action['target_id'] in objects, 'affordance target must exist')
            if field == 'interactions': require(action['action'] in {'apply_force','robot_push','record_trajectory'}, 'unsupported executable interaction; use affordances for declarations')
            if 'recording' in action:
                recording = action['recording']
                require(isinstance(recording, dict) and set(recording) <= {'every_steps', 'spatialtree', 'camera_path'}, 'recording accepts every_steps, spatialtree and camera_path')
                if 'every_steps' in recording:
                    require(type(recording['every_steps']) is int and recording['every_steps'] > 0, 'recording.every_steps must be a positive integer')
                if 'spatialtree' in recording:
                    _validate_spatialtree_recording(recording['spatialtree'])
                if 'camera_path' in recording:
                    _validate_camera_path(recording['camera_path'])
            if action['action'] == 'record_trajectory':
                require({'id','action','camera_id','duration_steps','recording'} == set(action),
                        'record_trajectory needs id, action, camera_id, duration_steps and recording')
                require(action['camera_id'] in [c.get('id') for c in p['cameras'] if c.get('id')], 'trajectory camera_id must name an existing camera')
                require(type(action['duration_steps']) is int and 1 <= action['duration_steps'] <= 10000,
                        'record_trajectory.duration_steps must be 1..10000')
                require('spatialtree' in action['recording'], 'record_trajectory requires recording.spatialtree')
                require(action['recording'].get('every_steps', 1) <= action['duration_steps'], 'recording interval exceeds trajectory duration')
                if 'camera_path' in action['recording']:
                    require(action['recording']['camera_path'][-1]['step'] <= action['duration_steps'], 'camera path exceeds trajectory duration')
            if action['action'] == 'robot_push' and (field == 'interactions' or 'interactions' not in p):
                from scene_production.server.isaac_sim.capture_requests.robot_contact import validate_robot_action
                validate_robot_action(action, objects)
                ident(action['robot_id'])
                for waypoint in action['waypoints']: ident(waypoint['id'])
                if 'camera_id' in action:
                    require(action['camera_id'] in [c.get('id') for c in p['cameras'] if c.get('id')], 'interaction camera_id must name an existing camera')
            if action['action'] == 'apply_force' and (field == 'interactions' or 'interactions' not in p):
                _validate_force_action(action, objects)
                if 'camera_id' in action:
                    require(action['camera_id'] in [c.get('id') for c in p['cameras'] if c.get('id')], 'interaction camera_id must name an existing camera')
    executable = [action for action in p.get('interactions', p.get('affordances', [])) if action['action'] == 'apply_force']
    require(len(executable) <= 16, 'too many executable interactions')
    require(sum(action.get('duration_steps', 30) + action.get('observe_steps', 90) for action in executable) <= 10000, 'interaction step budget exceeded')
    from scene_production.server.isaac_sim.capture_requests.robot_contact import robot_step_count
    robot_actions=[a for a in p.get('interactions',p.get('affordances',[])) if a['action']=='robot_push']
    camera_steps = sum(a['duration_steps'] for a in p.get('interactions',p.get('affordances',[])) if a['action']=='record_trajectory')
    require(camera_steps+sum(robot_step_count(a) for a in robot_actions)+sum(a.get('duration_steps',30)+a.get('observe_steps',90) for a in executable)<=10000,'interaction step budget exceeded')
    robots={}
    for action in robot_actions:
        placement=(action['robot_base_position'],action.get('robot_base_orientation_wxyz',[1.,0.,0.,0.]))
        require(action['robot_id'] not in robots or robots[action['robot_id']]==placement,'shared robot_id must keep its base pose')
        robots[action['robot_id']]=placement

    layers = p.get('semantic_layers', [])
    _bounded_list(layers, 128, 'too many semantic layers')
    layer_ids = set()
    for layer in layers:
        require(isinstance(layer, dict) and {'id', 'name'} <= set(layer), 'semantic layer needs id and name')
        ident(layer['id']); require(layer['id'] not in layer_ids, 'duplicate semantic layer ID')
        _optional_string(layer['name'], 'invalid semantic layer name')
        if 'labels' in layer:
            _bounded_list(layer['labels'], 4096, 'too many semantic labels')
            require(all(isinstance(label, str) and label for label in layer['labels']), 'invalid semantic label')
        if 'authority' in layer:
            require(layer['authority'] in {'simulator', 'official', 'imported', 'generated', 'unknown'}, 'invalid semantic authority')
        layer_ids.add(layer['id'])

    graph = p.get('scene_graph')
    if graph is not None:
        require(isinstance(graph, dict) and set(graph) <= {'nodes', 'edges'}, 'invalid scene graph')
        _bounded_list(graph.get('nodes', []), 2048, 'scene graph too large')
        _bounded_list(graph.get('edges', []), 4096, 'scene graph too large')
        for edge in graph.get('edges', []):
            require(isinstance(edge, dict) and {'source', 'target'} <= set(edge), 'graph edge needs source and target')

    provenance = p.get('provenance')
    if provenance is not None:
        require(isinstance(provenance, dict), 'invalid scene provenance')
        require(set(provenance) <= {'sources', 'generator', 'created_by', 'revision', 'notes'}, 'invalid scene provenance fields')
        if 'sources' in provenance:
            _bounded_list(provenance['sources'], 512, 'too many provenance sources')
            require(all(isinstance(source, (str, dict)) for source in provenance['sources']), 'invalid provenance source')

    # Enrich object records when present, while leaving the v1 builder fields
    # untouched.  Unknown free-form metadata stays out of the executor.
    for obj in p['objects']:
        if 'room_id' in obj: require(obj['room_id'] in room_ids, 'object room must reference a room')
        if 'zone_id' in obj: require(obj['zone_id'] in zone_ids, 'object zone must reference a zone')
        if 'material_id' in obj: require(obj['material_id'] in material_ids, 'object material must reference a material')
        material=next((item for item in materials if item['id']==obj.get('material_id')),{})
        effective_appearance={**material.get('appearance',{}),**obj.get('appearance',{})}
        if 'native_opacity_multiplier' in effective_appearance:
            require(ASSETS.get(obj['kind'],{}).get('supports_native_opacity_multiplier') is True,f'object {obj["id"]}: native_opacity_multiplier requires a registered capable native asset; it cannot replace generic object opacity')
        if 'texture_id' in effective_appearance:
            require(obj['kind'] in {'box','sphere','cylinder','container','composite'},f'object {obj["id"]}: registered texture_id supports primitives, containers and composites; imported meshes retain their source UV materials')
        if 'uv_scale_m' in effective_appearance:require('texture_id' in effective_appearance,f'object {obj["id"]}: uv_scale_m needs a registered texture_id')
        if 'texture_tint' in effective_appearance:require('texture_id' in effective_appearance,f'object {obj["id"]}: texture_tint needs a registered texture_id')
        for index,part in enumerate(obj.get('parts',[])):
            if 'material_id' in part:
                require(part['material_id'] in material_ids, f'object {obj["id"]}.parts[{index}]: material_id must reference a scene material')
                part_material=next(item for item in materials if item['id']==part['material_id'])
                part_appearance={**part_material.get('appearance',{}),**part.get('appearance',{})}
            else:part_appearance={**effective_appearance,**part.get('appearance',{})}
            require('native_opacity_multiplier' not in part_appearance, f'object {obj["id"]}.parts[{index}]: native_opacity_multiplier applies only to capable native assets')
            for key in ('uv_scale_m','texture_tint'):
                if key in part_appearance:require('texture_id' in part_appearance,f'object {obj["id"]}.parts[{index}]: {key} needs a registered texture_id')
        if 'asset_id' in obj and asset_ids: require(obj['asset_id'] in asset_ids or obj['kind'] == 'mesh', 'object asset must reference a registered asset')
        if 'asset_quality' in obj:
            require(isinstance(obj['asset_quality'], dict), 'invalid asset quality')
            require(set(obj['asset_quality']) <= {'semantic_review', 'identity_match', 'state_match', 'completeness', 'issues', 'repair_prompt', '3d_validated', 'reason'}, 'invalid asset quality fields')
        if 'semantic_labels' in obj:
            _bounded_list(obj['semantic_labels'], 32, 'too many object semantic labels')
            require(all(isinstance(label, str) and label for label in obj['semantic_labels']), 'invalid object semantic label')
        if 'affordances' in obj:
            _bounded_list(obj['affordances'], 64, 'too many object affordances')
            require(all(isinstance(item, str) for item in obj['affordances']), f'object {obj["id"]}: affordances must be a list of strings, not action records; structured action records belong to the top-level affordances or interactions')
        if 'tags' in obj:
            _bounded_list(obj['tags'], 64, 'too many object tags')
            require(all(isinstance(tag, str) and tag for tag in obj['tags']), 'invalid object tag')
    return p
def part_contract_errors(p):
    """Locate all kind/parts mismatches without changing the proposed scene."""
    errors=[]
    if not isinstance(p,dict) or not isinstance(p.get('objects'),list):return errors
    for index,obj in enumerate(p['objects']):
        if not isinstance(obj,dict) or not isinstance(obj.get('parts'),list):continue
        prefix=f'object {obj.get("id","?")} /objects/{index}'
        parts=obj['parts'];kind=obj.get('kind')
        if kind=='composite' and not parts:
            errors.append(f'{prefix}: composite needs parts; supply nonempty parts or replace the entire record with a supported asset kind and parts=[]')
        elif kind!='composite' and parts:
            errors.append(f'{prefix}: only composites accept parts; kind={kind!r} requires parts=[]; use composite for explicit parts or clear parts for the selected asset kind')
        for pi,part in enumerate(parts):
            if isinstance(part,dict) and part.get('shape') not in {'box','sphere','cylinder'}:
                errors.append(f'{prefix}/parts/{pi}/shape: invalid part shape {part.get("shape")!r}; allowed: box, sphere, cylinder')
    return errors
def appearance_contract_errors(p):
    errors=[]
    for section in ('objects','materials'):
        items=p.get(section,[])
        if not isinstance(items,list):continue
        for index,item in enumerate(items):
            if not isinstance(item,dict) or 'appearance' not in item:continue
            context=f'{section[:-1]} {item.get("id","?")} /{section}/{index}/appearance'
            try:validate_appearance(item['appearance'],context)
            except ValueError as exc:errors.append(f'{context}: {exc}')
    return errors
def validate_program(p):
    require(isinstance(p, dict), 'scene must be an object')
    require(p.get('schema') in SCENE_SCHEMAS, 'unsupported scene schema')
    required_top = {'schema', 'scene_id', 'title', 'objects', 'cameras', 'assumptions'}
    require(required_top <= set(p), 'invalid scene fields')
    allowed_top = required_top | {'rooms', 'zones', 'portals', 'assets', 'materials', 'lights', 'navigation', 'affordances', 'interactions', 'semantic_layers', 'scene_graph', 'provenance', 'render_environment'}
    require(set(p) <= allowed_top, 'invalid scene fields')
    ident(p['scene_id'])
    require(isinstance(p['title'], str) and len(p['title']) < 200, 'invalid title')
    require(isinstance(p['objects'], list) and 1 <= len(p['objects']) <= SCENE_V2_MAX_OBJECTS, 'entity count exceeds execution budget')
    geometry_errors=part_contract_errors(p)+appearance_contract_errors(p)
    require(not geometry_errors,'; '.join(geometry_errors))
    ids = set()
    for o in p['objects']:
        require(isinstance(o, dict), 'invalid object')
        required={'id','label','kind','size','xy','support','base_z','dynamic','mass_kg'}
        optional={'color','yaw_deg','parts','generation','asset_id','asset_quality','mesh_transform','render_representation','cast_shadows','physics','appearance','room_id','zone_id','material_id','semantic_labels','affordances','tags','metadata','source_ref'}
        require(required <= set(o) <= required|optional, f'object {o.get("id","?")}: invalid object fields; missing={sorted(required-set(o))}, unsupported={sorted(set(o)-required-optional)}. Allowed optional fields={sorted(optional)}; provenance belongs to top-level, while object notes belong in metadata/source_ref')
        ident(o['id']); require(o['id'] not in ids, 'duplicate ID')
        require(isinstance(o['label'], str) and 0 < len(o['label']) < 100, 'invalid semantic label')
        require(o['kind'] in {'box','sphere','cylinder','container','composite','generated','mesh'} | set(ASSETS), 'unsupported builder')
        if o['kind']=='generated':
            require(isinstance(o.get('generation'),dict) and isinstance(o['generation'].get('prompt'),str), 'generated asset needs a visual generation prompt')
        if o['kind']=='mesh':ident(o.get('asset_id'))
        if 'render_representation' in o:require(o['render_representation'] in {'auto','gaussian','mesh'}, 'render_representation must be auto, gaussian or mesh')
        if 'cast_shadows' in o:require(type(o['cast_shadows']) is bool, 'object cast_shadows must be boolean')
        if 'mesh_transform' in o:
            require(o['kind'] in {'mesh','generated'}, 'mesh_transform only applies to imported or generated meshes')
            transform=o['mesh_transform']
            require(isinstance(transform,dict) and set(transform)<={'orientation_deg_xyz','scale_mode'}, 'invalid mesh_transform fields')
            if 'orientation_deg_xyz' in transform:numbers(transform['orientation_deg_xyz'],3,-360,360)
            require(transform.get('scale_mode','uniform_fit')=='uniform_fit', f'object {o["id"]}: mesh_transform.scale_mode must be "uniform_fit", got {transform.get("scale_mode")!r}; preserve proportions and change orientation_deg_xyz for pose, not scale_mode')
        physics=o.get('physics',{})
        require(isinstance(physics, dict), 'invalid physics properties')
        require(set(physics)<={'static_friction','dynamic_friction','restitution','mass_source','collider'},'invalid physics properties')
        for key in ('static_friction','dynamic_friction'):
            if key in physics:numbers([physics[key]],1,0,3)
        if 'restitution' in physics:numbers([physics['restitution']],1,0,1)
        if 'collider' in physics:require(physics['collider'] in {'convexHull','convexDecomposition'},'unsupported collider')
        appearance=o.get('appearance',{})
        validate_appearance(appearance)
        if 'native_opacity_multiplier' in appearance:
            require(ASSETS.get(o['kind'],{}).get('supports_native_opacity_multiplier') is True,f'object {o["id"]}: native_opacity_multiplier requires a registered capable native asset')
        context=f'object {o["id"]}'
        dimensions(o['size'],context+'.size')
        if 'color' in o:numbers(o['color'],3,0,1,context+'.color')
        numbers(o['xy'],2,-1000,1000,context+'.xy')
        numbers([o['base_z']],1,-1000,1000,context+'.base_z')
        numbers([o.get('yaw_deg',0)],1,-1000,1000,context+'.yaw_deg')
        require(type(o['dynamic']) is bool, f'object {o["id"]}: dynamic must be boolean')
        require(type(o['mass_kg']) in (float, int) and math.isfinite(o['mass_kg']) and (.001 if o['dynamic'] else 0) <= o['mass_kg'] <= 1000000, f'object {o["id"]}: invalid mass_kg; dynamic bodies require mass >= 0.001, static bodies allow unused mass=0')
        require(isinstance(o['support'],str), f'object {o["id"]}: support must be ground or an object ID')
        parts=o.get('parts',[])
        require(isinstance(parts,list), 'invalid parts')
        if o['kind'] == 'composite': require(bool(parts), 'composite needs parts')
        else: require(not parts, 'only composites accept parts')
        for part_index,part in enumerate(parts):
            require(isinstance(part, dict), 'invalid part fields')
            require({'shape','size','offset','color'}<=set(part)<={'shape','size','offset','color','rotation_deg_xyz','material_id','appearance'}, 'invalid part fields')
            require(part['shape'] in {'box','sphere','cylinder'}, 'invalid part shape')
            validate_appearance(part.get('appearance',{}))
            if 'material_id' in part:ident(part['material_id'])
            part_context=f'{context}.parts[{part_index}]'
            dimensions(part['size'],part_context+'.size')
            numbers(part['offset'],3,-1000,1000,part_context+'.offset')
            numbers(part['color'],3,0,1,part_context+'.color')
            numbers(part.get('rotation_deg_xyz',[0,0,0]),3,-360,360,part_context+'.rotation_deg_xyz')
        ids.add(o['id'])
    objects_in_support_order(p['objects'])
    require(isinstance(p['cameras'],list) and 1 <= len(p['cameras']) <= 64, 'camera count exceeds execution budget')
    camera_ids=set()
    for index,c in enumerate(p['cameras']):
        require(isinstance(c, dict) and {'position','target'} <= set(c) <= {'position','target','id','up','focal_length_mm','horizontal_aperture_mm','role','allow_external'}, f'camera {index}: fields are position,target and optional id,up,focal_length_mm,horizontal_aperture_mm,role,allow_external')
        if 'id' in c:
            ident(c['id'])
            require(c['id'] not in camera_ids, f'camera {index}: duplicate id');camera_ids.add(c['id'])
        numbers(c['position'],3,-1000,1000,f'camera {c.get("id",index)}.position')
        numbers(c['target'],3,-1000,1000,f'camera {c.get("id",index)}.target')
        require(sum((a-b)**2 for a,b in zip(c['position'],c['target']))>1e-8, f'degenerate camera {index}: position and target must be more than 0.0001 m apart; vertical views are allowed')
        for field in ('focal_length_mm','horizontal_aperture_mm'):
            if field in c:
                value=c[field]
                require(type(value) in (int,float) and math.isfinite(value) and value>0, f'camera {index}.{field}: expected a positive finite number')
        if 'up' in c:
            numbers(c['up'],3,-math.inf,math.inf,f'camera {index}.up')
            direction=[c['target'][i]-c['position'][i] for i in range(3)];up=c['up']
            cross=[direction[1]*up[2]-direction[2]*up[1],direction[2]*up[0]-direction[0]*up[2],direction[0]*up[1]-direction[1]*up[0]]
            require(any(v != 0 for v in cross), f'camera {index}.up: cannot be zero or parallel to the view direction')
        if 'role' in c:
            require(isinstance(c['role'], str) and c['role'], f'camera {index}.role: expected a nonempty string')
        if 'allow_external' in c:
            require(type(c['allow_external']) is bool, f'camera {index}.allow_external: expected a boolean')
    require(isinstance(p['assumptions'],list) and len(p['assumptions']) <= 30, 'invalid assumptions')
    require(all(isinstance(item, str) for item in p['assumptions']), 'assumptions must be strings')
    _validate_scene_extensions(p)
    return p
SCENE_SCHEMA_DESCRIPTION += '\nInstalled native asset kinds (use the exact key as object kind; size is the native measured bounding box in meters): ' + json.dumps({key:{field:value for field,value in asset.items() if field!='path'} for key,asset in ASSETS.items()})
SCENE_SCHEMA_DESCRIPTION += '\nRegistered texture IDs: ' + ', '.join(NATIVE_MATERIALS)
SCENE_SCHEMA_DESCRIPTION += '\nRegistered texture materials accept optional appearance.texture_tint:[r,g,b] in 0..1. It multiplies base-color texture in linear RGB after sRGB decoding; [1,1,1] retains the original texture. It does not modify normal maps, geometry, source files or imported/native asset materials. Object color and named material base_color remain fallback colors when no texture is used. Use texture_tint to stain wood or tint fabric while retaining its pattern. Named appearance merges before object overrides; omission preserves existing textured appearance. Material receipts include the tint.'
SCENE_SCHEMA_DESCRIPTION += '\nThere is no generic opacity/transmission parameter. Registered native assets with supports_native_opacity_multiplier=true accept appearance.native_opacity_multiplier in 0..1, applied only to existing unconnected MDL Opacity_Multiply inputs. It multiplies native alpha, not measured optical transmittance; preserve textures, geometry and colliders. Other materials in the same object remain unchanged unless separately supported. Check actual appearance_overrides and rendered views. All entries in cameras are final scene snapshots after interactions. Camera IDs such as before/after do not change capture time. Separate interaction_*_before/after.png files record the real action. Distinct-view requests require different useful camera poses; duplicate poses do not add coverage.'
SCENE_SCHEMA_DESCRIPTION += '\nAn executable action may set camera_id to an existing camera for its before/after images. Otherwise the executor selects the authored camera aimed closest to the target object. The pose stays fixed across that action; visual_evidence records the camera and target pixel bounds in both images. Use those images and visibility to assess the action.'
SCENE_SCHEMA_DESCRIPTION += '\nFor an interaction demonstration, an apply_force or robot_push action can add recording:{every_steps:4}. The executor renders actual simulation states at that step interval and exports an MP4, original PNG frames and a timeline with simulation timestamps and target positions. Empty recording:{} selects approximately 30 fps from physics dt; omitting recording keeps endpoint-only captures. This adds rendering work but no physics steps, interpolated motion or extra simulator. FPS is 1/(every_steps*physics_dt); the final after image remains available when the action ends between video samples. Use the returned recording receipt for filenames and timing.'
SCENE_SCHEMA_DESCRIPTION += '\nNative video GT: add recording.spatialtree:{scenario_id?,split?}, split=train/dev/test/sealed. Resolution comes from capture options and FPS from every_steps and the actual physics dt. An optional recording.camera_path:[{step:0,position:[x,y,z],target:[x,y,z]},...] linearly moves the camera at recorded simulation steps; steps are relative to the first sample and poses after the last keyframe hold. For standalone camera motion or fixed-camera video, use an interaction {id,action:"record_trajectory",camera_id,duration_steps,recording:{every_steps:4,spatialtree:{},camera_path:[...]}}; camera_path is optional. This advances physics without applying object forces or pose commands. Combined camera/object motion uses camera_path on apply_force or robot_push recording. Exported interaction_N_spatialtree.zip contains RGB, optical-axis metric depth, semantic/instance arrays and mappings, camera intrinsics/poses, rigid object poses, visibility/boxes, native motion and identity correspondence. Read the summary through benchforge_scene_evidence and copy the ZIP to the task workspace; no tracking model supplies GT. This is a BenchForge native synthetic contract, not the official SpatialTree dataset format.'
SCENE_SCHEMA_DESCRIPTION += '\nAn apply_force or robot_push action may set contact_object_ids:[other_scene_object_ids] to observe target-object collisions, including static objects. object_contacts records each physics step at the actual physics rate (120 Hz for robot_push): force on the target from each named object, target and other object world positions, and any robot hand/finger forces in separate columns (empty for external-force actions). The summary reports first/last nonzero contact, peak force and displacement without deciding task success. These objects need not stay still; witness_object_ids retains its separate stationary-witness meaning. Ordinary robot trajectory is sampled every 3 physics steps (40 Hz), plus its final sample; recording FPS is independent.'
SCENE_SCHEMA_DESCRIPTION += '\nExecutable robot_push actions: {id,action:"robot_push",object_id,robot_id,robot_base_position:[x,y,z],waypoints:[{id,position:[x,y,z],duration_s}],optional robot_base_orientation_wxyz,end_effector_orientation_wxyz,witness_object_ids,contact_object_ids,observe_seconds,camera_id,recording}. Uses installed official Franka Panda, closed fingers and Lula IK joint targets. Waypoints describe the right_gripper IK frame in world meters; this differs from the reported right-finger body origin. Default base orientation [1,0,0,0], end-effector orientation [0,1,0,0], observation 1.5 seconds. A shared robot_id keeps the same base pose. Target and any witness objects must be dynamic. Robot captures run physics at 120 Hz and preserve ordinary apply_force step counts. Mass, friction and mesh collision approximation stay scene-authored. Success requires >=.04m target translation, >=3 sampled hand contacts above .05N, <=.005m movement before contact threshold, <=.01m witness movement and final target root-Z tilt <=20 degrees, <=.02m vertical displacement throughout the trajectory, and target visibility in both endpoint images; checks and raw trajectories remain visible on failure. No target force or pose commands, grasp, measured dynamics or general motion-planning claim. Place the robot on a support, author reachable collision-aware waypoints, inspect actual before/after evidence, and revise task content when needed. Total action steps stay within the existing 10000-step budget.'
SCENE_SCHEMA_DESCRIPTION += '\nEnvironment lights may additionally select environment_id from this registry: '+json.dumps({key:{k:v for k,v in record.items() if k!='path'} for key,record in ENVIRONMENTS.items()})+'. The HDR texture affects illumination and visible sky, not scene geometry. An optional direction sets the world direction of the HDR lower pole, tilting the whole environment after stage-up-axis alignment; it does not specify the sun position. Omit direction to retain the level horizon. HDR brightness must be verified in the actual renderer and exposure. Preserve texture provenance and compare actual rendered sky before selecting intensity. An HDR image does not supply outdoor geometry or metric GT. You may explicitly create outdoor objects using supported SceneProgram kinds and registered assets, respecting bounds and recording synthetic/program provenance. Never claim uncreated or merely pictured background geometry was simulated.'
SCENE_SCHEMA_DESCRIPTION += '\nDielectric controls: optional ior (1..3, default 1.5) sets the refractive-index basis of surface reflection; specular (0..1, default .5) scales normal-incidence Fresnel F0 by 2*specular. Specular .5 retains the IOR Fresnel reflectance, 0 removes the normal-incidence dielectric reflection, and 1 doubles it. The executor authors an effective UsdPreviewSurface IOR while retaining the metallic workflow, metal color, roughness and textures. This controls surface reflection only, not glass transmission or opacity. Named materials merge before object-local appearance. Native OmniPBR supports roughness, metallic and specular through its MDL constants even when the source uses unauthored defaults, preserving textures and their blend influences. OmniPBR IOR, unsupported controls on other MDL shaders, connected inputs and specular-color workflows retain their source behavior and are reported as skipped. Omitted controls preserve existing shader defaults.'
SCENE_SCHEMA_DESCRIPTION += '\nImported meshes preserve source color, metallic and roughness even without images or UVs. appearance.roughness and appearance.metallic override the source scalar factor (and multiply any source metallic-roughness texture) on each face material. Named scene materials merge before object overrides. With source UVs, base color/emissive use sRGB textures; normal, metallic-roughness (G/B), and occlusion (R) use raw textures. Source tint and emissive factors are retained. Opacity and glTF material extensions are not implemented. Inspect capture appearance_overrides and bound_texture_slots for actual bindings; this is not calibrated reflectance.'
