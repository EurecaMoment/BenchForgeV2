"""Read-only initial geometry advice; never selects semantic pose or changes GT."""
import json
import math
from pathlib import Path
import re
from .mesh_geometry import transform_mesh_geometry
from .part_geometry import part_bounds, horizontal_box_top
from .support_graph import objects_in_support_order


GUIDANCE = ('geometry_preview.json is program/source-geometry advice before simulation, not GT or contact validation. '
    'uniform_fit takes the smallest requested_size/oriented_extent ratio. Check limiting_axes and actual_size_m; '
    'axis_target_examples are alternative envelopes, not automatic fixes: each keeps one requested axis length and source proportions, '
    'and may exceed other original limits. Choose pose from source geometry/reference images, not bounding boxes alone. '
    'support references the whole object top, not the nearest shelf. Composite box_top_faces report actual local part geometry, '
    'For composites, declared placement envelope and part geometry differ: composite_geometry gives actual part bottom/top and inset. '
    'A base_z=0 envelope can contain parts floating above its bottom; compare geometry_bottom_gap_m and geometry_base_z_for_contact. '
    'world top height and base_z_for_contact under the current contract; xy remains world coordinates. '
    'In either scene schema, a negative base_z can select a lower board. '
    'A face or footprint match is geometric advice only; clearance, semantic orientation and real contact still require inspection/simulation. '
    'Task Python can call from spatialforge.geometry_preview import preview_scene_geometry; '
    'preview_scene_geometry(program, "/assets") reads only referenced mesh.json files once per unique asset per call, '
    'without Isaac or a model API. Do not modify the Harness to use it.')


def mesh_fit_preview(mesh, requested_size, mesh_transform=None):
    _,receipt=transform_mesh_geometry(mesh['vertices'],requested_size,mesh.get('coordinate_frame'),mesh_transform)
    extent=[receipt['oriented_bounds_before_scale'][1][i]-receipt['oriented_bounds_before_scale'][0][i] for i in range(3)]
    ratios=[requested_size[i]/extent[i] for i in range(3)]
    scale=min(ratios);actual=receipt['actual_size_m']
    return {**{k:receipt[k] for k in ('actual_size_m','requested_size_limits_m','orientation_deg_xyz','orientation_source','gravity_alignment','uniform_scale','oriented_bounds_before_scale')},
        **({'camera_coordinates':mesh['camera_coordinates']} if mesh.get('camera_coordinates') else {}),
        **({'source_camera':mesh['source_camera']} if mesh.get('source_camera') else {}),
        'limiting_axes':['xyz'[i] for i in range(3) if math.isclose(ratios[i],scale,rel_tol=1e-8)],
        'fill_fraction':[actual[i]/requested_size[i] for i in range(3)],
        'axis_target_examples':[{'keep_requested_axis':'xyz'[i],
            'proportional_envelope_m':[extent[j]*ratios[i] for j in range(3)],
            'exceeds_original_limits_on':['xyz'[j] for j in range(3) if extent[j]*ratios[i]>requested_size[j]+1e-8]} for i in range(3)],
        'semantic_upright':'not_inferred','source':'registered mesh vertices and declared transform'}


def _world_xy(xy,local,yaw):
    c=math.cos(math.radians(yaw));s=math.sin(math.radians(yaw))
    return [xy[0]+local[0]*c-local[1]*s,xy[1]+local[0]*s+local[1]*c]


def _corners(xy,size,yaw):
    return [_world_xy(xy,[x*size[0]/2,y*size[1]/2],yaw) for x,y in ((-1,-1),(1,-1),(1,1),(-1,1))]


def _fits_face(obj,size,face):
    # Conservative oriented bounding rectangle, not mesh contact or stability.
    corners=_corners(obj['xy'],size,obj.get('yaw_deg',0))
    local=[_world_xy([0,0],[p[0]-face['world_xy'][0],p[1]-face['world_xy'][1]],-face['yaw_deg']) for p in corners]
    return all(abs(p[0])<=face['size_xy_m'][0]/2+1e-8 and abs(p[1])<=face['size_xy_m'][1]/2+1e-8 for p in local)


