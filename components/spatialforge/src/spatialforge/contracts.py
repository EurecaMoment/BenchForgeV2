"""Model proposals are data; only these bounded operations reach Isaac."""
import math
import json
import re
from copy import deepcopy
from typing import Any
from .asset_catalog import load_native_assets
from .material_catalog import load_native_materials
from .environment_catalog import ENVIRONMENTS
from .support_graph import objects_in_support_order

ASSETS = {
    'mug': {'path': 'Mugs/SM_Mug_A2.usd', 'size': [.0924, .1272, .091], 'description': 'ceramic mug with handle'},
    'bin': {'path': 'KLT_Bin/small_KLT_visual_collision.usd', 'size': [.198, .297, .1464], 'description': 'open industrial container'},
}
ASSETS.update(load_native_assets())
NATIVE_MATERIALS=load_native_materials()


def normalize_native_asset_references(program):
    """Canonicalize the two spellings of a registered native asset, preserving input."""
    result=deepcopy(program)
    for obj in result.get('objects',[]):
        if obj.get('kind')=='mesh' and obj.get('asset_id') in ASSETS:
            transform=obj.get('mesh_transform')
            if transform:
                if any(transform.get('orientation_deg_xyz',[0,0,0])) or transform.get('scale_mode','uniform_fit')!='uniform_fit':
                    raise ValueError(f'object {obj["id"]}: native asset aliases only support zero Euler orientation with uniform_fit; use yaw_deg and native asset kind')
                native_size=ASSETS[obj['asset_id']]['size'];requested=list(obj['size'])
                scale=min(requested[i]/native_size[i] for i in range(3))
                obj['size']=[v*scale for v in native_size]
                obj['metadata']={**obj.get('metadata',{}),'native_alias_fit':{'requested_size':requested,'uniform_scale':scale}}
                obj.pop('mesh_transform')
            obj['kind']=obj.pop('asset_id')
    return result

# Both schema versions use the same desktop executor and execution budget.
SCENE_V1_MAX_OBJECTS = SCENE_V2_MAX_OBJECTS = 512
SCENE_MAX_ROOMS = 64
SCENE_MAX_ZONES = 256
SCENE_MAX_PORTALS = 256
SCENE_MAX_ASSETS = 1024
LIGHT_KINDS = {'point', 'spot', 'area', 'directional', 'sun', 'environment'}
LIGHT_FIELDS = {'id', 'kind', 'position', 'direction', 'color', 'intensity', 'temperature', 'size', 'angle', 'inner_cone_deg', 'outer_cone_deg', 'cast_shadows', 'enabled', 'environment_id'}
RENDER_ENVIRONMENT_FIELDS = {'renderer', 'samples_per_pixel', 'exposure'}
RENDERERS = {'RaytracedLighting', 'PathTracing'}


def require(ok, message):
    if not ok: raise ValueError(message)


def ident(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value),
            f'invalid ID {value!r}: use letters, digits and underscores, starting with a letter or underscore')
    return value


def numbers(value, length, lo, hi, context='vector'):
    require(isinstance(value, list) and len(value) == length, f'{context}: expected {length} numbers; got {value!r}')
    require(all(type(v) in (float, int) and math.isfinite(v) and lo <= v <= hi for v in value),
            f'{context}: expected finite numbers in [{lo}, {hi}]; got {value!r}')


def dimensions(value, context='size'):
    numbers(value, 3, 0, 1000, context)
    require(all(v > 0 for v in value), f'{context}: dimensions must be positive; got {value!r}')


