"""Optional SceneProgram placement from SAM3D's predicted camera-space geometry."""
import math

import numpy as np

from .mesh_geometry import transform_mesh_geometry


def camera_layout_placement(mesh, meters_per_unit, camera_position, orientation_deg_xyz=None):
    """Return placement fields without editing an asset or scene.

    Use the same scale, camera position and rotation for objects reconstructed
    from the same image. This preserves their predicted relative geometry,
    including its errors; it does not infer metric scale or camera intrinsics.
    The scene rotation follows the usual source-basis, X, Y, Z order.
    """
    if mesh['coordinate_frame'] != 'sam3d_camera':
        raise ValueError('camera layout needs sam3d_camera source geometry')
    scale = float(meters_per_unit)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('meters_per_unit must be positive and finite')
    origin = np.asarray(camera_position, dtype=np.float64)
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError('camera_position must contain three finite coordinates')
    pose = {'orientation_deg_xyz': list(orientation_deg_xyz or [0, 0, 0]),
            'scale_mode': 'uniform_fit'}
    _, probe = transform_mesh_geometry(mesh['vertices'], [1, 1, 1], 'sam3d_camera', pose)
    lo, hi = np.asarray(probe['oriented_bounds_before_scale'])
    size = (hi - lo) * scale
    center = (lo + hi) * (scale / 2) + origin
    rotation = np.asarray(probe['T_local_from_source'])[:3, :3] / probe['uniform_scale']
    source_to_world = np.eye(4)
    source_to_world[:3, :3] = rotation * scale
    source_to_world[:3, 3] = origin
    return {
        'placement': {'size': size.tolist(), 'xy': center[:2].tolist(),
                      'base_z': float(lo[2] * scale + origin[2]),
                      'support': 'ground', 'yaw_deg': 0, 'mesh_transform': pose},
        'camera_pose': {'position': origin.tolist(),
                        'target': (origin + rotation[:, 2]).tolist(),
                        'up': (-rotation[:, 1]).tolist()},
        'T_world_from_source': source_to_world.tolist(),
        'meters_per_unit': scale,
        'authority': 'SAM3D prediction with caller-selected scale and camera pose; not GT',
        'limits': 'Preserves source layout errors. Focal length, gravity, occluded geometry and physical contact are not inferred.',
    }
