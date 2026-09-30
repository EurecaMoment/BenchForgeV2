"""Bounded RGB readiness check without advancing simulation or changing a camera."""
import numpy as np


def instance_region(instance, prim_path, image_shape):
    """Use case-preserving simulator instance paths, not lowercased class labels."""
    masks=np.asarray(instance['data'])
    masks=masks.view(np.uint32).reshape(image_shape) if masks.dtype==np.uint8 else masks.squeeze()
    labels=[int(key) for key,path in instance['info']['idToLabels'].items()
            if path==prim_path or path.startswith(prim_path+'/')]
    return np.isin(masks,labels)


def object_visibility(instance, object_id, prim_path, image_shape):
    """Report target pixels from the same simulator instance frame as RGB."""
    ys,xs=np.where(instance_region(instance,prim_path,image_shape))
    return {'object_id':object_id,'visible_pixels':int(len(xs)),
            'bbox_xyxy':[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)] if len(xs) else None}


def read_rgb_bounded(read, render_step, expected_shape, on_rejected, max_attempts=3, reinitialize=None, render_steps=5):
    attempts=[];rgb=None;reinitialized=False
    for attempt in range(max_attempts):
        for _ in range(render_steps):render_step()
        raw=np.asarray(read())
        shape_ok=raw.ndim==3 and raw.shape[:2]==tuple(expected_shape) and raw.shape[2]>=3
        rgb=raw[:,:,:3].copy() if shape_ok else None
        valid=rgb is not None and bool(np.any(rgb))
        diagnostics={'attempt':attempt+1,'shape':list(raw.shape),'nonzero_rgb':valid,
                     'reason':None if valid else 'all_zero_rgb' if shape_ok else 'invalid_rgb_shape'}
        if rgb is not None:
            diagnostics.update(rgb_min=int(rgb.min()),rgb_max=int(rgb.max()),rgb_std=float(rgb.std()))
        attempts.append(diagnostics)
        if valid:break
        if attempt==0:
            on_rejected(rgb,diagnostics)
            if reinitialize is not None and max_attempts>1:
                reinitialize();reinitialized=True
    return rgb,{'valid_rgb':attempts[-1]['nonzero_rgb'],'attempts':attempts,
                'simulation_advanced':False,'final_camera_changed':False,
                'render_reinitialized':reinitialized,'max_attempts':max_attempts,'render_steps_per_attempt':render_steps}