def preview_scene_geometry(program, assets_root=None, mesh_loader=None):
    """Use a validated SceneProgram and read-only registry root or mesh loader.

    Only named assets are loaded; no registry scan, writes or semantic pose search.
    Unknown mesh/support dimensions propagate as unknown rather than fabricated GT.
    """
    root=Path(assets_root).resolve() if assets_root is not None else None
    cache={};rows=[];by_id={};warnings=[]
    def load(asset_id):
        if asset_id not in cache:
            try:
                if mesh_loader is not None:value=mesh_loader(asset_id)
                else:
                    if root is None:raise ValueError('asset root unavailable')
                    if not isinstance(asset_id,str) or not re.fullmatch(r'asset_[a-f0-9]{16}',asset_id):raise ValueError('invalid registered asset ID')
                    path=(root/asset_id/'mesh.json').resolve()
                    if not path.is_relative_to(root):raise ValueError('asset path escapes registry')
                    value=json.loads(path.read_text(encoding='utf8'))
                if not isinstance(value,dict):raise ValueError('mesh record unavailable')
                cache[asset_id]={key:value.get(key) for key in ('vertices','coordinate_frame','camera_coordinates','source_camera')}
            except (ValueError,KeyError,OSError,TypeError) as exc:cache[asset_id]={'preview_error':type(exc).__name__+': '+str(exc)[:160]}
        return cache[asset_id]
    indexes={obj['id']:index for index,obj in enumerate(program['objects'])}
    for obj in objects_in_support_order(program['objects']):
        index=indexes[obj['id']]
        row={'object_id':obj['id'],'path':f'/objects/{index}','kind':obj['kind'],'support':obj['support'],
             'base_z':obj['base_z'],'requested_size_m':list(obj['size']),'actual_size_m':list(obj['size'])}
        if obj['kind'] in {'mesh','generated'}:
            row['actual_size_m']=None
            mesh=load(obj['asset_id']) if obj.get('asset_id') else {'preview_error':'asset not generated yet'}
            if 'preview_error' in mesh:row['unavailable']=mesh['preview_error']
            else:
                try:
                    row['mesh_fit']=mesh_fit_preview(mesh,obj['size'],obj.get('mesh_transform'))
                    row['actual_size_m']=row['mesh_fit']['actual_size_m']
                    if min(row['mesh_fit']['fill_fraction'])<.5:
                        warnings.append({'object_id':obj['id'],'code':'envelope_underfilled',
                            'detail':'at least one actual axis is less than half its requested envelope; check intended size and limiting_axes, not an automatic quality failure'})
                except (ValueError,KeyError,TypeError) as exc:row['unavailable']='mesh preview unavailable: '+str(exc)[:160]
        parent=by_id.get(obj['support'])
        support_top=0. if obj['support']=='ground' else parent.get('whole_object_top_z_m') if parent else None
        size=row['actual_size_m']
        base=support_top+obj['base_z'] if support_top is not None else None
        row['initial_bottom_z_m']=base
        row['initial_center_m']=[*obj['xy'],base+size[2]/2] if base is not None and size is not None else None
        row['whole_object_top_z_m']=base+size[2] if base is not None and size is not None else None
        geometry_bottom=base
        row['placement_size_basis']='declared_envelope' if obj['kind']=='composite' else 'normalized_geometry'
        if obj['kind']=='composite' and base is not None:
            bounds=[part_bounds(part) for part in obj['parts']]
            local_min=[min(bound[0][axis] for bound in bounds) for axis in range(3)]
            local_max=[max(bound[1][axis] for bound in bounds) for axis in range(3)]
            bottom_inset=size[2]/2+local_min[2]
            top_inset=size[2]/2-local_max[2]
            geometry_bottom=base+bottom_inset
            row['composite_geometry']={'local_min_m':local_min,'local_max_m':local_max,
                'size_m':[local_max[i]-local_min[i] for i in range(3)],
                'bottom_z_m':geometry_bottom,'top_z_m':base+size[2]/2+local_max[2],
                'bottom_inset_from_envelope_m':bottom_inset,'top_inset_from_envelope_m':top_inset,
                'scope':'analytic initial part extents, not physical contact; executor still places by declared envelope'}
            if bottom_inset>.002 or top_inset>.002:
                warnings.append({'object_id':obj['id'],'code':'composite_geometry_inset',
                    'detail':'parts do not reach the declared envelope bottom or top; check actual part bounds before treating base_z or whole_object_top as a contact surface; may be intentional'})
        row['initial_geometry_bottom_z_m']=geometry_bottom
        if geometry_bottom is not None and support_top is not None:
            row['geometry_bottom_gap_above_support_envelope_m']=geometry_bottom-support_top
            row['base_z_for_geometry_bottom_at_support_envelope']=obj['base_z']-(geometry_bottom-support_top)
        row['box_top_faces']=[]
        if base is not None and size is not None:
            parts=obj['parts'] if obj['kind']=='composite' else [{'shape':'box','size':size,'offset':[0,0,0]}] if obj['kind']=='box' else []
            for pi,part in enumerate(parts):
                if part['shape']!='box':continue
                face=horizontal_box_top(part)
                if face is None:continue
                yaw=obj.get('yaw_deg',0)
                xy=_world_xy(obj['xy'],face['center'],yaw)
                top=base+size[2]/2+face['center'][2]
                face_yaw=yaw+face['yaw_deg']
                row['box_top_faces'].append({'part_index':pi if obj['kind']=='composite' else None,
                    'world_xy':xy,'top_z_m':top,'size_xy_m':face['size_xy'],'yaw_deg':face_yaw,
                    'world_corners_xy':_corners(xy,face['size_xy'],face_yaw),
                    'base_z_for_contact':top-row['whole_object_top_z_m'],
                    'base_z_allowed_by_schema':-1000<=top-row['whole_object_top_z_m']<=1000,
                    'parent_dynamic':obj['dynamic'],'physical_support_validated':False})
        if parent and parent['box_top_faces'] and size is not None and base is not None:
            row['support_face_options']=[{'part_index':f['part_index'],'top_z_m':f['top_z_m'],
                'world_xy':f['world_xy'],'size_xy_m':f['size_xy_m'],'yaw_deg':f['yaw_deg'],
                'base_z_for_contact':f['base_z_for_contact'],'base_z_allowed_by_schema':f['base_z_allowed_by_schema'],
                'current_bottom_gap_m':base-f['top_z_m'],'footprint_within_face':_fits_face(obj,size,f),
                'geometry_bottom_gap_m':geometry_bottom-f['top_z_m'],
                'geometry_base_z_for_contact':obj['base_z']-(geometry_bottom-f['top_z_m']),
                'geometry_base_z_allowed_by_schema':-1000<=obj['base_z']-(geometry_bottom-f['top_z_m'])<=1000,
                'parent_dynamic':f['parent_dynamic']} for f in parent['box_top_faces']]
            matches=[f for f in row['support_face_options'] if f['footprint_within_face'] and abs(f['geometry_bottom_gap_m'])<1e-5]
            if not matches:warnings.append({'object_id':obj['id'],'code':'no_full_box_face_at_declared_height',
                'detail':'current conservative footprint and actual geometry bottom do not match a box top face; this does not prove missing contact or intersection'})
        if row.get('unavailable') or base is None:warnings.append({'object_id':obj['id'],'code':'preview_incomplete','detail':row.get('unavailable','support height unavailable')})
        rows.append(row);by_id[obj['id']]=row
    return {'schema':'spatialforge.geometry_preview/v1','authority':'program/source geometry advice; not simulation GT',
        'scene_id':program['scene_id'],'objects':sorted(rows,key=lambda row:indexes[row['object_id']]),'warnings':warnings,'mesh_assets_read':len(cache),
        'limits':['initial geometry only; no settling/contact/occlusion assessment','native object extents follow declared normalization; native internal surfaces are not inferred','semantic upright cannot be derived from bounds','envelope_underfilled is a heuristic, not an acceptance gate'],
        'guidance':GUIDANCE}


