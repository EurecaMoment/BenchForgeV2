#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request


HOST = os.environ.get("YOLOE_SERVICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("YOLOE_SERVICE_PORT", "8766"))
BASE_URL = os.environ.get("YOLOE_BASE_URL", f"http://{HOST}:{PORT}")
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHCLAW_ROOT = os.environ.get(
    "BENCHCLAW_ROOT", os.path.abspath(os.path.join(ROOT_DIR, "..", ".."))
)
BENCHCLAW_PARENT = os.path.abspath(os.path.join(BENCHCLAW_ROOT, ".."))
THIRD_PARTY_ROOT = os.environ.get(
    "THIRD_PARTY_ROOT", os.path.join(BENCHCLAW_PARENT, "thirty_part")
)
SERVICE_PATH = os.path.join(ROOT_DIR, "yoloe_service.py")
SERVICE_LOG = os.path.join(ROOT_DIR, "service.log")
CONDA_EXE = os.environ.get("CONDA_EXE", "")
CONDA_ENV = os.environ.get("YOLOE_CONDA_ENV", "yoloe")
YOLOE_REPO = os.environ.get(
    "YOLOE_REPO",
    os.path.join(THIRD_PARTY_ROOT, "annotationTools", "yoloe"),
)
YOLOE_CHECKPOINT = os.environ.get(
    "YOLOE_CHECKPOINT",
    "",
)
YOLOE_MOBILECLIP = os.environ.get(
    "YOLOE_MOBILECLIP",
    "",
)
YOLOE_PF_CHECKPOINT = os.environ.get(
    "YOLOE_PF_CHECKPOINT",
    "",
)


def resolve_local_path(path_value):
    if not path_value:
        return path_value
    text = str(path_value).replace("\\", "/")
    if text == "BENCHCLAW_ROOT":
        return BENCHCLAW_ROOT
    if text.startswith("BENCHCLAW_ROOT/"):
        return os.path.abspath(
            os.path.join(BENCHCLAW_ROOT, text[len("BENCHCLAW_ROOT/") :])
        )
    if text == "THIRD_PARTY_ROOT":
        return THIRD_PARTY_ROOT
    if text.startswith("THIRD_PARTY_ROOT/"):
        return os.path.abspath(
            os.path.join(THIRD_PARTY_ROOT, text[len("THIRD_PARTY_ROOT/") :])
        )
    return os.path.abspath(path_value)


def load_json_file(path_value):
    with open(path_value, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _http_get(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post(path, payload):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3600) as response:
        return json.loads(response.read().decode("utf-8"))


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def service_is_ready():
    try:
        payload = _http_get("/health")
        return bool(payload.get("ok"))
    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        OSError,
        json.JSONDecodeError,
    ):
        return False


def ensure_server(*args, **kwargs):
    if service_is_ready():
        return {"reused": True, "url": BASE_URL}
    raise RuntimeError("Configured backend is offline; start it explicitly with benchforge backend. No automatic service mutation.")


def cmd_health(_args):
    print_json(_http_get("/health"))


def cmd_ensure_server(args):
    print_json(ensure_server(timeout_seconds=args.timeout))


def cmd_text_infer(args):
    ensure_server(timeout_seconds=args.timeout)
    payload = {
        "image_path": resolve_local_path(args.image_path),
        "checkpoint_path": args.checkpoint_path,
        "device": args.device,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "names": [item.strip() for item in args.names.split(",") if item.strip()],
        "annotated_output_path": resolve_local_path(args.annotated_output_path)
        if args.annotated_output_path
        else None,
    }
    print_json(_http_post("/text-infer", payload))


def cmd_prompt_free_infer(args):
    ensure_server(timeout_seconds=args.timeout)
    if args.names_file:
        with open(args.names_file, "r", encoding="utf-8") as handle:
            names = [line.strip() for line in handle if line.strip()]
    else:
        names = [item.strip() for item in args.names.split(",") if item.strip()]
    payload = {
        "image_path": resolve_local_path(args.image_path),
        "checkpoint_path": args.checkpoint_path,
        "device": args.device,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "names": names,
        "pf_checkpoint_path": args.pf_checkpoint_path,
        "pf_head_conf": args.pf_head_conf,
        "max_det": args.max_det,
        "annotated_output_path": resolve_local_path(args.annotated_output_path)
        if args.annotated_output_path
        else None,
    }
    print_json(_http_post("/prompt-free-infer", payload))


def cmd_visual_infer(args):
    ensure_server(timeout_seconds=args.timeout)
    if args.request_file:
        payload = load_json_file(args.request_file)
    else:
        payload = {
            "image_path": args.image_path,
            "target_image_path": args.target_image_path,
            "prompt_type": args.prompt_type,
            "class_names": [
                item.strip() for item in args.class_names.split(",") if item.strip()
            ]
            or ["object0"],
            "imgsz": args.imgsz,
            "conf": args.conf,
            "iou": args.iou,
            "annotated_output_path": args.annotated_output_path,
        }
        if args.prompt_type == "bboxes":
            if not args.bbox:
                raise RuntimeError(
                    "visual-infer with --prompt-type bboxes requires at least one --bbox"
                )
            payload["bboxes"] = [
                [float(v) for v in item.split(",")] for item in args.bbox
            ]
            payload["cls"] = (
                [int(v) for v in args.cls.split(",")]
                if args.cls
                else [0] * len(payload["bboxes"])
            )
        else:
            if not args.mask_json:
                raise RuntimeError(
                    "visual-infer with --prompt-type masks requires --mask-json"
                )
            payload["masks"] = load_json_file(args.mask_json)
            payload["cls"] = (
                [int(v) for v in args.cls.split(",")]
                if args.cls
                else [0] * len(payload["masks"])
            )
    payload.setdefault("checkpoint_path", args.checkpoint_path)
    payload.setdefault("device", args.device)
    if payload.get("image_path"):
        payload["image_path"] = resolve_local_path(payload["image_path"])
    if payload.get("target_image_path"):
        payload["target_image_path"] = resolve_local_path(payload["target_image_path"])
    if payload.get("annotated_output_path"):
        payload["annotated_output_path"] = resolve_local_path(
            payload["annotated_output_path"]
        )
    print_json(_http_post("/visual-infer", payload))


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_parser = subparsers.add_parser("ensure-server")
    ensure_parser.add_argument("--timeout", type=int, default=180)
    ensure_parser.set_defaults(func=cmd_ensure_server)

    health_parser = subparsers.add_parser("health")
    health_parser.set_defaults(func=cmd_health)

    text_parser = subparsers.add_parser("text-infer")
    text_parser.add_argument("--image-path", required=True)
    text_parser.add_argument(
        "--names", required=True, help="Comma-separated class names"
    )
    text_parser.add_argument("--imgsz", type=int, default=640)
    text_parser.add_argument("--conf", type=float, default=0.25)
    text_parser.add_argument("--iou", type=float, default=0.7)
    text_parser.add_argument("--checkpoint-path", default=YOLOE_CHECKPOINT)
    text_parser.add_argument("--device", default="auto")
    text_parser.add_argument("--annotated-output-path")
    text_parser.add_argument("--timeout", type=int, default=180)
    text_parser.set_defaults(func=cmd_text_infer)

    pf_parser = subparsers.add_parser("prompt-free-infer")
    pf_parser.add_argument("--image-path", required=True)
    pf_parser.add_argument("--names", default="")
    pf_parser.add_argument("--names-file")
    pf_parser.add_argument("--imgsz", type=int, default=640)
    pf_parser.add_argument("--conf", type=float, default=0.25)
    pf_parser.add_argument("--iou", type=float, default=0.7)
    pf_parser.add_argument("--pf-checkpoint-path", default=YOLOE_PF_CHECKPOINT)
    pf_parser.add_argument("--pf-head-conf", type=float, default=0.001)
    pf_parser.add_argument("--max-det", type=int, default=1000)
    pf_parser.add_argument("--checkpoint-path", default=YOLOE_CHECKPOINT)
    pf_parser.add_argument("--device", default="auto")
    pf_parser.add_argument("--annotated-output-path")
    pf_parser.add_argument("--timeout", type=int, default=180)
    pf_parser.set_defaults(func=cmd_prompt_free_infer)

    visual_parser = subparsers.add_parser("visual-infer")
    visual_parser.add_argument("--request-file")
    visual_parser.add_argument("--image-path")
    visual_parser.add_argument("--target-image-path")
    visual_parser.add_argument(
        "--prompt-type", choices=["bboxes", "masks"], default="bboxes"
    )
    visual_parser.add_argument(
        "--bbox", action="append", help="x1,y1,x2,y2; repeatable"
    )
    visual_parser.add_argument("--mask-json")
    visual_parser.add_argument("--cls", default="")
    visual_parser.add_argument("--class-names", default="object0")
    visual_parser.add_argument("--imgsz", type=int, default=640)
    visual_parser.add_argument("--conf", type=float, default=0.25)
    visual_parser.add_argument("--iou", type=float, default=0.7)
    visual_parser.add_argument("--annotated-output-path")
    visual_parser.add_argument("--checkpoint-path", default=YOLOE_CHECKPOINT)
    visual_parser.add_argument("--device", default="auto")
    visual_parser.add_argument("--timeout", type=int, default=180)
    visual_parser.set_defaults(func=cmd_visual_infer)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
