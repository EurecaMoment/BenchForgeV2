"""SAM3D fast baking with each view's aligned raster and observation masks."""
import numpy as np


def view_samples(raster_uv, raster_mask, observation, observation_mask, texture_size):
    # utils3d leaves UV bottom-up, but already flips its mask to top-down.
    # Gaussian observations use the same top-down orientation as that mask.
    uv=raster_uv.flip(0)
    visible=raster_mask.bool() & observation_mask.bool()
    pixels=(uv[visible]*texture_size).floor().long().clamp(0,texture_size-1)
    indices=pixels[:,0]+(texture_size-1-pixels[:,1])*texture_size
    return indices,observation[visible]


def bake_texture_fast(vertices,faces,uvs,observations,masks,extrinsics,intrinsics,
        texture_size=2048,near=.1,far=10.,**options):
    import cv2
    import torch
    import utils3d
    device=options.get('device','cuda')
    vertices=torch.as_tensor(vertices,device=device)
    faces=torch.as_tensor(faces.astype(np.int32),device=device)
    uvs=torch.as_tensor(uvs,device=device)
    colors=torch.zeros((texture_size*texture_size,3),device=device)
    weights=torch.zeros(texture_size*texture_size,device=device)
    context=utils3d.torch.RastContext(backend='cuda')
    with torch.no_grad():
        for observation,mask,extrinsic,intrinsic in zip(observations,masks,extrinsics,intrinsics):
            observation=torch.as_tensor(observation,device=device).float()/255
            mask=torch.as_tensor(mask,device=device)>0
            view=utils3d.torch.extrinsics_to_view(torch.as_tensor(extrinsic,device=device))
            projection=utils3d.torch.intrinsics_to_perspective(torch.as_tensor(intrinsic,device=device),near,far)
            raster=utils3d.torch.rasterize_triangle_faces(context,vertices[None],faces,
                observation.shape[1],observation.shape[0],uv=uvs[None],view=view,projection=projection)
            indices,samples=view_samples(raster['uv'][0],raster['mask'][0],observation,mask,texture_size)
            colors.scatter_add_(0,indices[:,None].expand(-1,3),samples)
            weights.scatter_add_(0,indices,torch.ones(len(indices),device=device))
        observed=weights>0
        colors[observed]/=weights[observed,None]
        texture=(colors.reshape(texture_size,texture_size,3).clamp(0,1)*255).byte().cpu().numpy()
        missing=(~observed).reshape(texture_size,texture_size).byte().cpu().numpy()
    return cv2.inpaint(texture,missing,3,cv2.INPAINT_TELEA)
