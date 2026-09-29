from __future__ import annotations

import importlib.util
import os
import sys
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .common import finish, load_request, require_file, worker_arguments
from ..io import write_json_atomic


def load_official_inference(source_root: Path):
    notebook = source_root / "notebook" / "inference.py"
    require_file(str(notebook), "SAM3D inference module")
    os.environ.setdefault("LIDRA_SKIP_INIT", "true")
    os.environ.setdefault("CONDA_PREFIX", str(Path(sys.executable).parents[1]))
    for path in (notebook.parent, source_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location("pic2sim_sam3d_official", notebook)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load SAM3D inference module: {notebook}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Inference


def camera_mesh(output):
    import torch
    import trimesh
    from sam3d_objects.utils.visualization import SceneVisualizer

    raw = output["mesh"][0]
    source = trimesh.Trimesh(
        vertices=raw.vertices.detach().float().cpu().numpy(),
        faces=raw.faces.detach().cpu().numpy(),
        process=False,
    )
    if getattr(raw, "vertex_attrs", None) is not None:
        colors = raw.vertex_attrs[:, :3].detach().float().clamp(0, 1).cpu().numpy()
        source.visual.vertex_colors = np.column_stack(
            (np.round(colors * 255).astype(np.uint8), np.full(len(colors), 255, dtype=np.uint8))
        )
    cloud = SceneVisualizer.object_pointcloud(
        points_local=torch.from_numpy(np.asarray(source.vertices)).float().cuda().unsqueeze(0),
        quat_l2c=output["rotation"],
        trans_l2c=output["translation"],
        scale_l2c=output["scale"],
    )
    source.vertices = cloud.points_list()[0].detach().float().cpu().numpy()
    return source


def tensor_list(value) -> list:
    return value.detach().float().cpu().tolist()


def asset_contract(item, request, seed):
    sources = {}
    for key in ('image','mask'):
        path = require_file(item[key],key)
        stat = path.stat()
        sources[key] = [str(path),stat.st_size,stat.st_mtime_ns]
    return {'sources':sources, 'seed':seed,
            'source_root':str(Path(request['source_root']).resolve()),
            'config_path':str(Path(request['config_path']).resolve())}


def completed_asset(path, contract):
    try:
        import trimesh
        record=json.loads(path.with_suffix('.complete.json').read_text())
        if record['contract'] != contract:
            return None
        mesh=trimesh.load(path,force='mesh')
        if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
            return None
        return record['asset']
    except (OSError,ValueError,KeyError,AttributeError):
        return None


def main() -> None:
    arguments = worker_arguments()
    request = load_request(arguments)
    source_root = Path(request["source_root"]).resolve()
    config_path = require_file(request["config_path"], "SAM3D configuration")
    output_dir = Path(request["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    from .common import cached_model
    inference = cached_model(('sam3d', str(source_root), str(config_path)),
        lambda: load_official_inference(source_root)(str(config_path), compile=False))
    if request.get('_prewarm'):
        finish(arguments, prewarmed=True)
        return

    assets = []
    for index, item in enumerate(request["objects"]):
        image_path = require_file(item["image"], "object source image")
        mask_path = require_file(item["mask"], "object mask")
        seed=int(item.get('seed', int(request.get('seed',42))+index))
        asset_name=f"{item['object_id']}.glb"
        if Path(asset_name).name != asset_name or '\\' in asset_name:
            raise ValueError('SAM3D object identity is not a safe filename')
        path=output_dir/asset_name
        contract=asset_contract(item,request,seed)
        recovered=completed_asset(path,contract)
        if recovered is not None:
            assets.append(recovered)
            write_json_atomic(output_dir/'partial_assets.json',{'assets':assets})
            continue
        image = np.asarray(Image.open(image_path).convert("RGB"))
        mask = np.asarray(Image.open(mask_path).convert("L")) >= 128
        output = inference(image, mask, seed=seed)
        mesh = camera_mesh(output)
        temporary=path.with_name('.'+path.stem+'.part.glb')
        mesh.export(temporary)
        os.replace(temporary,path)
        assets.append(
            {
                "object_id": item["object_id"],
                "asset": asset_name,
                "rotation_wxyz": tensor_list(output["rotation"]),
                "translation": tensor_list(output["translation"]),
                "scale": tensor_list(output["scale"]),
                "layout_iou": float(output.get("iou", -1.0)),
            }
        )
        write_json_atomic(path.with_suffix('.complete.json'),{'contract':contract,'asset':assets[-1]})
        write_json_atomic(output_dir/'partial_assets.json', {'assets':assets})
    finish(arguments, assets=assets)


if __name__ == "__main__":
    main()