APPEARANCE_FIELDS={'roughness','metallic','specular','ior','texture_id','texture_tint','uv_scale_m','native_opacity_multiplier'}


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
            require(value in {'spatialforge.scene/v1', 'spatialforge.scene/v2'}, 'unsupported scene schema')
            merged[key] = 'spatialforge.scene/v2' if base[key].endswith('/v2') else value
        else:
            merged[key] = _merge_extension_value(base[key], value, key) if key in base else deepcopy(value)
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
            if field == 'interactions': require(action['action'] in {'apply_force','robot_push'}, 'unsupported executable interaction; use affordances for declarations')
            if 'recording' in action:
                recording = action['recording']
                require(isinstance(recording, dict) and set(recording) <= {'every_steps'}, 'recording accepts optional every_steps')
                if 'every_steps' in recording:
                    require(type(recording['every_steps']) is int and recording['every_steps'] > 0, 'recording.every_steps must be a positive integer')
            if action['action'] == 'robot_push' and (field == 'interactions' or 'interactions' not in p):
                from .robot_contact import validate_robot_action
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
    from .robot_contact import robot_step_count
    robot_actions=[a for a in p.get('interactions',p.get('affordances',[])) if a['action']=='robot_push']
    require(sum(robot_step_count(a) for a in robot_actions)+sum(a.get('duration_steps',30)+a.get('observe_steps',90) for a in executable)<=10000,'interaction step budget exceeded')
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
    require(p.get('schema') in {'spatialforge.scene/v1', 'spatialforge.scene/v2'}, 'unsupported scene schema')
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


