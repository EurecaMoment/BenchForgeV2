"""SAM3D activated Gaussian payloads paired with their source mesh."""
import math
from pathlib import Path
import shutil

import numpy as np


def save_gaussian(output, path, local_to_source):
    gaussian = output['gaussian'][0]
    arrays = {name: getattr(gaussian, prop).detach().float().cpu().numpy()
              for name, prop in {'positions': 'get_xyz', 'scales': 'get_scaling',
                                 'orientations': 'get_rotation', 'opacities': 'get_opacity',
                                 'features': 'get_features'}.items()}
    np.savez_compressed(path, **arrays, local_to_source=local_to_source)


def register_gaussian(source, destination, source_frame):
    """Keep local splats intact; record the same source-frame conversion as mesh_export."""
    with np.load(source, allow_pickle=False) as data:
        count = len(data['positions'])
        coefficients = data['features'].shape[1]
        degree = math.isqrt(coefficients) - 1
        if (count == 0 or data['positions'].shape != (count, 3)
                or data['scales'].shape != (count, 3)
                or data['orientations'].shape != (count, 4)
                or data['opacities'].size != count
                or data['features'].shape != (count, coefficients, 3)
                or (degree + 1) ** 2 != coefficients):
            raise ValueError('Gaussian NPZ needs matching activated positions/scales/wxyz/opacities/SH arrays')
        local_to_source = data['local_to_source'] if 'local_to_source' in data else np.eye(4)
        basis = np.eye(4)
        if source_frame == 'y_up':
            basis[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
        transform = basis @ local_to_source
    shutil.copy2(source, destination)
    return {'file': Path(destination).name, 'count': count, 'sh_degree': degree,
            'T_mesh_from_gaussian': transform.tolist(),
            'representation': 'ParticleField3DGaussianSplat',
            'appearance': 'SAM3D radiance; source illumination retained, not relightable PBR',
            'physics': 'paired mesh', 'default_render_representation': 'gaussian'}


def render_representation(object_record, mesh_record):
    choice = object_record.get('render_representation', 'auto')
    if choice == 'auto':
        return 'gaussian' if mesh_record.get('gaussian') else 'mesh'
    if choice == 'gaussian' and not mesh_record.get('gaussian'):
        raise ValueError('asset has no Gaussian payload; import the paired Gaussian or select mesh rendering')
    return choice
