#!/usr/bin/env python3
import argparse
import contextlib
import json
import os
import sys
import threading
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
YOLOE_REPO = os.environ.get(
    "YOLOE_REPO",
    os.path.join(THIRD_PARTY_ROOT, "annotationTools", "yoloe"),
)
DEFAULT_CHECKPOINT = os.environ.get(
    "YOLOE_CHECKPOINT",
    "CONFIGURE_PATH",
)
DEFAULT_MOBILECLIP = os.environ.get(
    "YOLOE_MOBILECLIP",
    "CONFIGURE_PATH",
)
DEFAULT_PF_CHECKPOINT = os.environ.get(
    "YOLOE_PF_CHECKPOINT",
    "CONFIGURE_PATH",
)
DEFAULT_DEVICE = os.environ.get("YOLOE_DEVICE", "auto")

if YOLOE_REPO not in sys.path:
    sys.path.insert(0, YOLOE_REPO)

os.chdir(YOLOE_REPO)


MODEL_LOCK = threading.RLock()
INFERENCE_LOCK = threading.RLock()


@contextlib.contextmanager
def _pushd(path):
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


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


def _resolve_device(device):
    import torch

    if device and device != "auto":
        return device
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _ensure_mobileclip_link():
    target_path = os.path.join(YOLOE_REPO, "mobileclip_blt.pt")
    if os.path.exists(target_path):
        return target_path
    if os.path.exists(DEFAULT_MOBILECLIP):
        try:
            os.symlink(DEFAULT_MOBILECLIP, target_path)
        except FileExistsError:
            pass
        return target_path
    return target_path


def _build_runtime(checkpoint_path=DEFAULT_CHECKPOINT, device=DEFAULT_DEVICE):
    from ultralytics import YOLOE

    resolved_device = _resolve_device(device)
    _ensure_mobileclip_link()
    model = YOLOE(checkpoint_path)
    model.eval()
    model.to(resolved_device)
    return {
        "checkpoint_path": checkpoint_path,
        "device": resolved_device,
        "model": model,
    }


def _get_runtime(
    checkpoint_path=DEFAULT_CHECKPOINT, device=DEFAULT_DEVICE, role="default"
):
    with MODEL_LOCK:
        # YOLOE mutates class/head/predictor state across text and visual prompt paths.
        # Building an isolated runtime per request is slower but prevents cross-request
        # corruption and threaded state leakage that manifests as shape mismatch 500s.
        return _build_runtime(checkpoint_path=checkpoint_path, device=device)


