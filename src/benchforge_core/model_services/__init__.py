"""Independent HTTP clients; model loading belongs to external inference services."""
CLIENTS = {
    "yoloe": "yoloe", "sam3": "sam3", "moge": "moge", "lama": "lama",
    "flux_fill": "flux", "osor_flux_fill": "osor_flux",
    "objectclear_fill": "objectclear", "qwen_image_edit": "qwen_image_edit",
    "diffusion": "diffusion", "depth_anything": "depth_anything", "sam3d": "sam3d",
    "blender": "blender",
}
MODEL_TOOLS = ["model_" + name for name in CLIENTS]
