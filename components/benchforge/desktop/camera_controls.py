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


import math

class PublicScaleError(ValueError):
    pass


def _vec(values, size):
    if len(values) != size:
        raise PublicScaleError("Wrong vector or matrix shape")
    result = [float(x) for x in values]
    if not all(math.isfinite(x) for x in result):
        raise PublicScaleError("Non-finite camera calibration")
    return result


def _close(a, b, tolerance=1e-5):
    return all(abs(x-y) <= tolerance for x, y in zip(a, b))


def intrinsics(camera, width, height):
    """Use recorded K, or complete recorded optics and readout conform policy."""
    candidate = camera.get("K") or camera.get("intrinsic_matrix")
    nested = camera.get("intrinsics")
    if candidate is None and isinstance(nested, dict):
        candidate = nested.get("K") or nested.get("matrix")
    if candidate is not None:
        if len(candidate) == 9 and not isinstance(candidate[0], (list, tuple)):
            candidate = [candidate[:3], candidate[3:6], candidate[6:]]
        result = [_vec(row, 3) for row in candidate]
        if len(result) != 3 or not _close(result[2], [0, 0, 1]):
            raise PublicScaleError("Invalid captured K")
        if result[0][0] <= 0 or result[1][1] <= 0:
            raise PublicScaleError("Non-positive captured focal length")
        if abs(result[0][1]) > 1e-8 or abs(result[1][0]) > 1e-8:
            raise PublicScaleError("This helper requires captured zero-skew pinhole K")
        return result, "captured_intrinsic_matrix"
    required = ["focal_length_mm", "horizontal_aperture_mm", "vertical_aperture_mm",
                "horizontal_aperture_offset_mm", "vertical_aperture_offset_mm",
                "pixel_aspect_ratio", "aspect_ratio_conform_policy", "projection"]
    missing = [name for name in required if name not in camera]
    if missing:
        raise PublicScaleError("Capture omitted K or readout calibration: " + ", ".join(missing))
    if camera["projection"] != "perspective":
        raise PublicScaleError("This public pack requires a captured perspective camera")
    focal, ha, va, pixel_aspect = [float(camera[k]) for k in required[:3]+["pixel_aspect_ratio"]]
    if not all(math.isfinite(x) and x > 0 for x in (focal, ha, va, pixel_aspect)):
        raise PublicScaleError("Invalid captured optical parameters")
    aspect = width * pixel_aspect / height
    policy = camera["aspect_ratio_conform_policy"]
    if policy == "expandAperture":
        if ha / va > aspect: va = ha / aspect
        else: ha = va * aspect
    elif policy == "cropAperture":
        if ha / va > aspect: ha = va * aspect
        else: va = ha / aspect
    elif policy == "adjustApertureWidth": ha = va * aspect
    elif policy == "adjustApertureHeight": va = ha / aspect
    elif policy != "adjustPixelAspectRatio":
        raise PublicScaleError("Unrecorded or unsupported readout conform policy")
    ho = float(camera["horizontal_aperture_offset_mm"])
    vo = float(camera["vertical_aperture_offset_mm"])
    if not all(math.isfinite(x) for x in (ho, vo)):
        raise PublicScaleError("Invalid aperture offset")
    return [[width*focal/ha, 0, width/2-width*ho/ha],
            [0, height*focal/va, height/2+height*vo/va], [0, 0, 1]], "captured_optics_and_readout"


def native_camera_readout(camera, render_product):
    # Portable source contract: read the camera and its own live product in the
    # caller's stage. Do not substitute a viewport, another frame, a saved final
    # camera, or installation-specific paths. Keep this call before product cleanup.
    from pxr import UsdRender, UsdGeom
    prim = camera.GetPrim()
    stage = prim.GetStage()
    product_path = render_product if isinstance(render_product, str) else str(render_product.path)
    product = UsdRender.Product.Get(stage, product_path)
    if not product or not product.GetPrim().IsValid():
        raise ValueError("Camera calibration requires the actual live RenderProduct")
    camera_targets = product.GetCameraRel().GetTargets()
    if len(camera_targets) != 1 or camera_targets[0] != prim.GetPath():
        raise ValueError("RenderProduct camera does not match the captured view")
    resolution = product.GetResolutionAttr().Get()
    width, height = int(resolution[0]), int(resolution[1])
    if min(width, height) <= 0:
        raise ValueError("Invalid actual RenderProduct resolution")
    metadata = {
        "schema": "benchforge.native-camera-readout/v1",
        "projection": str(camera.GetProjectionAttr().Get()),
        "focal_length_mm": float(camera.GetFocalLengthAttr().Get()),
        "horizontal_aperture_mm": float(camera.GetHorizontalApertureAttr().Get()),
        "vertical_aperture_mm": float(camera.GetVerticalApertureAttr().Get()),
        "horizontal_aperture_offset_mm": float(camera.GetHorizontalApertureOffsetAttr().Get()),
        "vertical_aperture_offset_mm": float(camera.GetVerticalApertureOffsetAttr().Get()),
        "pixel_aspect_ratio": float(product.GetPixelAspectRatioAttr().Get()),
        "aspect_ratio_conform_policy": str(product.GetAspectRatioConformPolicyAttr().Get()),
        "render_product_resolution": {"width": width, "height": height},
        "meters_per_scene_unit": float(UsdGeom.GetStageMetersPerUnit(stage)),
        "matrix_layout": "usd_row_vectors",
        "calibration_source": "same live UsdGeomCamera and UsdRenderProduct",
        "camera_path": str(prim.GetPath()),
        "render_product_path": product_path,
        "pixel_coordinates": "upper-left pixel boundary is (0,0); pixel centers are (u+0.5,v+0.5)",
        "pixel_center_offset_px": [.5, .5],
    }
    matrix, basis = intrinsics(metadata, width, height)
    metadata["K"] = matrix
    metadata["K_basis"] = basis
    return metadata


def camera_evidence(camera, spec, matrix, render_product=None):
    result = {'position': spec['position'], 'target': spec['target'], 'up': resolved_up(spec),
              'T_world_camera_usd': [list(row) for row in matrix],
              'convention': 'USD camera -Z forward +Y up', 'matrix_layout': 'usd_row_vectors',
              'projection': str(camera.GetProjectionAttr().Get()),
              'focal_length_mm': float(camera.GetFocalLengthAttr().Get()),
              'horizontal_aperture_mm': float(camera.GetHorizontalApertureAttr().Get()),
              'vertical_aperture_mm': float(camera.GetVerticalApertureAttr().Get()),
              'horizontal_aperture_offset_mm': float(camera.GetHorizontalApertureOffsetAttr().Get()),
              'vertical_aperture_offset_mm': float(camera.GetVerticalApertureOffsetAttr().Get())}
    if render_product is not None:
        result.update(native_camera_readout(camera, render_product))
    return result
