"""Independent Depth Anything V2 Small inference with uncalibrated output."""
import argparse
import json
import os
from pathlib import Path
import sys


MODEL_ID = 'depth-anything/Depth-Anything-V2-Small'
DEFAULT_SOURCE = 'third_party/Depth-Anything-V2'


def run(request):
    # Explicit CPU calls must not use the official helper's automatic CUDA choice.
    if request.get('device') == 'cpu':
        os.environ['CUDA_VISIBLE_DEVICES'] = ''

    import cv2
    import numpy as np
    import torch

    source_root = Path(request.get('source_root') or os.environ.get('SPATIALFORGE_DEPTH_SOURCE', DEFAULT_SOURCE)).resolve()
    sys.path.insert(0, str(source_root))
    from depth_anything_v2.dpt import DepthAnythingV2

    checkpoint = Path(request['model_path']).resolve()
    if checkpoint.is_dir():
        checkpoint = checkpoint / 'depth_anything_v2_vits.pth'
    output_dir = Path(request['output_dir']).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = Path(request['image']).resolve()
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f'Cannot read source image: {image_path}')

    device = request.get('device') or ('cuda' if torch.cuda.is_available() else 'cpu')
    if device == 'cpu':
        torch.set_num_threads(int(request.get('cpu_threads', 4)))
        # The installed xFormers kernels require CUDA; V2 already has a CPU branch.
        from depth_anything_v2.dinov2_layers import attention
        attention.XFORMERS_AVAILABLE = False
    model = DepthAnythingV2(encoder='vits', features=64, out_channels=[48, 96, 192, 384])
    model.load_state_dict(torch.load(str(checkpoint), map_location='cpu', weights_only=True))
    model = model.to(device).eval()
    input_size = int(request.get('input_size', 518))
    depth = model.infer_image(image, input_size=input_size).astype(np.float32)

    depth_path = output_dir / 'depth.npy'
    visualization_path = output_dir / 'depth_visualization.png'
    np.save(depth_path, depth)
    low, high = float(depth.min()), float(depth.max())
    preview = np.zeros(depth.shape, dtype=np.uint8) if high == low else np.round((depth - low) * 255 / (high - low)).astype(np.uint8)
    if not cv2.imwrite(str(visualization_path), cv2.applyColorMap(preview, cv2.COLORMAP_INFERNO)):
        raise OSError(f'Cannot write depth visualization: {visualization_path}')
    result = {
        'status': 'ok',
        'image': str(image_path),
        'depth': str(depth_path),
        'visualization': str(visualization_path),
        'shape': list(depth.shape),
        'depth_type': 'relative_inverse_depth',
        'units': 'arbitrary',
        'scale': 'uncalibrated; larger values indicate nearer surfaces',
        'gt_source': False,
        'range': [low, high],
        'device': device,
        'input_size': input_size,
        'model': {
            'id': MODEL_ID,
            'checkpoint': str(checkpoint),
            'source_root': str(source_root),
            'official_url': f'https://huggingface.co/{MODEL_ID}',
        },
    }
    (output_dir / 'depth_metadata.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    parser.add_argument('--response', required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    result = run(request)
    Path(args.response).write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
