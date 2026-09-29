"""Authored camera pose and optics for the persistent render camera."""
from scene_runtime import camera_up


def resolved_up(spec):
    return spec['up'] if 'up' in spec else camera_up(spec['position'], spec['target'])


def camera_matrix(spec):
    from pxr import Gf
    return Gf.Matrix4d().SetLookAt(Gf.Vec3d(*spec['position']), Gf.Vec3d(*spec['target']),
                                  Gf.Vec3d(*resolved_up(spec))).GetInverse()


def apply_camera_optics(camera, spec):
    # Set defaults for each view so a previous view's zoom cannot leak forward.
    camera.CreateFocalLengthAttr().Set(spec.get('focal_length_mm', 24))
    camera.CreateHorizontalApertureAttr().Set(spec.get('horizontal_aperture_mm', 36))


def camera_evidence(camera, spec, matrix):
    return {'position': spec['position'], 'target': spec['target'], 'up': resolved_up(spec),
            'T_world_camera_usd': [list(row) for row in matrix],
            'convention': 'USD camera -Z forward +Y up',
            'focal_length_mm': camera.GetFocalLengthAttr().Get(),
            'horizontal_aperture_mm': camera.GetHorizontalApertureAttr().Get()}
