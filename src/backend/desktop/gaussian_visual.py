"""Embed a native Gaussian visual alongside its normalized mesh collider."""
import numpy as np
from pxr import Gf, Sdf, UsdGeom, Vt


def define_gaussian_visual(stage, parent, payload, metadata, normalization):
    data = np.load(payload, allow_pickle=False)
    transform = (np.asarray(normalization['T_local_from_source'])
                 @ np.asarray(metadata['T_mesh_from_gaussian']))
    node = UsdGeom.Xform.Define(stage, parent + '/GaussianNormalization')
    UsdGeom.Xformable(node).AddTransformOp().Set(Gf.Matrix4d(transform.T.tolist()))
    prim = stage.DefinePrim(str(node.GetPath()) + '/Gaussian', 'ParticleField3DGaussianSplat')
    for name, kind in [('positions', Sdf.ValueTypeNames.Point3fArray), ('scales', Sdf.ValueTypeNames.Float3Array)]:
        prim.CreateAttribute(name, kind).Set(Vt.Vec3fArray.FromNumpy(data[name].astype('float32')))
    quaternions = [Gf.Quatf(float(q[0]), Gf.Vec3f(*map(float, q[1:]))) for q in data['orientations']]
    prim.CreateAttribute('orientations', Sdf.ValueTypeNames.QuatfArray).Set(Vt.QuatfArray(quaternions))
    prim.CreateAttribute('opacities', Sdf.ValueTypeNames.FloatArray).Set(Vt.FloatArray.FromNumpy(data['opacities'].reshape(-1).astype('float32')))
    prim.CreateAttribute('radiance:sphericalHarmonicsDegree', Sdf.ValueTypeNames.Int).Set(metadata['sh_degree'])
    sh = prim.CreateAttribute('radiance:sphericalHarmonicsCoefficients', Sdf.ValueTypeNames.Float3Array)
    sh.Set(Vt.Vec3fArray.FromNumpy(data['features'].reshape(-1, 3).astype('float32')))
    variable = UsdGeom.Primvar(sh)
    variable.SetElementSize(data['features'].shape[1]); variable.SetInterpolation('vertex')
    radius = 3 * data['scales'].max(axis=1)[:, None]
    extent = np.stack([(data['positions']-radius).min(axis=0), (data['positions']+radius).max(axis=0)])
    prim.CreateAttribute('extent', Sdf.ValueTypeNames.Float3Array).Set(Vt.Vec3fArray.FromNumpy(extent.astype('float32')))
    data.close()
    return {**metadata, 'prim_path': str(prim.GetPath()), 'embedded': True,
            'T_entity_from_gaussian': transform.tolist(),
            'collision_prim_path': parent + '/Geometry', 'collision_visibility': 'invisible'}