def _to_builtin(value):
    import numpy as np
    import torch

    if isinstance(value, dict):
        return {str(k): _to_builtin(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(v) for v in value]
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _reset_predict_state(model):
    # YOLOE reuses predictor instances internally. Different modes mutate predictor
    # state, so force a clean predictor per request while keeping weights resident.
    model.predictor = None


def _load_image(path):
    from PIL import Image

    return Image.open(os.path.abspath(path)).convert("RGB")


def _result_to_payload(result):
    result_cpu = result.cpu()
    names = result_cpu.names
    if isinstance(names, list):
        names_map = {str(i): name for i, name in enumerate(names)}
    else:
        names_map = {str(k): v for k, v in names.items()}
    payload = {
        "path": result_cpu.path,
        "orig_shape": list(result_cpu.orig_shape),
        "names": names_map,
        "speed": _to_builtin(result_cpu.speed),
        "num_detections": 0,
        "detections": [],
    }

    boxes = result_cpu.boxes
    masks = result_cpu.masks
    if boxes is None or len(boxes) == 0:
        return payload

    xyxy = boxes.xyxy.tolist()
    xywhn = boxes.xywhn.tolist()
    confs = boxes.conf.tolist()
    classes = boxes.cls.tolist()
    mask_segments = masks.xy if masks is not None else [None] * len(boxes)
    mask_segments_norm = masks.xyn if masks is not None else [None] * len(boxes)

    detections = []
    for idx in range(len(boxes)):
        class_id = int(classes[idx])
        detections.append(
            {
                "index": idx,
                "class_id": class_id,
                "class_name": names[class_id]
                if isinstance(names, list)
                else names.get(class_id, str(class_id)),
                "confidence": float(confs[idx]),
                "box_xyxy": xyxy[idx],
                "box_xywhn": xywhn[idx],
                "segment_xy": _to_builtin(mask_segments[idx])
                if masks is not None
                else None,
                "segment_xyn": _to_builtin(mask_segments_norm[idx])
                if masks is not None
                else None,
            }
        )
    payload["num_detections"] = len(detections)
    payload["detections"] = detections
    return payload


def _save_annotated_image(result, output_path):
    plotted = result.plot()
    from PIL import Image

    Image.fromarray(plotted).save(output_path)
    return output_path


def _run_text_infer(payload):
    runtime = _get_runtime(
        checkpoint_path=payload.get("checkpoint_path") or DEFAULT_CHECKPOINT,
        device=payload.get("device") or DEFAULT_DEVICE,
        role="text",
    )
    names = payload.get("names") or []
    if not names:
        raise RuntimeError("text inference requires non-empty 'names'")
    image = _load_image(payload["image_path"])
    model = runtime["model"]
    _reset_predict_state(model)
    with _pushd(YOLOE_REPO):
        model.set_classes(names, model.get_text_pe(names))
    results = model.predict(
        image,
        imgsz=int(payload.get("imgsz", 640)),
        conf=float(payload.get("conf", 0.25)),
        iou=float(payload.get("iou", 0.7)),
        verbose=False,
    )
    result = results[0]
    response = {
        "mode": "text",
        "checkpoint_path": runtime["checkpoint_path"],
        "service_device": runtime["device"],
        "class_names": names,
        "result": _result_to_payload(result),
    }
    if payload.get("annotated_output_path"):
        out_path = os.path.abspath(payload["annotated_output_path"])
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        response["annotated_output_path"] = _save_annotated_image(result, out_path)
    return response


def _run_prompt_free_infer(payload):
    vocab_runtime = _get_runtime(
        checkpoint_path=payload.get("checkpoint_path") or DEFAULT_CHECKPOINT,
        device=payload.get("device") or DEFAULT_DEVICE,
        role="prompt_free_vocab",
    )
    names = payload.get("names") or []
    if not names:
        raise RuntimeError("prompt-free inference requires non-empty 'names'")
    pf_checkpoint_path = payload.get("pf_checkpoint_path") or DEFAULT_PF_CHECKPOINT
    if not os.path.exists(pf_checkpoint_path):
        raise RuntimeError(
            f"prompt-free checkpoint not found: {pf_checkpoint_path}. "
            f"This mode requires a dedicated *-seg-pf.pt model in addition to the base checkpoint."
        )

    runtime = _get_runtime(
        checkpoint_path=pf_checkpoint_path,
        device=payload.get("device") or DEFAULT_DEVICE,
        role="prompt_free_infer",
    )
    image = _load_image(payload["image_path"])
    model = runtime["model"]
    _reset_predict_state(vocab_runtime["model"])
    _reset_predict_state(model)
    with _pushd(YOLOE_REPO):
        vocab = vocab_runtime["model"].get_vocab(names)
        model.set_vocab(vocab, names=names)
    model.model.model[-1].is_fused = True
    model.model.model[-1].conf = float(payload.get("pf_head_conf", 0.001))
    model.model.model[-1].max_det = int(payload.get("max_det", 1000))
    results = model.predict(
        image,
        imgsz=int(payload.get("imgsz", 640)),
        conf=float(payload.get("conf", 0.25)),
        iou=float(payload.get("iou", 0.7)),
        verbose=False,
    )
    result = results[0]
    response = {
        "mode": "prompt_free",
        "checkpoint_path": runtime["checkpoint_path"],
        "vocab_checkpoint_path": vocab_runtime["checkpoint_path"],
        "service_device": runtime["device"],
        "class_names": names,
        "result": _result_to_payload(result),
    }
    if payload.get("annotated_output_path"):
        out_path = os.path.abspath(payload["annotated_output_path"])
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        response["annotated_output_path"] = _save_annotated_image(result, out_path)
    return response


def _run_visual_infer(payload):
    import numpy as np
    from ultralytics.models.yolo.yoloe.predict_vp import YOLOEVPSegPredictor

    runtime = _get_runtime(
        checkpoint_path=payload.get("checkpoint_path") or DEFAULT_CHECKPOINT,
        device=payload.get("device") or DEFAULT_DEVICE,
        role="visual",
    )
    model = runtime["model"]
    _reset_predict_state(model)
    source_image = os.path.abspath(payload["image_path"])
    target_image = (
        os.path.abspath(payload["target_image_path"])
        if payload.get("target_image_path")
        else None
    )
    prompt_type = payload.get("prompt_type", "bboxes")
    prompt_classes = payload.get("class_names") or ["object0"]

    if prompt_type == "bboxes":
        prompts = {
            "bboxes": np.asarray(payload["bboxes"], dtype=np.float32),
            "cls": np.asarray(
                payload.get("cls", [0] * len(payload["bboxes"])), dtype=np.int64
            ),
        }
    elif prompt_type == "masks":
        prompts = {
            "masks": np.asarray(payload["masks"], dtype=np.uint8),
            "cls": np.asarray(
                payload.get("cls", [0] * len(payload["masks"])), dtype=np.int64
            ),
        }
    else:
        raise RuntimeError(
            "visual inference requires prompt_type in {'bboxes', 'masks'}"
        )

    kwargs = {
        "imgsz": int(payload.get("imgsz", 640)),
        "conf": float(payload.get("conf", 0.25)),
        "iou": float(payload.get("iou", 0.7)),
        "verbose": False,
        "prompts": prompts,
        "predictor": YOLOEVPSegPredictor,
    }

    if target_image:
        model.predict([source_image, target_image], return_vpe=True, **kwargs)
        model.set_classes(prompt_classes, model.predictor.vpe)
        model.predictor = None
        results = model.predict(
            target_image,
            imgsz=kwargs["imgsz"],
            conf=kwargs["conf"],
            iou=kwargs["iou"],
            verbose=False,
        )
    else:
        results = model.predict(source_image, **kwargs)

    result = results[0]
    response = {
        "mode": "visual",
        "checkpoint_path": runtime["checkpoint_path"],
        "service_device": runtime["device"],
        "class_names": prompt_classes,
        "result": _result_to_payload(result),
    }
    if payload.get("annotated_output_path"):
        out_path = os.path.abspath(payload["annotated_output_path"])
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        response["annotated_output_path"] = _save_annotated_image(result, out_path)
    model.predictor = None
    return response


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            payload = {
                "ok": True,
                "repo": YOLOE_REPO,
                "default_checkpoint": DEFAULT_CHECKPOINT,
                "default_pf_checkpoint": DEFAULT_PF_CHECKPOINT,
                "pf_checkpoint_ready": os.path.exists(DEFAULT_PF_CHECKPOINT),
                "mobileclip_path": DEFAULT_MOBILECLIP,
                "mobileclip_ready": os.path.exists(DEFAULT_MOBILECLIP)
                or os.path.exists(os.path.join(YOLOE_REPO, "mobileclip_blt.pt")),
                "default_device": DEFAULT_DEVICE,
            }
            _json_response(self, payload)
            return

        _json_response(
            self,
            {"error": f"Unsupported GET path: {self.path}"},
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self):
        try:
            payload = _read_json(self)
            with INFERENCE_LOCK:
                if self.path == "/text-infer":
                    response = _run_text_infer(payload)
                elif self.path == "/prompt-free-infer":
                    response = _run_prompt_free_infer(payload)
                elif self.path == "/visual-infer":
                    response = _run_visual_infer(payload)
                else:
                    _json_response(
                        self,
                        {"error": f"Unsupported POST path: {self.path}"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
            _json_response(self, response)
        except Exception as exc:
            print(f"YOLOE service error on {self.path}: {exc!r}", flush=True)
            _json_response(
                self, {"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"YOLOE service listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
