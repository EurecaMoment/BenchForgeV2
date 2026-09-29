"""Paired SAM3D Gaussian and mesh output, with optional mesh UV baking."""
import os
import sys
from pathlib import Path
import numpy as np


PYTORCH3D_TO_OPENCV = np.diag([-1., -1., 1., 1.])


def opencv_camera_output(mesh, local_to_pytorch3d):
    """Adapt official +X-left/+Y-up output to sam3d_camera +X-right/+Y-down."""
    result=mesh.copy()
    result.apply_transform(PYTORCH3D_TO_OPENCV)
    return result, PYTORCH3D_TO_OPENCV @ np.asarray(local_to_pytorch3d)


def camera_mesh_from_baked(mesh, local_to_camera):
    # The installed to_glb rotates local Z-up vertices to Y-up for GLB.
    # Undo that presentation transform before applying its predicted pose.
    y_to_z=np.eye(4)
    y_to_z[:3,:3]=[[1,0,0],[0,0,-1],[0,1,0]]
    result=mesh.copy()
    result.apply_transform(np.asarray(local_to_camera) @ y_to_z)
    return result


def main():
    # Native texture rasterization builds with ninja/nvcc from this model env.
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')
    import torch
    from PIL import Image
    from pic2sim.workers.common import finish,load_request,worker_arguments
    from pic2sim.workers.sam3d import load_official_inference,asset_contract,completed_asset,tensor_list,camera_mesh
    from spatialforge.gaussian_asset import save_gaussian
    from pic2sim.io import write_json_atomic
    args=worker_arguments();request=load_request(args)
    output_dir=Path(request['output_dir']);output_dir.mkdir(parents=True,exist_ok=True)
    inference=load_official_inference(Path(request['source_root']))(request['config_path'],compile=False)
    from spatialforge.source_camera import record_source_camera
    source_camera={}
    inference._pipeline.depth_model=record_source_camera(inference._pipeline.depth_model,source_camera)
    from sam3d_objects.utils.visualization import SceneVisualizer
    from sam3d_objects.model.backbone.tdfy_dit.utils import postprocessing_utils
    from spatialforge.sam3d_texture_baking import bake_texture_fast
    installed_bake=postprocessing_utils.bake_texture
    def bake_texture(*args,**kwargs):
        if kwargs.get('mode')=='fast':return bake_texture_fast(*args,**kwargs)
        return installed_bake(*args,**kwargs)
    # This worker process alone uses paired masks; the shared backend is intact.
    postprocessing_utils.bake_texture=bake_texture
    baking=bool(request.get('texture_baking'))
    settings={'with_mesh_postprocess':False,'with_texture_baking':baking,'use_vertex_color':not baking,
              'rendering_engine':inference._pipeline.rendering_engine,
              'texture_size':int(os.environ.get('SAM3D_TEXTURE_SIZE','512')),
              'bake_resolution':int(os.environ.get('SAM3D_TEXTURE_RESOLUTION','512')),
              'bake_views':int(os.environ.get('SAM3D_TEXTURE_VIEWS','64')),
              'bake_mode':os.environ.get('SAM3D_TEXTURE_MODE','fast'),
              'fast_bake_adapter':'utils3d_top_down_mask_v2',
              'texture_rasterizer':'nvdiffrast_cuda'}
    assets=[]
    for index,item in enumerate(request['objects']):
        seed=int(item.get('seed',int(request.get('seed',42))+index))
        path=output_dir/(item['object_id']+'.glb')
        contract={**asset_contract(item,request,seed),'texture_baking':settings,'paired_gaussian':True,
                  'camera_coordinates':'opencv_right_down_forward_v1'}
        recovered=completed_asset(path,contract)
        if recovered is not None and (output_dir/recovered['gaussian']).is_file():
            assets.append(recovered)
            continue
        image=np.asarray(Image.open(item['image']).convert('RGB'))
        mask=np.asarray(Image.open(item['mask']).convert('L'))>=128
        source_camera.clear()
        if baking:
            output=inference._pipeline.run(inference.merge_mask_to_rgba(image,mask),None,seed,
                stage1_only=False,with_mesh_postprocess=False,with_texture_baking=True,
                with_layout_postprocess=True,use_vertex_color=False,stage1_inference_steps=None,pointmap=None)
        else:output=inference(image,mask,seed=seed)
        basis=torch.tensor([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],dtype=torch.float32,device=output['rotation'].device)
        points=SceneVisualizer.object_pointcloud(basis.unsqueeze(0),output['rotation'],
            output['translation'],output['scale']).points_list()[0].detach().float().cpu().numpy()
        transform=np.eye(4);transform[:3,3]=points[0];transform[:3,:3]=(points[1:]-points[0]).T
        mesh=camera_mesh_from_baked(output['glb'],transform) if baking else camera_mesh(output)
        mesh,transform=opencv_camera_output(mesh,transform)
        temporary=path.with_name('.'+path.stem+'.part.glb');mesh.export(temporary);os.replace(temporary,path)
        gaussian_path=path.with_suffix('.gaussian.npz')
        save_gaussian(output,gaussian_path,transform)
        asset={'object_id':item['object_id'],'asset':path.name,
               'rotation_wxyz':tensor_list(output['rotation']),'translation':tensor_list(output['translation']),
               'scale':tensor_list(output['scale']),'layout_iou':float(output.get('iou',-1.0)),
               'gaussian':gaussian_path.name,'default_render_representation':'gaussian',
               'appearance':{'encoding':'baked_texture' if baking else 'vertex_color','settings':settings,
                             'source':'SAM3D paired Gaussian and mesh; optional baked mesh color, not measured PBR'},
               'local_to_camera':transform.tolist(),'source_frame':'sam3d_camera',
               'camera_coordinates':'opencv_right_down_forward_v1',
               'predicted_pose_coordinates':'pytorch3d_left_up_forward'}
        if source_camera:asset['source_camera']=dict(source_camera)
        assets.append(asset)
        write_json_atomic(path.with_suffix('.complete.json'),{'contract':contract,'asset':asset})
        write_json_atomic(output_dir/'partial_assets.json',{'assets':assets})
    finish(args,assets=assets)


if __name__=='__main__':main()
