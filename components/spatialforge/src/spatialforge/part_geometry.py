"""Analytic composite part geometry, shared by the contract and preview."""
import math


def rotation_matrix(angles):
    x,y,z=map(math.radians,angles)
    cx,cy,cz=math.cos(x),math.cos(y),math.cos(z)
    sx,sy,sz=math.sin(x),math.sin(y),math.sin(z)
    # Column vectors: X, then Y, then Z (USD rotateXYZ).
    return ((cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx),
            (sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx),
            (-sy,cy*sx,cy*cx))


def part_bounds(part):
    """Exact AABB of a rotated box, ellipsoid or elliptical Z-cylinder."""
    rotation=rotation_matrix(part.get('rotation_deg_xyz',[0,0,0]))
    radii=[v/2 for v in part['size']]
    shape=part.get('shape')
    extents=[]
    for row in rotation:
        scaled=[row[i]*radii[i] for i in range(3)]
        if shape=='box':extent=sum(abs(v) for v in scaled)
        elif shape=='sphere':extent=math.sqrt(sum(v*v for v in scaled))
        elif shape=='cylinder':extent=math.hypot(*scaled[:2])+abs(scaled[2])
        else:raise ValueError('unsupported part shape')
        extents.append(extent)
    return ([part['offset'][i]-extents[i] for i in range(3)],
            [part['offset'][i]+extents[i] for i in range(3)])


def horizontal_box_top(part):
    """Return an actual horizontal top face; a tilted box may have none."""
    rotation=rotation_matrix(part.get('rotation_deg_xyz',[0,0,0]))
    for axis in range(3):
        if abs(abs(rotation[2][axis])-1)>1e-8:continue
        u,v=[i for i in range(3) if i!=axis]
        return {'center':[*part['offset'][:2],part['offset'][2]+part['size'][axis]/2],
                'size_xy':[part['size'][u],part['size'][v]],
                'yaw_deg':math.degrees(math.atan2(rotation[1][u],rotation[0][u]))}
    return None