def compact_preview(preview):
    """Keep prompt size bounded; full preview remains available through evidence."""
    warned={warning['object_id'] for warning in preview['warnings']}
    useful=[row for row in preview['objects'] if row.get('mesh_fit') or row['object_id'] in warned or row.get('unavailable')]
    useful.sort(key=lambda row:row['object_id'] not in warned)
    def rounded(value):
        if isinstance(value,float):return round(value,6)
        if isinstance(value,list):return [rounded(v) for v in value]
        if isinstance(value,dict):return {k:rounded(v) for k,v in value.items()}
        return value
    objects=[]
    characters=len(json.dumps(preview['warnings'][:32]))+len(GUIDANCE)+512
    for row in useful[:32]:
        item={k:v for k,v in row.items() if k not in {'box_top_faces','support_face_options'}}
        if row.get('support_face_options'):
            options=sorted(row['support_face_options'],key=lambda face:(not face['footprint_within_face'],-math.prod(face['size_xy_m']),abs(face['current_bottom_gap_m'])))
            item['support_face_options']=options[:6]
            item['omitted_face_options']=max(0,len(options)-6)
        item=rounded(item)
        length=len(json.dumps(item))
        if characters+length>24000:continue
        characters+=length+2
        objects.append(item)
    return {'authority':preview['authority'],'warnings':preview['warnings'][:32],
        'objects':objects,
        'truncated_objects':len(useful)-len(objects),'guidance':GUIDANCE}
