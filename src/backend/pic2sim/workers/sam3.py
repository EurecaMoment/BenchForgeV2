from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .common import finish, load_request, require_file, worker_arguments


def _clip_and_pad_box(
    box: list[float], image_size: tuple[int, int], padding_ratio: float
) -> list[float]:
    width, height = image_size
    x1, y1, x2, y2 = (float(value) for value in box)
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    padding_x = (x2 - x1) * padding_ratio
    padding_y = (y2 - y1) * padding_ratio
    return [
        max(0.0, x1 - padding_x),
        max(0.0, y1 - padding_y),
        min(float(width), x2 + padding_x),
        min(float(height), y2 + padding_y),
    ]


def _xyxy_to_normalized_cxcywh(box: list[float], image_size: tuple[int, int]) -> list[float]:
    width, height = image_size
    x1, y1, x2, y2 = box
    return [
        (x1 + x2) / (2.0 * width),
        (y1 + y2) / (2.0 * height),
        (x2 - x1) / width,
        (y2 - y1) / height,
    ]


def _box_iou(left: list[float], right: list[float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _result_rank(prompt_box: list[float], result_box: list[float], score: float) -> float:
    center_x = (prompt_box[0] + prompt_box[2]) / 2.0
    center_y = (prompt_box[1] + prompt_box[3]) / 2.0
    center_inside = (
        result_box[0] <= center_x <= result_box[2]
        and result_box[1] <= center_y <= result_box[3]
    )
    return score + 0.35 * _box_iou(prompt_box, result_box) + (0.10 if center_inside else 0.0)


def main() -> None:
    arguments = worker_arguments()
    request = load_request(arguments)
    checkpoint = require_file(request["checkpoint"], "SAM3 checkpoint")
    output_dir = Path(request["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model

    from .common import cached_model
    model = cached_model(('sam3', str(checkpoint)), lambda: build_sam3_image_model(
        checkpoint_path=str(checkpoint), load_from_HF=False, device="cuda", eval_mode=True
    ))
    processor = Sam3Processor(model, confidence_threshold=float(request.get("confidence", 0.25)))
    if request.get('_prewarm'):
        finish(arguments, prewarmed=True)
        return
    image_path = require_file(request['image'], 'input image')
    image = Image.open(image_path).convert("RGB")
    segments: list[dict] = []
    serial = 0
    # SAM3's fused MLP emits BF16 while its stored weights remain FP32. Keep the
    # complete image/text forward inside autocast so ordinary layers agree.
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
        state = processor.set_image(image)
        for instance in request.get("instances", []):
            instance_id = int(instance["id"])
            prompt = str(instance.get('segmentation_prompt') or instance["label"]).strip()
            prompt_box = _clip_and_pad_box(
                list(instance["box"]),
                image.size,
                float(request.get("box_padding_ratio", 0.03)),
            )
            processor.reset_all_prompts(state)
            processor.set_text_prompt(prompt=prompt, state=state)
            result = processor.add_geometric_prompt(
                box=_xyxy_to_normalized_cxcywh(prompt_box, image.size),
                label=True,
                state=state,
            )
            ranked = []
            for mask, box, score in zip(
                result.get("masks", []), result.get("boxes", []), result.get("scores", [])
            ):
                result_box = [float(value) for value in box.detach().float().cpu().flatten()]
                result_score = float(score.detach().float().cpu())
                ranked.append(
                    (
                        _result_rank(prompt_box, result_box, result_score),
                        mask,
                        result_box,
                        result_score,
                    )
                )
            if not ranked:
                continue
            ranked.sort(key=lambda item: item[0], reverse=True)
            _, mask, result_box, result_score = ranked[0]
            array = mask.detach().bool().cpu().numpy().squeeze()
            if not array.any():
                continue
            mask_name = f"instance_{instance_id:04d}.png"
            Image.fromarray(np.where(array, 255, 0).astype(np.uint8), mode="L").save(
                output_dir / mask_name
            )
            selection_margin = (
                float(ranked[0][0] - ranked[1][0]) if len(ranked) > 1 else 1.0
            )
            segments.append(
                {
                    "id": instance_id,
                    "instance_id": instance_id,
                    "label": str(instance['label']).strip(),
                    "text_prompt": prompt,
                    "score": result_score,
                    "box": result_box,
                    "prompt_box": prompt_box,
                    "candidate_count": len(ranked),
                    "selection_margin": selection_margin,
                    "mask": mask_name,
                }
            )

        for prompt in request.get("prompts", []):
            processor.reset_all_prompts(state)
            result = processor.set_text_prompt(prompt=prompt, state=state)
            masks = result.get("masks", [])
            boxes = result.get("boxes", [])
            scores = result.get("scores", [])
            for mask, box, score in zip(masks, boxes, scores):
                array = mask.detach().bool().cpu().numpy().squeeze()
                if not array.any():
                    continue
                mask_name = f"mask_{serial:04d}.png"
                Image.fromarray(np.where(array, 255, 0).astype(np.uint8), mode="L").save(output_dir / mask_name)
                segments.append(
                    {
                        "id": serial,
                        "label": prompt,
                        "score": float(score.detach().float().cpu()),
                        "box": [float(value) for value in box.detach().float().cpu().flatten()],
                        "mask": mask_name,
                    }
                )
                serial += 1
    finish(arguments, segments=segments)


if __name__ == "__main__":
    main()
