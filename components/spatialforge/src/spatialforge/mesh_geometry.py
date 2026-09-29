"""Pure mesh transform shared by planning previews and the desktop executor."""
import math

def transform_mesh_normals(normals, transform):
    """Apply the inverse transpose, preserving authored directions under scaling."""
    import numpy as np
    transformed = np.asarray(normals, dtype=np.float64) @ np.linalg.inv(np.asarray(transform)[:3, :3])
    return transformed / np.linalg.norm(transformed, axis=1, keepdims=True)

def _number(value,lo,hi,name):
    if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
        raise ValueError('invalid '+name)
    return float(value)

def transform_mesh_geometry(vertices, requested_size, coordinate_frame, mesh_transform=None):
    """Preserve source shape with explicit rotation and a single scale factor.

    Size is an enclosing box limit. No axis or gravity orientation is inferred
    from appearance, PCA, or a bounding box. Face/UV/material arrays are untouched.
    """
    import numpy as np
    vertices=np.asarray(vertices,dtype=np.float64)
    requested=np.asarray(requested_size,dtype=np.float64)
    if vertices.ndim!=2 or vertices.shape[1]!=3 or not len(vertices) or not np.isfinite(vertices).all():
        raise ValueError('invalid generated vertices')
    if requested.shape!=(3,) or not np.isfinite(requested).all() or (requested<=0).any():
        raise ValueError('invalid mesh size limits')
    transform=mesh_transform or {}
    if not isinstance(transform,dict) or set(transform)-{'orientation_deg_xyz','scale_mode'}:
        raise ValueError('invalid mesh_transform')
    if transform.get('scale_mode','uniform_fit')!='uniform_fit':raise ValueError('mesh scale_mode must be uniform_fit')
    angles=transform.get('orientation_deg_xyz',[0,0,0])
    if not isinstance(angles,list) or len(angles)!=3:raise ValueError('invalid mesh orientation')
    angles=[_number(v,-360,360,'mesh orientation') for v in angles]
    if coordinate_frame=='sam3d_camera':basis=np.array([[1,0,0],[0,0,1],[0,-1,0]],dtype=np.float64)
    elif coordinate_frame=='z_up':basis=np.eye(3)
    else:raise ValueError('unsupported generated mesh coordinate frame')
    x,y,z=np.radians(angles);cx,cy,cz=np.cos([x,y,z]);sx,sy,sz=np.sin([x,y,z])
    rx=np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
    ry=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
    rz=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
    rotation=rz@ry@rx@basis
    oriented=vertices@rotation.T
    lo=oriented.min(axis=0);hi=oriented.max(axis=0);extent=hi-lo
    if (extent<=1e-8).any():raise ValueError('degenerate generated mesh bounds')
    scale=float(np.min(requested/extent));mid=(lo+hi)/2
    transformed=(oriented-mid)*scale;actual=extent*scale
    transform_matrix=np.eye(4);transform_matrix[:3,:3]=rotation*scale;transform_matrix[:3,3]=-mid*scale
    return transformed,{
        'scale_mode':'uniform_fit','normalization':'explicit rigid rotation, centered, uniformly scaled inside requested meter bounds',
        'normalization_scale_xyz':[scale]*3,'uniform_scale':scale,
        'requested_size_limits_m':requested.tolist(),'actual_size_m':actual.tolist(),
        'source_bounds':[vertices.min(axis=0).tolist(),vertices.max(axis=0).tolist()],
        'oriented_bounds_before_scale':[lo.tolist(),hi.tolist()],
        'orientation_deg_xyz':angles,'orientation_order':'source basis then X then Y then Z; scene yaw applied afterwards',
        'orientation_source':'explicit_declaration' if 'orientation_deg_xyz' in transform else 'coordinate_frame_basis_only',
        'T_local_from_source':transform_matrix.tolist(),'shape_preserved':True,
        'gravity_alignment':'unmeasured' if coordinate_frame=='sam3d_camera' else 'declared_z_up',
    }
