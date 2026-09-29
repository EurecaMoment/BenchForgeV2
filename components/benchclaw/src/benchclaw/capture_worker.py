"""Runs in the simulator's own Python environment; writes one normalized capture."""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def serial(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,dict):return {k:serial(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [serial(v) for v in value]
    return value


def rgb(output,index,camera,array):
    relative=f'{index:06}_{camera}.png'
    Image.fromarray(np.asarray(array,dtype=np.uint8)[...,:3]).convert('RGB').save(output/relative)
    return relative


def habitat(p,output):
    import habitat_sim as hs
    import magnum as mn
    import quaternion
    config=hs.SimulatorConfiguration();config.scene_id=p['scene'];config.gpu_device_id=0
    specs=[]
    for name,kind in [('rgb',hs.SensorType.COLOR),('depth',hs.SensorType.DEPTH)]:
        sensor=hs.CameraSensorSpec();sensor.uuid=name;sensor.sensor_type=kind;sensor.resolution=[p['height'],p['width']];sensor.position=mn.Vector3(0,1.5,0);sensor.hfov=mn.Deg(90)
        specs.append(sensor)
    agent_config=hs.agent.AgentConfiguration();agent_config.sensor_specifications=specs
    simulator=hs.Simulator(hs.Configuration(config,[agent_config]));frames=[]
    rng=np.random.default_rng(p['seed']);simulator.seed(p['seed']);simulator.pathfinder.seed(p['seed'])
    try:
        agent=simulator.initialize_agent(0)
        if not simulator.pathfinder.is_loaded:raise RuntimeError('Habitat navmesh missing')
        for i in range(p['frames']):
            for sample_attempt in range(20):
                state=hs.AgentState();state.position=simulator.pathfinder.get_random_navigable_point()
                state.rotation=hs.utils.common.quat_from_angle_axis(float(rng.uniform(-math.pi,math.pi)),np.array([0,1,0]))
                agent.set_state(state);obs=simulator.get_sensor_observations();sensor_state=agent.get_state().sensor_states['rgb']
                depth=np.asarray(obs['depth'],dtype=np.float32)
                if np.isfinite(depth).all() and (depth>0).mean()>.5 and np.std(obs['rgb'][...,:3])>1:break
            else:raise RuntimeError('No valid Habitat viewpoint within 20 seeded samples')
            depth_name=f'{i:06}_depth.npy';np.save(output/depth_name,depth)
            rotation=quaternion.as_rotation_matrix(sensor_state.rotation)@np.diag([1,-1,-1])
            transform=np.eye(4);transform[:3,:3]=rotation;transform[:3,3]=sensor_state.position
            f=p['width']/2
            frames.append({'images':{'rgb':rgb(output,i,'rgb',obs['rgb'])},'files':[{'kind':'depth','uri':depth_name}],
                'gt':{'camera_to_world':transform.tolist(),'camera_frame':'x_right_y_down_z_forward','world_frame':'habitat_y_up',
                      'camera_intrinsics':[[f,0,p['width']/2],[0,f,p['height']/2],[0,0,1]],'depth_unit':'m','depth_axis':'camera_z',
                      'agent_position':list(state.position),'sampling':'seeded_navigable_viewpoints','sample_attempts':sample_attempt+1}})
    finally:simulator.close()
    return {'source_uri':Path(p['scene']).as_uri(),'frames':frames}


def libero_hdf5(p,output):
    import h5py
    frames=[]
    with h5py.File(p['dataset'],'r') as file:
        demo=file['data'][p['demo']]
        if len(demo['actions'])<p['frames']:raise ValueError('Requested frames exceed demonstration')
        image_keys=[k for k,v in demo['obs'].items() if len(v.shape)==4 and v.shape[-1]==3]
        for i in range(p['frames']):
            images={k:rgb(output,i,k,demo['obs'][k][i][::-1]) for k in sorted(image_keys)}
            state={k:demo[k][i] for k in demo if isinstance(demo[k],h5py.Dataset) and demo[k].shape and demo[k].shape[0]>i}
            state['observation']={k:v[i] for k,v in demo['obs'].items() if k not in image_keys}
            state['rgb_transform']='vertical_flip_from_mujoco'
            frames.append({'images':images,'files':[],'gt':serial(state)})
    return {'source_uri':Path(p['dataset']).as_uri()+'#'+p['demo'],'frames':frames}


def libero(p,output):
    import h5py
    from libero.libero import benchmark
    from libero.libero.envs import OffScreenRenderEnv
    suite=benchmark.get_benchmark_dict()[p['suite']]();task=suite.get_task(p['task_id'])
    root=Path('/home/maqiang/simulators/LIBERO')
    dataset=root/'datasets'/p['suite']/(task.name+'_demo.hdf5')
    with h5py.File(dataset,'r') as file:
        demo=file['data'][p['demo']];actions=demo['actions'][:p['frames']];initial=demo['states'][0]
    if len(actions)!=p['frames']:raise ValueError('Demonstration shorter than requested capture')
    env=OffScreenRenderEnv(bddl_file_name=str(root/'libero/libero/bddl_files'/task.problem_folder/task.bddl_file),
                          camera_heights=p['height'],camera_widths=p['width'])
    frames=[]
    try:
        env.seed(p['seed']);env.reset();env.set_init_state(initial)
        for i,action in enumerate(actions):
            obs,reward,done,info=env.step(action)
            keys=[k for k,v in obs.items() if isinstance(v,np.ndarray) and v.ndim==3 and v.shape[-1]==3]
            images={k:rgb(output,i,k,obs[k][::-1]) for k in sorted(keys)}
            state=env.sim.get_state().flatten()
            frames.append({'images':images,'files':[],'gt':serial({'action':action,'reward':reward,'done':bool(done),'info':info,
                'observation':{k:v for k,v in obs.items() if k not in keys},'simulator_state':state,'task':task.name,'language':task.language,
                'action_source':'official_demo_replay','rgb_transform':'vertical_flip_from_mujoco'})})
            if done and i+1<p['frames']:raise RuntimeError('Episode terminated before requested timepoints')
    finally:env.close()
    return {'source_uri':dataset.as_uri(),'frames':frames}


def carla(p,output):
    import carla
    import queue
    import importlib.util
    legacy=Path(__file__).resolve().parents[2]/'BenchClaw/simulatorCards/CARLA/quick_capture.py'
    spec=importlib.util.spec_from_file_location('carla_geometry',legacy);geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
    client=carla.Client(p['host'],p['port']);client.set_timeout(30)
    if p.get('map_name'):
        if not client.get_world().get_map().name.endswith('/'+p['map_name']):client.load_world(p['map_name'])
    world=client.get_world();original=world.get_settings();settings=world.get_settings()
    settings.synchronous_mode=True;settings.fixed_delta_seconds=.1
    actors=[];sensors=[];frames=[];traffic=None
    try:
        world.apply_settings(settings)
        blueprint=world.get_blueprint_library().filter('vehicle.tesla.model3')[0]
        points=world.get_map().get_spawn_points()
        vehicle=world.try_spawn_actor(blueprint,points[p['seed']%len(points)])
        if vehicle is None:raise RuntimeError('Selected CARLA spawn is occupied')
        actors.append(vehicle)
        if p.get('autopilot',True):
            traffic=client.get_trafficmanager(p.get('tm_port',5802));traffic.set_synchronous_mode(True);traffic.set_random_device_seed(p['seed'])
            vehicle.set_autopilot(True,p.get('tm_port',5802));traffic.distance_to_leading_vehicle(vehicle,5)
        mounts=geometry.camera_mounts(vehicle)
        for camera in p.get('cameras',['front','side_left','side_right','rear','top']):
            mount=mounts[camera]
            for kind,blueprint_id in [('rgb','sensor.camera.rgb'),('depth','sensor.camera.depth'),('instance','sensor.camera.instance_segmentation')]:
                bp=world.get_blueprint_library().find(blueprint_id)
                bp.set_attribute('image_size_x',str(p['width']));bp.set_attribute('image_size_y',str(p['height']));bp.set_attribute('fov','90')
                sensor=world.spawn_actor(bp,carla.Transform(mount['loc'],mount['rot']),attach_to=vehicle)
                q=queue.Queue();sensor.listen(q.put);actors.append(sensor);sensors.append((camera,kind,sensor,q))
        previous=None
        for tick in range(p.get('max_ticks',3000)):
            if not p.get('autopilot',True):vehicle.apply_control(carla.VehicleControl(throttle=.25,steer=0))
            frame_id=world.tick();i=len(frames);images={};files=[];transforms={};visibility={};measurements=[]
            for camera,kind,sensor,q in sensors:
                measurement=q.get(timeout=30)
                while measurement.frame<frame_id:measurement=q.get(timeout=30)
                if measurement.frame!=frame_id:raise RuntimeError('CARLA sensor synchronization failure')
                measurements.append((camera,kind,sensor,measurement))
            position=vehicle.get_location()
            if tick%p.get('save_every',1) or (previous and position.distance(previous)<p.get('min_save_distance',0)):continue
            for camera,kind,sensor,measurement in measurements:
                bgra=np.frombuffer(measurement.raw_data,dtype=np.uint8).reshape(p['height'],p['width'],4)
                transforms[camera]=measurement.transform.get_matrix()
                if kind=='rgb':images[camera]=rgb(output,i,camera,bgra[...,:3][...,::-1])
                elif kind=='depth':
                    depth=(bgra[:,:,2].astype(np.float64)+256*bgra[:,:,1]+65536*bgra[:,:,0])/(16777215)*1000
                    name=f'{i:06}_{camera}_depth.npy';np.save(output/name,depth.astype(np.float32));files.append({'kind':'depth','uri':name})
                else:
                    name=f'{i:06}_{camera}_instance.png';Image.fromarray(bgra[...,:3][...,::-1]).save(output/name);files.append({'kind':'mask','uri':name})
                    visibility[camera]=geometry.collect_visible_actor_metadata({'actor':sensor,'image_width':p['width'],'image_height':p['height'],'fov':90,'min_visible_pixels':12},measurement,world)
                    for actor in visibility[camera]['visible_actors']:
                        actor['bbox_2d']['xmax']+=1;actor['bbox_2d']['ymax']+=1
            snapshot=world.get_snapshot();visible_actors=[]
            for actor in world.get_actors().filter('vehicle.*'):
                visible_actors.append({'id':actor.id,'type':actor.type_id,'transform':actor.get_transform().get_matrix(),
                    'bbox_extent':[actor.bounding_box.extent.x,actor.bounding_box.extent.y,actor.bounding_box.extent.z]})
            frames.append({'images':images,'files':files,'gt':{'frame_id':frame_id,'timestamp':snapshot.timestamp.elapsed_seconds,
                'ego_transform':vehicle.get_transform().get_matrix(),'camera_to_world_unreal':transforms,
                'coordinate_convention':'unreal_x_forward_y_right_z_up_left_handed','depth_unit':'m','depth_axis':'camera_z',
                'camera_intrinsics':[[p['width']/2,0,p['width']/2],[0,p['width']/2,p['height']/2],[0,0,1]],
                'world_actors':visible_actors,'visible_instance_metadata':visibility,'bbox_pixel_boundary':'half_open',
                'autopilot':p.get('autopilot',True),'speed_mps':geometry.actor_speed(vehicle)}})
            previous=position
            if len(frames)==p['frames']:break
        if len(frames)!=p['frames']:raise RuntimeError('CARLA capture budget exhausted before requested spatial samples')
    finally:
        if traffic:
            if vehicle is not None and vehicle.is_alive:
                vehicle.set_autopilot(False,p.get('tm_port',5802))
                world.tick()
            traffic.set_synchronous_mode(False)
        for actor in reversed(actors):
            if actor.is_alive:
                if hasattr(actor,'stop'):actor.stop()
                actor.destroy()
        world.apply_settings(original)
    return {'source_uri':f'carla://{p["host"]}:{p["port"]}/{world.get_map().name}','frames':frames}


if __name__=='__main__':
    mode,config,directory=sys.argv[1:];p=json.loads(Path(config).read_text());output=Path(directory)
    result={'habitat':habitat,'libero':libero,'libero_hdf5':libero_hdf5,'carla':carla}[mode](p,output)
    (output/'collection.json').write_text(json.dumps(serial(result)))
