"""Independent native Isaac Sim capture adapter; run with Isaac's Python.

Supports explicitly authored cuboids, cameras and optional initial velocity.
No scene planning, generated assets or SpatialForge integration is implicit.
"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    scene = json.loads(Path(request['scene_program']).read_text(encoding='utf-8'))
    output = Path(request['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True})
    try:
        import numpy as np
        from PIL import Image
        from pxr import Gf, UsdLux
        from isaacsim.core.api import World
        from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid
        from isaacsim.core.utils.semantics import add_update_semantics
        from isaacsim.sensors.camera import Camera

        world = World(stage_units_in_meters=1.0)
        light = UsdLux.DomeLight.Define(world.stage, '/World/Light')
        light.CreateIntensityAttr(float(scene.get('light_intensity', 1000)))
        objects = []
        for index, spec in enumerate(scene['objects']):
            kind = DynamicCuboid if spec.get('dynamic') else FixedCuboid
            obj = world.scene.add(kind(prim_path=f'/World/Object_{index}', name=f'object_{index}',
                position=np.array(spec['position']), scale=np.array(spec['size']), size=1,
                color=np.array(spec.get('color', [0.6,0.6,0.6]))))
            add_update_semantics(obj.prim, spec.get('label', spec['id']))
            objects.append((spec, obj))
        camera = Camera(prim_path='/World/Camera', resolution=tuple(scene.get('resolution', [640,480])))
        world.reset()
        camera.initialize()
        camera.add_distance_to_image_plane_to_frame()
        camera.add_instance_segmentation_to_frame()
        for spec, obj in objects:
            if spec.get('initial_velocity') is not None:
                obj.set_linear_velocity(np.array(spec['initial_velocity']))
        trajectory=[]
        for step in range(scene.get('steps', 60)):
            world.step(render=True)
            trajectory.append({'step':step,'objects':[
                {'id':spec['id'],'position':obj.get_world_pose()[0].tolist(),
                 'orientation_wxyz':obj.get_world_pose()[1].tolist()} for spec,obj in objects]})
        views=[]
        for index, view in enumerate(scene['views']):
            eye, target = Gf.Vec3d(*view['eye']), Gf.Vec3d(*view['target'])
            rotation=Gf.Matrix4d().SetLookAt(eye,target,Gf.Vec3d(0,0,1)).GetInverse().ExtractRotationQuat()
            q=np.array([rotation.GetReal(),*rotation.GetImaginary()])
            camera.set_world_pose(position=np.array(view['eye']),orientation=q,camera_axes='usd')
            for _ in range(20):
                world.render()
                app.update()
            rgba=camera.get_rgba()
            if rgba is None or not rgba.size:
                raise RuntimeError('Isaac returned no camera image')
            Image.fromarray(rgba[:,:,:3].astype(np.uint8)).save(output/f'view_{index}.png')
            frame=camera.get_current_frame()
            depth=frame.get('distance_to_image_plane')
            if depth is None:
                raise RuntimeError('Isaac returned no depth frame')
            np.save(output/f'depth_{index}.npy',depth)
            segmentation=frame.get('instance_segmentation')
            if segmentation is not None:
                np.save(output/f'instance_{index}.npy',segmentation['data'])
                (output/f'instance_{index}.json').write_text(json.dumps(segmentation.get('info',{})),encoding='utf-8')
            views.append({'image':f'view_{index}.png','depth':f'depth_{index}.npy',
                          'eye':view['eye'],'orientation_wxyz':q.tolist(),'depth_type':'distance_to_image_plane'})
        world.stage.GetRootLayer().Export(str(output/'scene.usda'))
        report={'source':'isaac_sim','views':views,'trajectory':trajectory,
                'quality':'not_assessed','interaction_success':'not_assessed'}
        (output/'state.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:
        app.close()


if __name__=='__main__':
    main()