SCENE_SCHEMA_DESCRIPTION = '''Return only JSON with schema="spatialforge.scene/v1" or "spatialforge.scene/v2". Both versions use the same desktop Isaac executor and accept the fields below with the same geometry ranges and execution budget (512 objects, 64 cameras). Changing schema is unnecessary for room-scale objects, negative floor height or distant cameras. Both schemas include scene_id (USD identifier), title,
objects and cameras matching the user's requested number and scene complexity, assumptions (strings).
Keep scene metadata concise and necessary for execution or provenance. Requested QA counts are fulfilled by downstream dataset generation from simulator evidence; never invent QA items or pad semantic_layers to satisfy a question count. Semantic layers describe genuine label namespaces only.
Every object requires these base fields, plus supported optional fields below: id,label,kind,size:[x,y,z] meters,xy:[x,y] WORLD position,
support:"ground" or another object ID,base_z:height offset above supporting surface (normally 0),yaw_deg (optional, defaults to 0 degrees),
dynamic:boolean,mass_kg:number. Only composite objects require a nonempty parts list; other kinds may omit parts or use parts:[]. Dynamic bodies require mass_kg>=.001; static bodies may use mass_kg=0 because mass is unused. Object and referenced metadata IDs use ASCII letters, digits and underscores, starting with a letter or underscore. Case is preserved; use the same spelling in references.
support="ground" places the object relative to world Z=0; it does not create a floor or collider. Author the floor/terrain explicitly when the scene needs one. Only declared objects supply visible and collision geometry, so surfaces below zero and open exterior spaces remain as authored.
Kinds: box,sphere,cylinder (axis Z),container (five separate walls, open top),composite,mug,bin,
generated (free-form realistic asset using FLUX.2 diffusion + SAM3 segmentation + SAM3D), mesh (reuse registered asset_id).
Object color:[r,g,b] in 0..1 is optional. Named material base_color, source asset appearance and the existing neutral fallback [.7,.7,.7] remain available without a redundant object color. Composite part color remains required.
For generated kind add generation:{prompt: detailed English product description}; the same asset-tool options may be supplied here: label (short segmentation subject), source_image, source_mask, subject_box (pixel xyxy), seed, edit_reference, texture_baking (optional SAM3D UV color textures; omitted/false keeps vertex colors), source_mesh, source_gaussian, source_up_axis, asset_id. They are passed to the asset tool unchanged. Keep the object label for its scene identity; generation.label can describe just the subject to segment. Existing images and masks may come from the independent tools. For mesh add asset_id from asset catalog. SAM3D assets retain paired Gaussian appearance and mesh physics. Default render_representation=auto displays Gaussian when available, otherwise the existing mesh; explicit mesh selects mesh appearance, and explicit gaussian selects the paired Gaussian. Both representations share the mesh normalization, object pose and semantic identity. For paired reconstructed components, keep Gaussian appearance with same-source mesh physics (auto or gaussian). Inspect PathTracing captures and local lighting before changing representation. Gaussian radiance retains source lighting; explicit mesh/PBR is available when the task specifically calls for mesh appearance or for a diagnostic comparison. Gaussian objects cast native RTX shadows by default. Optional object cast_shadows:false disables casting; true enables it. Explicit settings also control mesh/primitive shadows without changing physics. Inspect captures for interaction with source-baked appearance; shadow casting does not convert Gaussian radiance into relightable PBR. Gaussian fields also receive shadows from surrounding meshes: indoor darkness can persist with object cast_shadows:false. Inspect room openings, local light placement and captured views; hidden-mesh roughness/metallic do not change visible Gaussian radiance.
Imported/generated meshes use uniform_fit scaling by default: size:[x,y,z] sets bounding limits after orientation, and a single scale factor fits all axes without changing source proportions. The resulting dimensions can be smaller than the requested limits. Do not force every source axis to the requested length. Optional mesh_transform:{orientation_deg_xyz:[x,y,z],scale_mode:"uniform_fit"}; each Euler angle is -360..360 degrees, default [0,0,0], scale_mode only supports uniform_fit. The executor applies the source's documented coordinate-system conversion first (including SAM3D camera basis), then explicit rotations around X, Y, Z in that order, then uniform fitting; yaw_deg is the scene placement rotation. Use orientation only when supported by asset coordinates or inspected geometry. The executor never guesses semantic pose through PCA or image interpretation. Actual oriented mesh bounds determine support height and placement.
Choose native, reused, generated or composite geometry to fit the object.
Optional physics:{static_friction,dynamic_friction,restitution,collider:"convexDecomposition",mass_source:"synthetic_prior"}.
Optional appearance:{roughness:0..1,metallic:0..1,specular:0..1,ior:1..3,texture_id:operator_registered_ID,uv_scale_m:[u_m,v_m],native_opacity_multiplier:0..1}. native_opacity_multiplier is only available for native kinds explicitly advertising supports_native_opacity_multiplier; it scales their native alpha and is not calibrated optical transmittance or generic opacity. uv_scale_m is a two-vector in .01..100 meters specifying the physical length of one texture repeat on each surface axis, not a pixel or repeat count; it requires an effective texture_id. Registered textures work on boxes, cylinders, spheres, open containers and mixed box/cylinder/sphere composites. Boxes and container walls use planar metric UVs; cylinders use circumference/height with planar caps. Spheres use equatorial and XZ-meridian arc lengths with equirectangular pole distortion. Curves have smooth shading, 96 circumferential segments and 48 sphere latitude intervals; collision is the convex hull of each part, preserving the open container. Imported meshes retain source UV materials. Named materials may contain the same appearance fields; object-local appearance overrides the named material. Never give arbitrary texture paths or URLs. These are appearance priors, not measured PBR parameters. Choose physically plausible material priors and actual dimensions.
For composite parts: shape (box/sphere/cylinder),size:[x,y,z],offset:[x,y,z],color:[r,g,b],optional material_id and appearance. Parts inherit object appearance by default; part appearance overrides individual fields. Explicit part material_id selects a scene material instead of the inherited object material, then part appearance overrides it. This allows wood, bare metal and fabric within one composite; named part base_color takes precedence over its fallback color. Each textured part has its own uv_scale_m and texture_tint. Optional rotation_deg_xyz:[x,y,z] in degrees (-360..360, default [0,0,0]). Object and part dimensions are finite positive meters up to 1000; there is no minimum thickness or automatic thickening. Submillimeter strings, wires and sheets keep their submitted dimensions. Size is local before rotation; cylinders extend along local Z. Rotate around the part center in X, then Y, then Z order, then offset in composite coordinates; object yaw applies last. For example, a cylinder rotated [0,90,0] lies along composite X. Materials, UVs and colliders follow the part rotation.
Offsets are measured from the composite bounding box center. Rotated part bounds must fit the declared outer size (within 0.002m tolerance); preview reports the resulting geometry bounds and actual horizontal box support faces.
All geometry is bottom aligned; child support base height = support object's top + base_z.
Objects may appear in any list order. The preview and executor resolve the support graph before positioning children; submitted order and object records are preserved. Support IDs must exist and support chains cannot be cyclic.
Box/container dimensions exact; mug and bin are real local USD assets rescaled to size and bottom aligned.
Mug native size=[.0924,.1272,.091], bin native size=[.198,.297,.1464].
Composite parts can form custom objects and may protrude outside the declared size. Composite size is the placement envelope: the parent center and support top still use it. Actual part bounds and horizontal support surfaces are reported by geometry_preview; no clipping, resizing or recentering is applied.
For shelving, choose explicit boards or composite geometry and place supported objects at the relevant surface height.
Tables can be static solid worktops. Add dynamic props only when the requested task benefits from interaction; architectural visualization and navigation-only scenes may be entirely static.
Choose clearances appropriate to the intended contact, objects and activity.
Cameras each {position:[x,y,z],target:[x,y,z],id?:identifier,up?:[x,y,z],focal_length_mm?:number,horizontal_aperture_mm?:number,role?:string,allow_external?:boolean}, Z-up, negative Y is front. Camera IDs are optional metadata, unique within cameras, and use the same case-preserving identifier syntax. Omitted optics retain focal_length_mm=24 and horizontal_aperture_mm=36; both accept positive finite numbers. Horizontal field of view is 2*atan(horizontal_aperture_mm/(2*focal_length_mm)); choose optics when matching a reference camera instead of distorting objects. Optional up controls camera roll and must not be zero or parallel to target-position; omission keeps the existing Z-up/vertical-view choice. Choose camera views for the requested evidence. Position and target must differ by more than 0.0001m. Close-ups and exactly vertical top-down views are supported. Aim at the actual object center, computed from support top height plus base_z and half the object height; do not confuse composite local part offsets with world heights. A camera targeting a declared room is checked against its declared floor/ceiling before desktop capture; use role:"external" or allow_external:true for an intentionally exterior viewpoint.
For v2, rooms and zones are spatial/semantic regions only. They do not create floors or walls: represent physical boundaries as explicit objects or imported geometry, and use room representation="explicit_objects" with geometry.object_ids when declaring them.
Allowed optional top-level fields: rooms,zones,portals,assets,materials,lights,navigation,affordances,interactions,semantic_layers,scene_graph,provenance,render_environment. No other top-level fields.
Room: {id,name,bounds:{center:[x,y,z],size:[x,y,z]},floor_z?,representation:"bounds_only"|"explicit_objects"|"imported_geometry",geometry?:{object_ids:[existing object IDs],notes?},semantic_role?}. A room's bounds center is WORLD position and size is full dimensions. Zone: {id,name,bounds,room_id?,purpose?}. Objects may reference existing room_id,zone_id,material_id and add semantic_labels,affordances,tags,metadata,source_ref. Object affordances must be string lists such as ["support_prop"], not action records; structured actions belong to the top-level lists.
Portal: {id,kind,position:[x,y,z],size:[x,y,z],from_room?,to_room?,passable?}; portal and navigation records are declarations, not executable geometry or proven traversability. Navigation fields are agents,waypoints,edges,clearance_m,source.
Materials: [{id,name,base_color:[r,g,b],roughness:0..1,metallic:0..1,specular:0..1,ior:1..3}]. Refer to them with material_id. Registered assets are selected by object kind or mesh asset_id, never by adding an external path.
Executable interactions are optional (at most 16 total). External-force actions use: {id,action:"apply_force",object_id,force_newtons:[x,y,z],duration_steps:1..600,observe_steps:1..600,min_displacement_m,max_displacement_m,max_vertical_displacement_m,max_final_speed_m_s,max_initial_speed_m_s,max_drift_m}. Only id,action,object_id,force_newtons are required. Defaults: duration_steps=30,observe_steps=90,min_displacement_m=.02,max_displacement_m=1,max_vertical_displacement_m=.1,max_final_speed_m_s=.1,max_initial_speed_m_s=.03,max_drift_m=.005. The target must be dynamic, force magnitude nonzero and <=1000N, 0<min_displacement_m<=max_displacement_m, and total duration+observation steps<=10000. The simulator applies real force after stable settling and measures motion along the force, fall and final speed; do not label this a robot grasp or calibrated real-world dynamics. Size force and duration so the prop moves within its support surface and stops safely. Other action ideas belong only in affordances:[{id,action,object_id?,target_id?}] as declarations.
Optional assets records: {id,kind,uri?,size?,provenance?:{source?,generator?,prompt_id?,license?,measured?}}. Asset metadata does not import external geometry. Scene graph: {nodes:[],edges:[{source,target,relation?}]}. Semantic layers: [{id,name,labels?,authority:"simulator"|"official"|"imported"|"generated"|"unknown"}]. Provenance fields: sources,generator,created_by,revision,notes. Do not claim generated labels are official or measured.
Optional render_environment is exactly {renderer:"RaytracedLighting"|"PathTracing",samples_per_pixel:16..512,exposure:-10..10}. Each field is optional. When visible paired Gaussians are present and no renderer is selected, capture defaults to PathTracing at 128 samples; explicit renderer/sample choices remain available. Prefer PathTracing for enclosed Gaussian scenes and inspect actual captures.
Light kind is point,spot,area,directional,sun,environment. Supported light fields are id,kind,position,direction,color,intensity,temperature,size:[x,y],angle,inner_cone_deg,outer_cone_deg,cast_shadows,enabled. id and kind are required. direction is a nonzero finite vector; the renderer normalizes it, so target minus light position is accepted without component clamping. point/spot/area require position:[x,y,z]; infinite environment/directional/sun lights may omit position because translation does not change their illumination. For sun/directional, angle is the angular diameter in degrees (0..180, default .53); larger angles soften shadows without changing the requested intensity. It changes that light, not the HDR environment or indirect illumination. Area light softness instead depends on size and distance.
For point/spot, omitted size means a zero-radius point emitter (USD treatAsPoint=true); explicit size[0] is the spherical emitter diameter in meters (size[1] is unused for sphere). For area lights, size is width and height in meters. Inspect capture light_receipts for authored emitter dimensions; changing emitter size changes appearance and illumination, not calibrated lux.
Light intensity is written directly to UsdLux inputs:intensity, not a normalized 0..1 slider. For this executor, useful interior starting ranges are environment 100..600, sun/directional 1000..3000, and area 300..1500; choose explicit values according to area size, exposure and actual rendered evidence. These are renderer starting settings, not measured lux or calibrated real illumination. Values such as environment .55 and sun 3.2 can render too dark at default exposure 0 (ISO 100). The executor does not silently multiply intensities: correct declared values after inspecting rendered views.
Parameters are synthetic priors, never real-world measurements. No arbitrary code or external paths.'''
SCENE_SCHEMA_DESCRIPTION += '\nInstalled native asset kinds (use the exact key as object kind; size is the native measured bounding box in meters): ' + json.dumps({key:{field:value for field,value in asset.items() if field!='path'} for key,asset in ASSETS.items()})
SCENE_SCHEMA_DESCRIPTION += '\nRegistered texture IDs: ' + ', '.join(NATIVE_MATERIALS)
SCENE_SCHEMA_DESCRIPTION += '\nRegistered texture materials accept optional appearance.texture_tint:[r,g,b] in 0..1. It multiplies base-color texture in linear RGB after sRGB decoding; [1,1,1] retains the original texture. It does not modify normal maps, geometry, source files or imported/native asset materials. Object color and named material base_color remain fallback colors when no texture is used. Use texture_tint to stain wood or tint fabric while retaining its pattern. Named appearance merges before object overrides; omission preserves existing textured appearance. Material receipts include the tint.'
SCENE_SCHEMA_DESCRIPTION += '\nThere is no generic opacity/transmission parameter. Registered native assets with supports_native_opacity_multiplier=true accept appearance.native_opacity_multiplier in 0..1, applied only to existing unconnected MDL Opacity_Multiply inputs. It multiplies native alpha, not measured optical transmittance; preserve textures, geometry and colliders. Other materials in the same object remain unchanged unless separately supported. Check actual appearance_overrides and rendered views. All entries in cameras are final scene snapshots after interactions. Camera IDs such as before/after do not change capture time. Separate interaction_*_before/after.png files record the real action. Distinct-view requests require different useful camera poses; duplicate poses do not add coverage.'
SCENE_SCHEMA_DESCRIPTION += '\nAn executable action may set camera_id to an existing camera for its before/after images. Otherwise the executor selects the authored camera aimed closest to the target object. The pose stays fixed across that action; visual_evidence records the camera and target pixel bounds in both images. Use those images and visibility to assess the action.'
SCENE_SCHEMA_DESCRIPTION += '\nFor an interaction demonstration, an apply_force or robot_push action can add recording:{every_steps:4}. The executor renders actual simulation states at that step interval and exports an MP4, original PNG frames and a timeline with simulation timestamps and target positions. Empty recording:{} selects approximately 30 fps from physics dt; omitting recording keeps endpoint-only captures. This adds rendering work but no physics steps, interpolated motion or extra simulator. FPS is 1/(every_steps*physics_dt); the final after image remains available when the action ends between video samples. Use the returned recording receipt for filenames and timing.'
SCENE_SCHEMA_DESCRIPTION += '\nAn apply_force or robot_push action may set contact_object_ids:[other_scene_object_ids] to observe target-object collisions, including static objects. object_contacts records each physics step at the actual physics rate (120 Hz for robot_push): force on the target from each named object, target and other object world positions, and any robot hand/finger forces in separate columns (empty for external-force actions). The summary reports first/last nonzero contact, peak force and displacement without deciding task success. These objects need not stay still; witness_object_ids retains its separate stationary-witness meaning. Ordinary robot trajectory is sampled every 3 physics steps (40 Hz), plus its final sample; recording FPS is independent.'
SCENE_SCHEMA_DESCRIPTION += '\nExecutable robot_push actions: {id,action:"robot_push",object_id,robot_id,robot_base_position:[x,y,z],waypoints:[{id,position:[x,y,z],duration_s}],optional robot_base_orientation_wxyz,end_effector_orientation_wxyz,witness_object_ids,contact_object_ids,observe_seconds,camera_id,recording}. Uses installed official Franka Panda, closed fingers and Lula IK joint targets. Waypoints describe the right_gripper IK frame in world meters; this differs from the reported right-finger body origin. Default base orientation [1,0,0,0], end-effector orientation [0,1,0,0], observation 1.5 seconds. A shared robot_id keeps the same base pose. Target and any witness objects must be dynamic. Robot captures run physics at 120 Hz and preserve ordinary apply_force step counts. Mass, friction and mesh collision approximation stay scene-authored. Success requires >=.04m target translation, >=3 sampled hand contacts above .05N, <=.005m movement before contact threshold, <=.01m witness movement and final target root-Z tilt <=20 degrees, <=.02m vertical displacement throughout the trajectory, and target visibility in both endpoint images; checks and raw trajectories remain visible on failure. No target force or pose commands, grasp, measured dynamics or general motion-planning claim. Place the robot on a support, author reachable collision-aware waypoints, inspect actual before/after evidence, and revise task content when needed. Total action steps stay within the existing 10000-step budget.'
SCENE_SCHEMA_DESCRIPTION += '\nEnvironment lights may additionally select environment_id from this registry: '+json.dumps({key:{k:v for k,v in record.items() if k!='path'} for key,record in ENVIRONMENTS.items()})+'. The HDR texture affects illumination and visible sky, not scene geometry. An optional direction sets the world direction of the HDR lower pole, tilting the whole environment after stage-up-axis alignment; it does not specify the sun position. Omit direction to retain the level horizon. HDR brightness must be verified in the actual renderer and exposure. Preserve texture provenance and compare actual rendered sky before selecting intensity. An HDR image does not supply outdoor geometry or metric GT. You may explicitly create outdoor objects using supported SceneProgram kinds and registered assets, respecting bounds and recording synthetic/program provenance. Never claim uncreated or merely pictured background geometry was simulated.'


