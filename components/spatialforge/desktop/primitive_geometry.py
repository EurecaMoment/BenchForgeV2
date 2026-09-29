"""Explicit UV meshes for the SceneProgram analytic shapes."""
import math

from scene_runtime import box_mesh_with_metric_uv

UV_MAPPINGS = {
    'box': 'six planar faces; meters per texture repeat',
    'cylinder': 'elliptical side arc and height; planar caps; meters per repeat',
    'sphere': 'equatorial arc and XZ meridian; equirectangular with pole distortion',
}


def _arc_lengths(points):
    lengths = [0.]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    return lengths


def primitive_mesh_with_uv(kind, size, uv_scale_m):
    """Curves use 96 longitude segments and 48 sphere latitude intervals.

    Arc lengths follow the sampled ellipse, so noncircular cylinders retain
    metric repeats. Sphere U/V lengths are measured at equator/XZ meridian;
    equirectangular UVs necessarily compress the pattern near the poles.
    """
    if kind == 'box':
        return {**box_mesh_with_metric_uv(size, uv_scale_m), 'normals_interpolation': 'uniform'}
    rx, ry, rz = [v / 2 for v in size]
    su, sv = uv_scale_m
    segments = 96
    ring = [(rx * math.cos(2 * math.pi * i / segments),
             ry * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    arc = _arc_lengths(ring + ring[:1])
    points, counts, indices, normals, st = [], [], [], [], []

    def face(vertices, uvs, directions):
        counts.append(len(vertices))
        indices.extend(vertices)
        st.extend(uvs)
        normals.extend(directions)

    def normal(x, y, z):
        vector = (x / rx**2, y / ry**2, z / rz**2)
        length = math.sqrt(sum(v*v for v in vector))
        return tuple(v / length for v in vector)

    if kind == 'cylinder':
        points = [(x, y, z) for z in (-rz, rz) for x, y in ring]
        bottom, top = len(points), len(points) + 1
        points.extend([(0, 0, -rz), (0, 0, rz)])
        for i in range(segments):
            j = (i + 1) % segments
            n0 = normal(*ring[i], 0)
            n1 = normal(*ring[j], 0)
            u0, u1 = arc[i] / su, arc[i+1] / su
            face([i, j, j+segments, i+segments],
                 [(u0, 0), (u1, 0), (u1, size[2]/sv), (u0, size[2]/sv)],
                 [n0, n1, n1, n0])
            for vertices, nz in (([bottom, j, i], -1), ([top, i+segments, j+segments], 1)):
                face(vertices, [((points[k][0]+rx)/su, nz*(points[k][1]+ry)/sv) for k in vertices],
                     [(0, 0, nz)] * 3)
    elif kind == 'sphere':
        latitudes = 48
        phi = [-math.pi/2 + math.pi*j/latitudes for j in range(latitudes+1)]
        meridian = _arc_lengths([(rx*math.cos(p), rz*math.sin(p)) for p in phi])
        points = [(0, 0, -rz)]
        for p in phi[1:-1]:
            points.extend([(x*math.cos(p), y*math.cos(p), rz*math.sin(p)) for x, y in ring])
        north = len(points)
        points.append((0, 0, rz))

        def vertex(j, i):
            return 1 + (j-1)*segments + i % segments

        for j in range(latitudes):
            v0, v1 = meridian[j]/sv, meridian[j+1]/sv
            for i in range(segments):
                u0, u1 = arc[i]/su, arc[i+1]/su
                if j == 0:
                    vertices = [0, vertex(1, i+1), vertex(1, i)]
                    uvs = [((u0+u1)/2, v0), (u1, v1), (u0, v1)]
                elif j == latitudes-1:
                    vertices = [vertex(j, i), vertex(j, i+1), north]
                    uvs = [(u0, v0), (u1, v0), ((u0+u1)/2, v1)]
                else:
                    vertices = [vertex(j, i), vertex(j, i+1), vertex(j+1, i+1), vertex(j+1, i)]
                    uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
                face(vertices, uvs, [normal(*points[k]) for k in vertices])
    else:
        raise ValueError('unsupported textured primitive: ' + kind)
    return {'points': points, 'face_vertex_counts': counts, 'face_vertex_indices': indices,
            'normals': normals, 'normals_interpolation': 'faceVarying', 'st': st}


def define_textured_primitive(stage, path, kind, size, color, uv_scale_m, offset=(0, 0, 0), rotation_deg_xyz=(0, 0, 0)):
    from pxr import Gf, Sdf, UsdGeom, UsdPhysics
    data = primitive_mesh_with_uv(kind, size, uv_scale_m)
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in data['points']])
    mesh.CreateFaceVertexCountsAttr(data['face_vertex_counts'])
    mesh.CreateFaceVertexIndicesAttr(data['face_vertex_indices'])
    mesh.CreateNormalsAttr([Gf.Vec3f(*n) for n in data['normals']])
    mesh.SetNormalsInterpolation(data['normals_interpolation'])
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    mesh.CreateExtentAttr([Gf.Vec3f(*[-v/2 for v in size]), Gf.Vec3f(*[v/2 for v in size])])
    st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.Float2Array, UsdGeom.Tokens.faceVarying)
    st.Set([Gf.Vec2f(*uv) for uv in data['st']])
    mesh.GetPrim().SetCustomDataByKey('spatialforge_uv_mapping', UV_MAPPINGS[kind])
    if any(offset):
        UsdGeom.Xformable(mesh).AddTranslateOp().Set(Gf.Vec3d(*offset))
    if any(rotation_deg_xyz):
        UsdGeom.Xformable(mesh).AddRotateXYZOp().Set(Gf.Vec3f(*rotation_deg_xyz))
    if kind == 'box':
        # A visual texture must not replace the analytic box contact surface.
        # Inherit this mesh's local offset/rotation; scale only the collider.
        collider = UsdGeom.Cube.Define(stage, path+'/Collision')
        collider.CreateSizeAttr(1.)
        collider.AddScaleOp().Set(Gf.Vec3f(*size))
        collider.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
        UsdPhysics.CollisionAPI.Apply(collider.GetPrim())
    else:
        UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr('convexHull')
    return mesh
