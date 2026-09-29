"""On-demand FLUX.2 Klein generation/editing with the installed diffusion runtime."""
import argparse
import json
from pathlib import Path


def load_pipeline_class():
    # BenchForge's runtime has a flash_attn/xformers version conflict. Diffusers'
    # supported torch SDPA path avoids importing that unused optional backend.
    import sys
    sys.modules['xformers'] = None
    import diffusers.utils.import_utils as import_utils
    import_utils._xformers_available = False
    from diffusers import Flux2KleinPipeline
    return Flux2KleinPipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    parser.add_argument('--response', required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    pipeline_class = load_pipeline_class()
    import torch
    from PIL import Image
    pipeline = pipeline_class.from_pretrained(request['model_path'], torch_dtype=torch.bfloat16, local_files_only=True)
    pipeline.enable_model_cpu_offload()
    pipeline.vae.enable_tiling()
    kwargs = {'prompt': request['prompt'], 'height': request.get('height', 768), 'width': request.get('width', 768),
              'num_inference_steps': request.get('steps', 4), 'guidance_scale': 1.,
              'generator': torch.Generator('cpu').manual_seed(request.get('seed', 42))}
    if request.get('image'):
        with Image.open(request['image']) as reference:
            kwargs['image'] = reference.convert('RGB')
    output = pipeline(**kwargs).images[0]
    destination = Path(request['output'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + '.part.png')
    output.save(temporary, format='PNG')
    temporary.replace(destination)
    response = Path(args.response)
    response.parent.mkdir(parents=True, exist_ok=True)
    temporary = response.with_suffix('.part.json')
    temporary.write_text(json.dumps({'status': 'ok', 'output': str(destination), 'model': Path(request['model_path']).name, 'size': list(output.size)}), encoding='utf-8')
    temporary.replace(response)


if __name__ == '__main__':
    main()
