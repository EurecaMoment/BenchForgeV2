#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


HOST = os.environ.get("SAM3_HOST", "127.0.0.1")
PORT = int(os.environ.get("SAM3_PORT", "8765"))
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_PATH = os.path.join(ROOT_DIR, "sam3_service.py")
SERVICE_LOG = os.path.join(ROOT_DIR, "service.log")
BASE_URL = os.environ.get("SAM3_BASE_URL", f"http://{HOST}:{PORT}")
CONDA_EXE = os.environ.get("CONDA_EXE", "")
DEFAULT_WARMUP_IMAGE = os.environ.get(
    "SAM3_WARMUP_IMAGE",
    "",
)

# Local annotation services must not go through HTTP_PROXY/HTTPS_PROXY.
# Otherwise health checks against 127.0.0.1 can time out, causing duplicate
# service starts and multiple heavy SAM3 model loads.
_no_proxy_values = [HOST, "127.0.0.1", "localhost"]
for _env_name in ("NO_PROXY", "no_proxy"):
    existing = os.environ.get(_env_name, "")
    merged = [x.strip() for x in existing.split(",") if x.strip()]
    for value in _no_proxy_values:
        if value and value not in merged:
            merged.append(value)
    os.environ[_env_name] = ",".join(merged)
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load_json_file(path_value):
    with open(path_value, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _http_get(path):
    with NO_PROXY_OPENER.open(f"{BASE_URL}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post(path, payload):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with NO_PROXY_OPENER.open(request, timeout=3600) as response:
        return json.loads(response.read().decode("utf-8"))


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


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def cmd_health(_args):
    print_json(_http_get("/health"))


def cmd_ensure_server(args):
    print_json(ensure_server(timeout_seconds=args.timeout))


def warmup_image_runtime(image_path=None, timeout_seconds=300):
    ensure_server(timeout_seconds=timeout_seconds)
    health_before = _http_get("/health")
    selected_image = image_path or DEFAULT_WARMUP_IMAGE
    if health_before.get("image_runtime_loaded"):
        return {
            "ok": True,
            "reused_runtime": True,
            "image_runtime_loaded": True,
            "health_before": health_before,
        }
    if not selected_image or not os.path.isfile(selected_image):
        raise RuntimeError(f"SAM3 warmup image not found: {selected_image}")

    session_payload = _http_post(
        "/image/request",
        {
            "request": {
                "type": "start_session",
                "image_path": os.path.abspath(selected_image),
            }
        },
    )
    result = session_payload.get("result") or {}
    session_id = result.get("session_id")
    if session_id:
        _http_post(
            "/image/request",
            {"request": {"type": "close_session", "session_id": session_id}},
        )
    health_after = _http_get("/health")
    if not health_after.get("image_runtime_loaded"):
        raise RuntimeError(f"SAM3 image runtime did not load: {health_after}")
    return {
        "ok": True,
        "reused_runtime": False,
        "image_runtime_loaded": True,
        "warmup_image": os.path.abspath(selected_image),
        "session_id": session_id,
        "health_before": health_before,
        "health_after": health_after,
    }


def cmd_warmup(args):
    print_json(warmup_image_runtime(args.image_path, timeout_seconds=args.timeout))


def cmd_image_infer(args):
    ensure_server(timeout_seconds=args.timeout)
    payload = {
        "image_path": os.path.abspath(args.image_path),
        "text_prompt": args.text_prompt,
        "save_masks_dir": os.path.abspath(args.save_masks_dir)
        if args.save_masks_dir
        else None,
        "confidence_threshold": args.confidence_threshold,
        "checkpoint_path": args.checkpoint_path,
        "include_logits": args.include_logits,
        "box_prompts": [json.loads(item) for item in args.box_prompt],
    }
    print_json(_http_post("/image/infer", payload))


def cmd_image_request(args):
    ensure_server(timeout_seconds=args.timeout)
    request_payload = load_json_file(args.request_file)
    print_json(_http_post("/image/request", {"request": request_payload}))


def cmd_video_request(args):
    ensure_server(timeout_seconds=args.timeout)
    request_payload = load_json_file(args.request_file)
    payload = {
        "version": args.version,
        "checkpoint_path": args.checkpoint_path,
        "compile": args.compile,
        "stream": args.stream,
        "request": request_payload,
    }
    print_json(_http_post("/video/request", payload))


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_parser = subparsers.add_parser("ensure-server")
    ensure_parser.add_argument("--timeout", type=int, default=180)
    ensure_parser.set_defaults(func=cmd_ensure_server)

    health_parser = subparsers.add_parser("health")
    health_parser.set_defaults(func=cmd_health)

    warmup_parser = subparsers.add_parser("warmup")
    warmup_parser.add_argument("--image-path", default=DEFAULT_WARMUP_IMAGE)
    warmup_parser.add_argument("--timeout", type=int, default=300)
    warmup_parser.set_defaults(func=cmd_warmup)

    image_parser = subparsers.add_parser("image-infer")
    image_parser.add_argument("--image-path", required=True)
    image_parser.add_argument("--text-prompt", default="")
    image_parser.add_argument("--save-masks-dir")
    image_parser.add_argument("--confidence-threshold", type=float, default=0.2)
    image_parser.add_argument("--box-prompt", action="append", default=[])
    image_parser.add_argument("--checkpoint-path")
    image_parser.add_argument("--include-logits", action="store_true")
    image_parser.add_argument("--timeout", type=int, default=180)
    image_parser.set_defaults(func=cmd_image_infer)

    image_request_parser = subparsers.add_parser("image-request")
    image_request_parser.add_argument("--request-file", required=True)
    image_request_parser.add_argument("--timeout", type=int, default=180)
    image_request_parser.set_defaults(func=cmd_image_request)

    video_parser = subparsers.add_parser("video-request")
    video_parser.add_argument("--request-file", required=True)
    video_parser.add_argument("--version", default="sam3.1")
    video_parser.add_argument("--checkpoint-path")
    video_parser.add_argument("--compile", action="store_true")
    video_parser.add_argument("--stream", action="store_true")
    video_parser.add_argument("--timeout", type=int, default=180)
    video_parser.set_defaults(func=cmd_video_request)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
