#!/usr/bin/env python3
import argparse
import contextlib
import json
import os
import sys
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHCLAW_ROOT = os.environ.get(
    "BENCHCLAW_ROOT", os.path.abspath(os.path.join(SERVICE_DIR, "..", ".."))
)
BENCHCLAW_PARENT = os.path.abspath(os.path.join(BENCHCLAW_ROOT, ".."))
THIRD_PARTY_ROOT = os.environ.get(
    "THIRD_PARTY_ROOT", os.path.join(BENCHCLAW_PARENT, "thirty_part")
)
SAM3_REPO = os.environ.get(
    "SAM3_REPO", os.path.join(THIRD_PARTY_ROOT, "annotationTools", "sam3")
)
DEFAULT_CHECKPOINT = os.environ.get(
    "SAM3_CHECKPOINT", ""
)

if SAM3_REPO not in sys.path:
    sys.path.insert(0, SAM3_REPO)


IMAGE_MODEL_RUNTIMES = {}
IMAGE_SESSIONS = {}
VIDEO_PREDICTORS = {}
MODEL_LOCK = threading.RLock()
IMAGE_REQUEST_LOCK = threading.RLock()
VIDEO_REQUEST_LOCK = threading.RLock()


def _json_response(handler, payload, status=HTTPStatus.OK):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler):
    content_length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(content_length) if content_length else b"{}"
    return json.loads(raw.decode("utf-8-sig"))


def _to_serializable(value):
    import numpy as np
    import torch

    if isinstance(value, dict):
        return {str(k): _to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(v) for v in value]
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _autocast_context(device):
    import torch

    if str(device).startswith("cuda"):
        return torch.autocast(device_type="cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()


def _save_mask_images(masks, save_dir):
    from pathlib import Path

    import numpy as np
    import torch
    from PIL import Image

    if not save_dir:
        return []

    Path(save_dir).mkdir(parents=True, exist_ok=True)
    masks_cpu = masks.detach().cpu() if isinstance(masks, torch.Tensor) else masks
    if (
        isinstance(masks_cpu, torch.Tensor)
        and masks_cpu.ndim == 4
        and masks_cpu.shape[1] == 1
    ):
        masks_cpu = masks_cpu[:, 0]

    saved_paths = []
    for idx, mask in enumerate(masks_cpu):
        mask_arr = mask.numpy() if hasattr(mask, "numpy") else np.asarray(mask)
        mask_bin = (mask_arr > 0.5).astype("uint8") * 255
        out_path = Path(save_dir) / f"mask_{idx:03d}.png"
        Image.fromarray(mask_bin).convert("L").save(out_path)
        saved_paths.append(str(out_path))
    return saved_paths


def _build_image_runtime(checkpoint_path=DEFAULT_CHECKPOINT):
    import torch

    from sam3.model_builder import build_sam3_image_model

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    model = build_sam3_image_model(
        checkpoint_path=checkpoint_path,
        load_from_HF=False,
        device=device,
        eval_mode=True,
    )
    model = model.to(device).float().eval()
    return {"device": device, "checkpoint_path": checkpoint_path, "model": model}


def _get_image_runtime(checkpoint_path=DEFAULT_CHECKPOINT):
    key = checkpoint_path or DEFAULT_CHECKPOINT
    with MODEL_LOCK:
        runtime = IMAGE_MODEL_RUNTIMES.get(key)
        if runtime is None:
            runtime = _build_image_runtime(checkpoint_path=key)
            IMAGE_MODEL_RUNTIMES[key] = runtime
        return runtime


def _serialize_current_image_state(
    state, image_size=None, save_masks_dir=None, include_logits=False
):
    import torch
    from sam3.model.box_ops import box_xyxy_to_xywh
    from sam3.train.masks_ops import rle_encode

    response = {}
    if image_size is None and "original_width" in state and "original_height" in state:
        image_size = (state["original_width"], state["original_height"])

    if image_size is not None:
        response["orig_img_w"] = image_size[0]
        response["orig_img_h"] = image_size[1]

    if (
        "boxes" in state
        and "scores" in state
        and "masks" in state
        and image_size is not None
    ):
        orig_img_w, orig_img_h = image_size
        if len(state["boxes"]) > 0:
            pred_boxes_xyxy = torch.stack(
                [
                    state["boxes"][:, 0] / orig_img_w,
                    state["boxes"][:, 1] / orig_img_h,
                    state["boxes"][:, 2] / orig_img_w,
                    state["boxes"][:, 3] / orig_img_h,
                ],
                dim=-1,
            )
            response["pred_boxes"] = box_xyxy_to_xywh(pred_boxes_xyxy).tolist()
        else:
            response["pred_boxes"] = []
        response["pred_masks"] = [
            item["counts"] for item in rle_encode(state["masks"].squeeze(1))
        ]
        response["pred_scores"] = state["scores"].tolist()
        response["boxes_xyxy"] = _to_serializable(state["boxes"])
        response["saved_mask_paths"] = _save_mask_images(state["masks"], save_masks_dir)
        if include_logits and "masks_logits" in state:
            response["masks_logits"] = _to_serializable(state["masks_logits"])
        elif "masks_logits" in state:
            response["masks_logits_shape"] = list(state["masks_logits"].shape)

    return response


def _create_image_session(payload):
    from sam3.model.sam3_image_processor import Sam3Processor

    checkpoint_path = payload.get("checkpoint_path") or DEFAULT_CHECKPOINT
    confidence_threshold = float(payload.get("confidence_threshold", 0.2))
    runtime = _get_image_runtime(checkpoint_path=checkpoint_path)
    processor = Sam3Processor(
        runtime["model"],
        device=runtime["device"],
        confidence_threshold=confidence_threshold,
    )
    session_id = payload.get("session_id") or str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "runtime": runtime,
        "processor": processor,
        "state": {},
        "image_path": None,
    }
    IMAGE_SESSIONS[session_id] = session
    if payload.get("image_path"):
        _image_set_image(session, payload["image_path"])
    return session


