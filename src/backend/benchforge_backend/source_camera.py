"""Record predicted source-camera intrinsics without altering depth inference."""
import math
import numpy as np


def source_camera_metadata(intrinsics, image_size):
    """MoGe K uses image-normalized coordinates; dimensions are width, height."""
    width, height = image_size
    matrix = np.asarray(intrinsics, dtype=np.float64)
    pixels = np.diag([width, height, 1]) @ matrix
    return {
        'intrinsics_normalized': matrix.tolist(),
        'intrinsics_pixels': pixels.tolist(),
        'image_size': [width, height],
        'horizontal_fov_deg': math.degrees(2 * math.atan(0.5 / matrix[0, 0])),
        'vertical_fov_deg': math.degrees(2 * math.atan(0.5 / matrix[1, 1])),
        'camera_coordinates': 'opencv_right_down_forward',
        'source': 'MoGe depth-model output used by SAM3D',
        'authority': 'predicted camera intrinsics; not measured calibration or GT',
        'gt_source': False,
    }


def record_source_camera(depth_model, record):
    """Wrap the existing worker-local callable; return its exact output object."""
    def infer(image):
        result = depth_model(image)
        record.clear()
        if result.get('intrinsics') is not None:
            height, width = image.shape[-2:]
            record.update(source_camera_metadata(result['intrinsics'].detach().float().cpu().tolist(),
                                                 [width, height]))
        return result
    return infer
