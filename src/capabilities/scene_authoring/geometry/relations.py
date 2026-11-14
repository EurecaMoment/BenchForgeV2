"""Conservative spatial checks using executed primitive geometry and poses."""
import math
from itertools import product

from capabilities.scene_authoring.geometry.parts import part_bounds
from capabilities.scene_authoring.geometry.parts import horizontal_box_top


def native_part_bounds(entity, *, support_only=False):
    geometry = entity.get('geometry_parts', {})
    matrix = entity.get('world_transform')
    if (geometry.get('source') != 'executed_primitive_construction' or
            geometry.get('coordinate_frame') != 'entity_local_meters' or
            not isinstance(matrix, list) or len(matrix) != 4 or
            any(not isinstance(row, list) or len(row) != 4 for row in matrix) or
            not all(isinstance(v, (int, float)) and math.isfinite(v) for row in matrix for v in row)):
        return []
    boxes = []
    try:
        for part in geometry.get('parts', []):
            if not part.get('prim_path'):return []
            if support_only and (part.get('shape') != 'box' or horizontal_box_top(part) is None or
                                 any(abs(matrix[i][2]) > 1e-6 or abs(matrix[2][i]) > 1e-6 for i in (0, 1))):
                continue
            lo, hi = part_bounds(part)
            points = [[sum(point[i] * matrix[i][axis] for i in range(3)) + matrix[3][axis]
                       for axis in range(3)] for point in product(*zip(lo, hi))]
            boxes.append(([min(p[i] for p in points) for i in range(3)],
                          [max(p[i] for p in points) for i in range(3)]))
    except (ValueError, KeyError, TypeError, IndexError):return []
    return boxes


def supported_by_parts(child, parts, gap=.04):
    lo, hi = child
    return any(abs(lo[2] - top[2]) <= gap and all(lo[i] >= bottom[i] - .02 and hi[i] <= top[i] + .02 for i in (0, 1))
               for bottom, top in parts)


def supported_by_native_parts(child, entity):
    """Executed box tops and upright elliptical cylinder tops can carry props.

    Cylinder corners must fit the actual ellipse, not its bounding square.
    Tilted surfaces remain unresolved rather than pretending to be horizontal.
    """
    geometry=entity.get('geometry_parts',{})
    if geometry.get('source')!='executed_primitive_construction' or geometry.get('coordinate_frame')!='entity_local_meters':return False
    if supported_by_parts(child,native_part_bounds(entity,support_only=True)):return True
    import numpy as np
    matrix=np.asarray(entity.get('world_transform',[]),dtype=float)
    if matrix.shape!=(4,4) or not np.isfinite(matrix).all():return False
    if any(abs(matrix[i][2])>1e-6 or abs(matrix[2][i])>1e-6 for i in (0,1)):return False
    try:inverse=np.linalg.inv(matrix)
    except np.linalg.LinAlgError:return False
    lo,hi=child
    for part in entity.get('geometry_parts',{}).get('parts',[]):
        if part.get('shape')!='cylinder' or not part.get('prim_path'):continue
        rotation=part.get('rotation_deg_xyz',[0,0,0])
        if any(abs(math.sin(math.radians(a)))>1e-6 for a in rotation[:2]):continue
        size=part['size'];offset=part['offset'];top=offset[2]+size[2]/2
        world_top=(np.array([offset[0],offset[1],top,1.])@matrix)[2]
        if abs(lo[2]-world_top)>.04:continue
        angle=math.radians(rotation[2]);c,s=math.cos(angle),math.sin(angle)
        contained=True
        for x,y in product(*zip(lo[:2],hi[:2])):
            point=np.array([x,y,lo[2],1.])@inverse
            dx,dy=point[0]-offset[0],point[1]-offset[1]
            px,py=c*dx+s*dy,-s*dx+c*dy
            if (px/(size[0]/2+.002))**2+(py/(size[1]/2+.002))**2>1:contained=False;break
        if contained:return True
    return False


def overlap_unresolved(left, right):
    return any(all(min(b[k], d[k]) - max(a[k], c[k]) > .02 for k in range(3))
               for a, b in left for c, d in right)


def transported_mesh_bounds(entity, dependency, mesh):
    """Tight source-vertex bounds under the measured final native transform.

    This can rule out overlap from an empty rotated AABB corner. It cannot
    establish contact forces or resolve intersecting mesh bounds.
    """
    import numpy as np
    if (dependency.get('embedded_geometry') is not True or dependency.get('shape_preserved') is not True or
            dependency.get('entity_id')!=entity.get('id') or dependency.get('render_representation')!='mesh' or
            entity.get('world_transform_convention')!='USD row-vector matrix; translation in last row; local to world meters'):
        return None
    vertices=np.asarray(mesh.get('vertices'),dtype=float)
    local=np.asarray(dependency.get('T_local_from_source'),dtype=float)
    world=np.asarray(entity.get('world_transform'),dtype=float)
    if (vertices.ndim!=2 or vertices.shape[1]!=3 or len(vertices)!=dependency.get('vertices') or
            local.shape!=(4,4) or world.shape!=(4,4) or
            not all(np.isfinite(v).all() for v in (vertices,local,world))):return None
    source=np.array([vertices.min(axis=0),vertices.max(axis=0)])
    if not np.allclose(source,np.asarray(dependency.get('source_bounds')),atol=1e-7):return None
    points=(vertices@local[:3,:3].T+local[:3,3])@world[:3,:3]+world[3,:3]
    return (points.min(axis=0).tolist(),points.max(axis=0).tolist())