def _get_image_session(session_id):
    session = IMAGE_SESSIONS.get(session_id)
    if session is None:
        raise RuntimeError(f"Cannot find image session {session_id}")
    return session


def _image_set_image(session, image_path):
    from PIL import Image

    abs_image_path = os.path.abspath(image_path)
    image = Image.open(abs_image_path).convert("RGB")
    with _autocast_context(session["runtime"]["device"]):
        session["state"] = session["processor"].set_image(image, state={})
    session["image_path"] = abs_image_path
    return image


def _serialize_image_session(session, save_masks_dir=None, include_logits=False):
    image_size = None
    if (
        session.get("state")
        and "original_width" in session["state"]
        and "original_height" in session["state"]
    ):
        image_size = (
            session["state"]["original_width"],
            session["state"]["original_height"],
        )
    payload = {
        "session_id": session["session_id"],
        "image_path": session.get("image_path"),
        "checkpoint_path": session["runtime"]["checkpoint_path"],
        "service_device": session["runtime"]["device"],
        "confidence_threshold": session["processor"].confidence_threshold,
        "has_backbone_out": "backbone_out" in session["state"],
        "has_text_prompt": "language_features"
        in session["state"].get("backbone_out", {}),
        "has_geometric_prompt": "geometric_prompt" in session["state"],
    }
    payload.update(
        _serialize_current_image_state(
            session["state"],
            image_size=image_size,
            save_masks_dir=save_masks_dir,
            include_logits=include_logits,
        )
    )
    return payload


def _serialize_predict_inst_result(result):
    if isinstance(result, tuple):
        return [_to_serializable(item) for item in result]
    return _to_serializable(result)


def _image_request(payload):
    request = payload["request"]
    request_type = request["type"]

    if request_type == "start_session":
        session = _create_image_session(request)
        return _serialize_image_session(
            session,
            save_masks_dir=request.get("save_masks_dir"),
            include_logits=bool(request.get("include_logits", False)),
        )

    if request_type == "predict_inst_batch":
        from PIL import Image
        from sam3.model.sam3_image_processor import Sam3Processor

        checkpoint_path = request.get("checkpoint_path") or DEFAULT_CHECKPOINT
        runtime = _get_image_runtime(checkpoint_path=checkpoint_path)
        processor = Sam3Processor(
            runtime["model"],
            device=runtime["device"],
            confidence_threshold=float(request.get("confidence_threshold", 0.2)),
        )
        images = [
            Image.open(os.path.abspath(path)).convert("RGB")
            for path in request["image_paths"]
        ]
        with _autocast_context(runtime["device"]):
            state = processor.set_image_batch(images, state={})
            result = runtime["model"].predict_inst_batch(
                state, **request.get("kwargs", {})
            )
        return {
            "checkpoint_path": runtime["checkpoint_path"],
            "service_device": runtime["device"],
            "result": _serialize_predict_inst_result(result),
        }

    session = _get_image_session(request["session_id"])
    processor = session["processor"]
    state = session["state"]

    if request_type == "set_image":
        _image_set_image(session, request["image_path"])
    elif request_type == "set_text_prompt":
        with _autocast_context(session["runtime"]["device"]):
            session["state"] = processor.set_text_prompt(request["prompt"], state)
    elif request_type == "add_geometric_prompt":
        with _autocast_context(session["runtime"]["device"]):
            session["state"] = processor.add_geometric_prompt(
                box=request["box"],
                label=bool(request.get("label", True)),
                state=state,
            )
    elif request_type == "add_geometric_prompts":
        with _autocast_context(session["runtime"]["device"]):
            for prompt_item in request.get("prompts", []):
                session["state"] = processor.add_geometric_prompt(
                    box=prompt_item["box"],
                    label=bool(prompt_item.get("label", True)),
                    state=session["state"],
                )
    elif request_type == "set_confidence_threshold":
        with _autocast_context(session["runtime"]["device"]):
            session["state"] = processor.set_confidence_threshold(
                float(request["threshold"]), state=session["state"]
            )
    elif request_type == "reset_all_prompts":
        processor.reset_all_prompts(session["state"])
    elif request_type == "predict_inst":
        with _autocast_context(session["runtime"]["device"]):
            result = session["runtime"]["model"].predict_inst(
                session["state"], **request.get("kwargs", {})
            )
        return {
            "session_id": session["session_id"],
            "checkpoint_path": session["runtime"]["checkpoint_path"],
            "service_device": session["runtime"]["device"],
            "result": _serialize_predict_inst_result(result),
        }
    elif request_type == "get_state":
        pass
    elif request_type == "close_session":
        IMAGE_SESSIONS.pop(session["session_id"], None)
        return {"session_id": session["session_id"], "is_success": True}
    else:
        raise RuntimeError(f"invalid image request type: {request_type}")

    return _serialize_image_session(
        session,
        save_masks_dir=request.get("save_masks_dir"),
        include_logits=bool(request.get("include_logits", False)),
    )


