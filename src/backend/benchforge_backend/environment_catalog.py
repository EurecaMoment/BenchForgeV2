"""Trusted environment maps; production proposals select IDs, never file paths."""
from pathlib import Path


ENVIRONMENTS={
    'clear_day_sky':{
        'path':'Materials/Textures/Skies/PolyHaven/kloofendal_43d_clear_puresky_4k.hdr',
        'root':'isaac','texture_format':'latlong',
        'description':'Clear daylight HDR sky, no buildings or terrain',
        'source':'Poly Haven sky supplied in the installed NVIDIA Isaac asset library',
        'calibration':'appearance and lighting prior; no site-specific illumination calibration',
    },
}


def apply_environment_texture(light, environment_id, asset_root, direction=None):
    from pxr import Gf, Sdf, UsdGeom
    record=ENVIRONMENTS[environment_id]
    path=Path(asset_root)/record['path']
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('Registered environment texture is missing: '+environment_id)
    light.CreateTextureFileAttr(Sdf.AssetPath(path.as_posix()))
    light.CreateTextureFormatAttr(record['texture_format'])
    light.OrientToStageUpAxis()
    if direction is not None:
        xform=UsdGeom.Xformable(light)
        base_ops=xform.GetOrderedXformOps()
        down=Gf.Vec3d(0,-1,0) if UsdGeom.GetStageUpAxis(light.GetPrim().GetStage())=='Y' else Gf.Vec3d(0,0,-1)
        rotation=Gf.Rotation(down,Gf.Vec3d(*direction).GetNormalized())
        orient=xform.AddOrientOp(opSuffix='environmentDirection')
        orient.Set(Gf.Quatf(rotation.GetQuat()))
        # Apply the requested world tilt after the texture's native up-axis conversion.
        xform.SetXformOpOrder([orient,*base_ops])
    return {'light_path':str(light.GetPath()),'environment_id':environment_id,
            'texture_path':path.as_posix(),'texture_format':record['texture_format'],
            'orientation':'stage_up_axis' if direction is None else 'explicit_world_nadir',
            'direction':list(direction) if direction is not None else None,
            'direction_meaning':'world direction of the HDR lower pole; does not specify a sun light direction',
            'source':record['source'],
            'calibration':record['calibration']}
