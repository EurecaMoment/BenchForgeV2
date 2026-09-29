"""Native simulator records to compiler evidence, preserving camera/sequence semantics."""
import math
from pathlib import Path
from .artifacts import read, write, jsonl


def adapt_capture(args,directory,config):
    source=Path(args['input']).resolve()
    if source.is_dir():source=source/'collection_manifest.json'
    manifest=read(source);records=[];filtered=[]
    simulator=args.get('simulator','habitat')
    if simulator=='habitat':
        import numpy as np
        groups=manifest.get('scenes',[manifest])
        for scene in groups:
            camera=scene.get('camera') or args.get('camera')
            if not camera:raise ValueError('Habitat capture needs explicit camera intrinsics; do not infer them from the image alone')
            for frame in scene['records']:
                origin=Path(frame['raw_depth_path']);origin=origin if origin.is_absolute() else source.parent/origin
                depth=np.load(origin).squeeze()
                h,w=depth.shape
                yy,xx=np.mgrid[:h,:w]
                ranges=depth*np.sqrt(1+((xx-camera['cx'])/camera['fx'])**2+((yy-camera['cy'])/camera['fy'])**2)
                candidates=[]
                radius=int(args.get('radius',18))
                for y in np.linspace(radius+4,h-radius-5,8,dtype=int):
                    for x in np.linspace(radius+4,w-radius-5,10,dtype=int):
                        patch=ranges[y-radius:y+radius+1,x-radius:x+radius+1]
                        if not np.isfinite(patch).all() or patch.min()<0.1:continue
                        median=float(np.median(patch))
                        if patch.min()<0.85*median or patch.max()>1.18*median:continue
                        candidates.append((x,y,median))
                # Deterministic broad coverage of visible surface patches. No semantic object guesses.
                selected=[]
                for candidate in sorted(candidates,key=lambda v:v[2]):
                    if all(math.hypot(candidate[0]-v[0],candidate[1]-v[1])>radius*4 for v in selected):selected.append(candidate)
                    if len(selected)>=args.get('regions',4):break
                iid=f"{scene['scene']}_{frame['frame_index']:05d}"
                if len(selected)<2:
                    filtered.append({'id':iid,'reason':'insufficient_continuous_visible_regions'});continue
                original=directory/'sources'/f'{iid}.json';write(original,{'camera':camera,'record':frame})
                image=Path(frame['rgb_path']);image=image if image.is_absolute() else source.parent/image
                objects=[]
                for i,(x,y,_) in enumerate(selected):
                    local=ranges[y-7:y+8,x-7:x+8]
                    objects.append({'object_id':f'region_{i}','category':'surface region',
                        'bbox_xyxy':[int(x-7),int(y-7),int(x+8),int(y+8)],
                        'depth_median':float(np.median(local)),
                        'measurement':{'kind':'median_camera_range','patch_half_size':7,'footprint_radius':radius}})
                records.append({'id':iid,'sample_id':iid,'scene':scene['scene'],'source_name':scene['scene'],
                    'provenance':{'kind':'simulation','path':str(original)},'source_type':'simulation',
                    'image_path':str(image),'media':[str(image)],'raw_depth_path':str(origin),
                    'objects':objects,'camera':camera,'depth_semantics':'euclidean_range',
                    'sequence_semantics':'independent_capture','adapter_code':str(Path(__file__).resolve()),
                    'sampling_policy':{'regions':args.get('regions',4),'radius':radius}})
    elif simulator=='libero':
        for task in manifest.get('tasks',[]):
            for frame in task['records']:
                iid=f"task_{task['task_id']}_step_{frame['step']}"
                original=directory/'sources'/f'{iid}.json';write(original,frame)
                records.append({'id':iid,'sample_id':iid,'task_id':task['task_id'],'step':frame['step'],
                    'media':list(frame['image_paths'].values()),'image_path':next(iter(frame['image_paths'].values()),None),
                    'provenance':{'kind':'simulation','path':str(original)},'source_type':'simulation',
                    'sequence_semantics':'ordered_sequence','sequence_id':task['task_name'],'source_fields':frame,
                    'task_language':task['language']})
    elif simulator=='carla':
        for scene in manifest.get('results',[]):
            scene_name=scene.get('map',scene.get('map_name','carla'))
            for frame in scene['frame_records']:
                views=frame.get('image_paths') or frame['cameras']
                if isinstance(views,list):
                    views={name:str(source.parent/Path(scene_name).name/name/f"{Path(scene_name).name}_{frame['frame_index']:05d}.{manifest.get('format','jpg')}") for name in views}
                for name,raw_image in views.items():
                    native=frame['camera_poses'][name]
                    visible=native.get('visible_objects') or {}
                    actors=visible.get('visible_actors',[])
                    image=Path(raw_image);image=image if image.is_absolute() else source.parent/image
                    objects=[]
                    for actor in actors:
                        box=actor['bbox_2d']
                        category=actor.get('type_id','unknown').split('.')[0]
                        objects.append({'object_id':str(actor['actor_id']),'category':category,
                            'bbox_xyxy':[box['xmin'],box['ymin'],box['xmax']+1,box['ymax']+1],
                            'area_px':box.get('pixel_count'),'native_actor':actor})
                    iid=f"{Path(scene_name).name}_{frame['frame_index']:05d}_{name}"
                    original=directory/'sources'/f'{iid}.json';write(original,{'frame':frame,'camera':native})
                    records.append({'id':iid,'sample_id':iid,'media':[str(image)],'image_path':str(image),
                        'instance_path':frame.get('instance_paths',{}).get(name),
                        'objects':objects,'source_fields':frame,'camera_name':name,'source_name':scene_name,
                        'provenance':{'kind':'simulation','path':str(original)},'source_type':'simulation',
                        'sequence_semantics':'ordered_sequence','sequence_id':scene_name+'_'+name,'step':frame['sim_frame'],
                        'depth_semantics':'actor_origin_distance_not_visible_surface',
                        'unsupported_from_single_frame':['speed','future_trajectory','route_optimal_action']})
    else:raise ValueError('Supported native adapters: habitat, libero, carla')
    jsonl(directory/'evidence.jsonl',records);jsonl(directory/'filtered.jsonl',filtered)
    if not records:raise ValueError('No usable native evidence records; see filtered.jsonl')
    return {'input':str(directory/'evidence.jsonl'),'records':len(records),'filtered':len(filtered),
            'gt_source':'native simulator data','note':'Surface regions are geometric samples, not semantic object annotations. Ordered simulator sequences retain step/sequence IDs.'}