def _image_infer(payload):
    request = {
        "type": "start_session",
        "image_path": payload["image_path"],
        "checkpoint_path": payload.get("checkpoint_path"),
        "confidence_threshold": payload.get("confidence_threshold", 0.2),
        "save_masks_dir": payload.get("save_masks_dir"),
        "include_logits": bool(payload.get("include_logits", False)),
    }
    session_payload = _image_request({"request": request})
    session_id = session_payload["session_id"]

    try:
        if payload.get("text_prompt"):
            session_payload = _image_request(
                {
                    "request": {
                        "type": "set_text_prompt",
                        "session_id": session_id,
                        "prompt": payload["text_prompt"],
                    }
                }
            )
        if payload.get("box_prompts"):
            session_payload = _image_request(
                {
                    "request": {
                        "type": "add_geometric_prompts",
                        "session_id": session_id,
                        "prompts": payload.get("box_prompts", []),
                        "save_masks_dir": payload.get("save_masks_dir"),
                        "include_logits": bool(payload.get("include_logits", False)),
                    }
                }
            )
        return session_payload
    finally:
        IMAGE_SESSIONS.pop(session_id, None)


def _get_video_predictor(version, checkpoint_path=None, compile_model=False):
    from sam3 import build_sam3_predictor

    key = (version, checkpoint_path or DEFAULT_CHECKPOINT, bool(compile_model))
    with MODEL_LOCK:
        predictor = VIDEO_PREDICTORS.get(key)
        if predictor is None:
            kwargs = {
                "version": version,
                "compile": bool(compile_model),
                "async_loading_frames": False,
            }
            if checkpoint_path:
                kwargs["checkpoint_path"] = checkpoint_path
            predictor = build_sam3_predictor(**kwargs)
            VIDEO_PREDICTORS[key] = predictor
        return predictor


def _video_request(payload):
    version = payload.get("version", "sam3.1")
    predictor = _get_video_predictor(
        version=version,
        checkpoint_path=payload.get("checkpoint_path"),
        compile_model=payload.get("compile", False),
    )
    request = payload["request"]

    if payload.get("stream", False):
        outputs = []
        for item in predictor.handle_stream_request(request):
            outputs.append(_to_serializable(item))
        return {"stream": True, "items": outputs, "version": version}

    response = predictor.handle_request(request)
    return {"stream": False, "response": _to_serializable(response), "version": version}


class Sam3Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            payload = {
                "ok": True,
                "service": "sam3-local",
                "image_runtime_loaded": bool(IMAGE_MODEL_RUNTIMES),
                "image_session_count": len(IMAGE_SESSIONS),
                "video_predictor_count": len(VIDEO_PREDICTORS),
            }
            return _json_response(self, payload)
        return _json_response(
            self, {"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND
        )

    def do_POST(self):
        try:
            payload = _read_json(self)
            if self.path == "/image/infer":
                with IMAGE_REQUEST_LOCK:
                    return _json_response(
                        self, {"ok": True, "result": _image_infer(payload)}
                    )
            if self.path == "/image/request":
                with IMAGE_REQUEST_LOCK:
                    return _json_response(
                        self, {"ok": True, "result": _image_request(payload)}
                    )
            if self.path == "/video/request":
                with VIDEO_REQUEST_LOCK:
                    return _json_response(
                        self, {"ok": True, "result": _video_request(payload)}
                    )
            return _json_response(
                self, {"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND
            )
        except Exception as exc:
            return _json_response(
                self,
                {"ok": False, "error": str(exc), "type": exc.__class__.__name__},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format_str, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Sam3Handler)
    print(f"SAM3 local service listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