SCENE_SCHEMA_DESCRIPTION += '\nDielectric controls: optional ior (1..3, default 1.5) sets the refractive-index basis of surface reflection; specular (0..1, default .5) scales normal-incidence Fresnel F0 by 2*specular. Specular .5 retains the IOR Fresnel reflectance, 0 removes the normal-incidence dielectric reflection, and 1 doubles it. The executor authors an effective UsdPreviewSurface IOR while retaining the metallic workflow, metal color, roughness and textures. This controls surface reflection only, not glass transmission or opacity. Named materials merge before object-local appearance. Native OmniPBR supports roughness, metallic and specular through its MDL constants even when the source uses unauthored defaults, preserving textures and their blend influences. OmniPBR IOR, unsupported controls on other MDL shaders, connected inputs and specular-color workflows retain their source behavior and are reported as skipped. Omitted controls preserve existing shader defaults.'
SCENE_SCHEMA_DESCRIPTION += '\nImported meshes preserve source color, metallic and roughness even without images or UVs. appearance.roughness and appearance.metallic override the source scalar factor (and multiply any source metallic-roughness texture) on each face material. Named scene materials merge before object overrides. With source UVs, base color/emissive use sRGB textures; normal, metallic-roughness (G/B), and occlusion (R) use raw textures. Source tint and emissive factors are retained. Opacity and glTF material extensions are not implemented. Inspect capture appearance_overrides and bound_texture_slots for actual bindings; this is not calibrated reflectance.'


