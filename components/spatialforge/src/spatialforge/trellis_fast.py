"""Lower-quality latency profile, explicitly distinct from full reconstruction."""
import time


FAST_PROFILE = {'name': 'fast10', 'pipeline': '512_coarse', 'geometry_resolution': 512,
    'sampling_steps': 6, 'target_triangles': 50000, 'texture_size': 1024,
    'remesh': False, 'uv_mode': 'triangle_atlas', 'texture_padding': 'dilate',
    'material_field_resolution': 128, 'surface_reprojection': False,
    'texture_checkpoint': 'slat_flow_imgshape2tex_dit_1_3B_1024_bf16',
    'texture_checkpoint_reused_on_coarse_grid': True, 'quality_tradeoff': True}


def run_fast(pipeline, image, seed, steps=4, check=None):
    """Use the installed 512 shape and 1024 material checkpoints on a coarse grid.

    This adaptation is recorded in provenance. It is not an official 512 texture
    checkpoint or a promise of quality equivalence to the 1024 cascade.
    """
    import torch
    timings = {}
    stage_started = time.perf_counter()

    def mark(name):
        nonlocal stage_started
        torch.cuda.synchronize()
        now = time.perf_counter()
        timings[name] = now - stage_started
        stage_started = now
        if check is not None:
            check()

    with torch.inference_mode():
        image = pipeline.preprocess_image(image)
        torch.manual_seed(seed)
        cond = pipeline.get_cond([image], 512)
        mark('image_condition_seconds')
        coords = pipeline.sample_sparse_structure(cond, 32, 1, {'steps': steps})
        mark('sparse_structure_seconds')
        shape = pipeline.sample_shape_slat(cond, pipeline.models['shape_slat_flow_model_512'],
            coords, {'steps': steps})
        mark('shape_sampling_seconds')
        texture = pipeline.sample_tex_slat(cond, pipeline.models['tex_slat_flow_model_1024'],
            shape, {'steps': steps})
        mark('texture_sampling_seconds')
        mesh = pipeline.decode_latent(shape, texture, 512)[0]
        mark('decode_seconds')
    return mesh, timings
