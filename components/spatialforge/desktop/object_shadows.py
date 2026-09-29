"""Author native RTX shadow visibility without changing appearance or collision geometry."""
from pxr import Sdf, Usd, UsdGeom


def apply_object_shadows(root, cast_shadows=None):
    receipts=[]
    for prim in Usd.PrimRange(root):
        gaussian=prim.GetTypeName()=='ParticleField3DGaussianSplat'
        if not gaussian and (cast_shadows is None or not prim.IsA(UsdGeom.Gprim)):
            continue
        enabled=True if cast_shadows is None else cast_shadows
        attr=UsdGeom.PrimvarsAPI(prim).CreatePrimvar('doNotCastShadows',Sdf.ValueTypeNames.Bool,UsdGeom.Tokens.constant)
        attr.Set(not enabled)
        receipts.append({'prim_path':str(prim.GetPath()),'casts_shadows':not attr.Get(),
                         'source':'paired_gaussian_default' if cast_shadows is None else 'explicit_object_setting'})
    return receipts