def scene_contract_capabilities():
    """Machine-readable summary for DSH and planners; no runtime probing."""
    return {
        'schemas': {
            'spatialforge.scene/v1': {'max_objects': SCENE_V1_MAX_OBJECTS, 'max_cameras':64, 'executor': 'desktop_isaac'},
            'spatialforge.scene/v2': {'max_objects': SCENE_V2_MAX_OBJECTS, 'max_cameras':64, 'executor': 'desktop_isaac'},
        },
        'extensions': ['scene_graph', 'rooms', 'zones', 'portals', 'assets', 'materials', 'lights', 'render_environment', 'navigation', 'affordances', 'semantic_layers', 'provenance'],
        'asset_sources': ['builtin', 'usd', 'mesh', 'generated', 'diffusion', 'sam3d', 'procedural', 'imported'],
        'native_assets': {key:{field:value for field,value in asset.items() if field!='path'} for key,asset in ASSETS.items()},
        'appearance_controls': {'fields':sorted(APPEARANCE_FIELDS),
            'registered_textures':{'kinds':['box','cylinder','sphere','container','composite'],
                'texture_tint':'optional linear RGB multiplier [0..1,0..1,0..1] on decoded base color; default white; normal map unchanged; object color does not tint textures',
                'uv':'planar faces; cylinder circumference/height and planar caps; sphere equator/XZ meridian with pole distortion',
                'geometry':'96 curve segments, 48 sphere latitude intervals; smooth normals; convex hull per part',
                'feedback':'material_dependencies records UV mapping per prim'},
            'dielectric_controls':{'fields':['ior','specular'],'specular_default':.5,
                'meaning':'ior sets dielectric Fresnel reflectance; specular scales normal-incidence F0 by 2*specular; metallic workflow retained',
                'implementation':'effective PreviewSurface IOR; does not enable transmission or change opacity',
                'native_support':'PreviewSurface metallic workflow: ior and specular; native OmniPBR: specular_level plus roughness/metallic constants, preserving texture blend. Unsupported IOR/MDL controls and connected inputs remain source-authored and are reported as skipped'},
            'imported_textured_mesh':{'fields':['roughness','metallic','ior','specular'],'meaning':'replace source factor per material, retaining texture variation; named material then object override',
                'base_color':'source RGB factor in linear space times sRGB texture; source UVs preserved',
                'texture_slots':['base_color','normal','metallic_roughness','occlusion','emissive'],
                'untextured_materials':'source color, metallic and roughness factors need no texture or UV',
                'unsupported':['imported opacity','glTF material extensions'],
                'feedback':'asset_dependencies.appearance_overrides per material; actual values and skipped texture slots'},
            'native_opacity_multiplier':{'range':[0,1],
                'registered_kinds':[key for key,asset in ASSETS.items() if asset.get('supports_native_opacity_multiplier') is True],
                'native_input':'existing unconnected scalar MDL Opacity_Multiply',
                'meaning':'native alpha multiplier, not calibrated optical transmittance',
                'feedback':'appearance_overrides per material; unsupported objects reject at validation, no matching input fails capture'}},
        'texture_ids':list(NATIVE_MATERIALS),
        'environment_maps':{key:{k:v for k,v in record.items() if k!='path'} for key,record in ENVIRONMENTS.items()},
        'lighting_controls':{'point_spot_unsized':'zero-radius point emitter; USD treatAsPoint=true',
            'point_spot_size':'size[0] spherical emitter diameter in meters; size[1] unused',
            'area_size':'width and height in meters','intensity':'unchanged USD input, not calibrated lux',
            'feedback':'capture/report.json and evidence.json light_receipts'},
        'outdoor_geometry':{'allowed':True,'method':'explicitly create outdoor objects with supported kinds and registered assets',
            'limits':'respect scene bounds; preserve synthetic/program provenance; HDR images alone are not geometry or GT'},
        'layout_guidance':{'design_tool':'spatialforge_layout','file_handoff':'an existing reference is optional; the pipeline generates one when omitted. To use a reference while authoring task code, generate and inspect it first','prepared_source':{'mode':'reference','design_task_id':'completed layout task ID'},'modes':['generate','edit','reference'],'source':'registered image or captured parent source_view','generator':'FLUX.2-klein-9B','authority':'design reference only; native Isaac provides GT','generated_objects':'diffusion/SAM3/SAM3D via generated kind'},
        'executable_interactions': ['apply_force','robot_push'],
        'program_submission': {'parameter':'scene_program_path','tools':['spatialforge_capture','spatialforge_run','spatialforge_refine'],
            'source':'Complete JSON written with standard file tools under the configured task root, or source_path returned by spatialforge_task_code; either input route is accepted','max_bytes':1048576,
            'validation':'existing scene contract, native alias compatibility and registered mesh availability before queueing',
            'first_pass':'frozen complete SceneProgram, no planner rewrite; existing asset realization and native normalization apply',
            'later_repairs':'submitted scene data stays operator-controlled; inspect captures and submit your own revision. Text-only requests retain their existing repair budget',
            'evidence':['submitted_program.json','program_handoff.json'],
            'authority':'task-authored scene data; never GT or acceptance'},
        'geometry_preview': {'file':'geometry_preview.json','tool':'spatialforge_evidence',
            'task_code':'from spatialforge.geometry_preview import preview_scene_geometry; preview_scene_geometry(program, "/assets")',
            'scope':'initial source mesh fit, composite part bounds versus placement envelope, and box top faces; not GT, semantic orientation or contact validation',
            'scene_mutation':False,'automatic_extra_retries':0},
        'repair_history':{'files':['repair_context.json','repair_changes.json'],'tool':'spatialforge_evidence',
            'scope':'bounded current and prior capture receipts, image manifest and object-ID program differences; advice only',
            'images':{'current_max':6,'previous_max':2,'design_reference':'last, separately labeled'},
            'pose_lock':False,'automatic_extra_retries':0,'gt_written':False},
        'gt_authority': ['desktop_isaac_native_state', 'official_source_annotations'],
        'data_selection':{'feedback_file':'data_selection.json','tool':'spatialforge_evidence',
            'marker_eligibility':'bbox min edge >= center marker diameter + 6 pixels; source boxes and GT unchanged',
            'replenishment':'after item rejection, consume unique diverse reserves; at most target_items + min(target_items, 8) reviews',
            'rendering':'only consumed candidates; no rerender or retry of a rejected item',
            'shortfall':'explicit when review budget or eligible unique candidates run out',
            'limits':'size screening is not visibility or semantic acceptance; scene retry/refine limits unchanged'},
        'quality_policy': 'record capability gaps and repair suggestions; quality review never writes ground truth',
    }
