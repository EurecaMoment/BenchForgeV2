#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


HOST = os.environ.get("DEPTHANYTHING3_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEPTHANYTHING3_PORT", "8008"))
BASE_URL = os.environ.get("DEPTHANYTHING3_BASE_URL", f"http://{HOST}:{PORT}")
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHCLAW_ROOT = os.environ.get(
    "BENCHCLAW_ROOT", os.path.abspath(os.path.join(ROOT_DIR, "..", ".."))
)
BENCHCLAW_PARENT = os.path.abspath(os.path.join(BENCHCLAW_ROOT, ".."))
THIRD_PARTY_ROOT = os.environ.get(
    "THIRD_PARTY_ROOT", os.path.join(BENCHCLAW_PARENT, "thirty_part")
)
SERVICE_LOG = os.path.join(ROOT_DIR, "service.log")
CONDA_EXE = os.environ.get("CONDA_EXE", "")
CONDA_ENV = os.environ.get("DEPTHANYTHING3_CONDA_ENV", "depthanythingv3")
PROJECT_DIR = os.environ.get(
    "DEPTHANYTHING3_PROJECT_DIR",
    os.path.join(THIRD_PARTY_ROOT, "annotationTools", "Depth-Anything-3"),
)
DEFAULT_MODEL_DIR = os.environ.get(
    "DEPTHANYTHING3_MODEL_DIR",
    "",
)
DEFAULT_GALLERY_DIR = os.environ.get(
    "DEPTHANYTHING3_GALLERY_DIR",
    os.path.join(
        THIRD_PARTY_ROOT, "annotationTools", "Depth-Anything-3", "workspace", "gallery"
    ),
)


def load_json_file(path_value):
    with open(path_value, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


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


def _http_get(path, timeout=30):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post(path, payload, timeout=3600):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_delete(path, timeout=30):
    request = urllib.request.Request(f"{BASE_URL}{path}", method="DELETE")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def service_is_ready():
    try:
        payload = _http_get("/status", timeout=10)
        return isinstance(payload, dict) and "model_loaded" in payload
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


def _normalize_optional_path(path_value):
    if not path_value:
        return None
    return resolve_local_path(path_value)


def cmd_health(_args):
    print_json({"ok": service_is_ready(), "base_url": BASE_URL})


def cmd_status(_args):
    print_json(_http_get("/status"))


def cmd_gpu_memory(_args):
    print_json(_http_get("/gpu-memory"))


def cmd_tasks(_args):
    print_json(_http_get("/tasks"))


def cmd_task(args):
    print_json(_http_get(f"/task/{args.task_id}"))


def cmd_delete_task(args):
    print_json(_http_delete(f"/task/{args.task_id}"))


def cmd_reload(_args):
    print_json(_http_post("/reload", {}))


def cmd_cleanup(_args):
    print_json(_http_post("/cleanup", {}))


def cmd_ensure_server(args):
    print_json(
        ensure_server(
            timeout_seconds=args.timeout,
            model_dir=args.model_dir,
            device=args.device,
            gallery_dir=args.gallery_dir,
        )
    )


def cmd_submit(args):
    ensure_server(
        timeout_seconds=args.timeout,
        model_dir=args.model_dir,
        device=args.device,
        gallery_dir=args.gallery_dir,
    )
    payload = {
        "image_paths": [os.path.abspath(path) for path in args.image_path],
        "export_dir": _normalize_optional_path(args.export_dir),
        "export_format": args.export_format,
        "process_res": args.process_res,
        "process_res_method": args.process_res_method,
        "export_feat_layers": [
            int(item) for item in args.export_feat.split(",") if item.strip()
        ],
        "require_metric_depth": True,
        "align_to_input_ext_scale": args.align_to_input_ext_scale,
        "use_ray_pose": args.use_ray_pose,
        "ref_view_strategy": args.ref_view_strategy,
        "conf_thresh_percentile": args.conf_thresh_percentile,
        "num_max_points": args.num_max_points,
        "show_cameras": args.show_cameras,
        "feat_vis_fps": args.feat_vis_fps,
    }
    if args.extrinsics_json:
        payload["extrinsics"] = load_json_file(args.extrinsics_json)
    if args.intrinsics_json:
        payload["intrinsics"] = load_json_file(args.intrinsics_json)
    print_json(_http_post("/inference", payload, timeout=60))


def cmd_wait_task(args):
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        payload = _http_get(f"/task/{args.task_id}")
        if args.quiet:
            if payload.get("status") in {"completed", "failed"}:
                print_json(payload)
                if payload.get("status") == "failed":
                    raise RuntimeError(
                        payload.get("message")
                        or f"DepthAnything3 task {args.task_id} failed"
                    )
                return
        else:
            print_json(payload)
        if payload.get("status") in {"completed", "failed"}:
            if payload.get("status") == "failed":
                raise RuntimeError(
                    payload.get("message")
                    or f"DepthAnything3 task {args.task_id} failed"
                )
            return
        time.sleep(args.poll_interval)
    raise RuntimeError(f"Timed out waiting for task {args.task_id}")


def cmd_auto(args):
    ensure_server(
        timeout_seconds=args.timeout,
        model_dir=args.model_dir,
        device=args.device,
        gallery_dir=args.gallery_dir,
    )

    command = [
        CONDA_EXE,
        "run",
        "--no-capture-output",
        "-n",
        CONDA_ENV,
        "da3",
        "auto",
        resolve_local_path(args.input_path),
        "--model-dir",
        resolve_local_path(args.model_dir or DEFAULT_MODEL_DIR),
        "--export-dir",
        resolve_local_path(args.export_dir),
        "--export-format",
        args.export_format,
        "--backend-url",
        BASE_URL,
        "--use-backend",
        "--process-res",
        str(args.process_res),
        "--process-res-method",
        args.process_res_method,
        "--conf-thresh-percentile",
        str(args.conf_thresh_percentile),
        "--num-max-points",
        str(args.num_max_points),
        "--feat-vis-fps",
        str(args.feat_vis_fps),
        "--fps",
        str(args.fps),
    ]
    if args.export_feat:
        command.extend(["--export-feat", args.export_feat])
    if args.auto_cleanup:
        command.append("--auto-cleanup")
    if not args.show_cameras:
        command.extend(["--show-cameras", "False"])
    if args.sparse_subdir:
        command.extend(["--sparse-subdir", args.sparse_subdir])
    if not args.align_to_input_ext_scale:
        command.extend(["--align-to-input-ext-scale", "False"])
    if args.use_ray_pose:
        command.append("--use-ray-pose")
    if args.ref_view_strategy:
        command.extend(["--ref-view-strategy", args.ref_view_strategy])

    completed = subprocess.run(command, cwd=PROJECT_DIR, check=False)
    sys.exit(completed.returncode)


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health")
    health_parser.set_defaults(func=cmd_health)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=cmd_status)

    gpu_parser = subparsers.add_parser("gpu-memory")
    gpu_parser.set_defaults(func=cmd_gpu_memory)

    tasks_parser = subparsers.add_parser("tasks")
    tasks_parser.set_defaults(func=cmd_tasks)

    task_parser = subparsers.add_parser("task")
    task_parser.add_argument("--task-id", required=True)
    task_parser.set_defaults(func=cmd_task)

    delete_parser = subparsers.add_parser("delete-task")
    delete_parser.add_argument("--task-id", required=True)
    delete_parser.set_defaults(func=cmd_delete_task)

    reload_parser = subparsers.add_parser("reload")
    reload_parser.set_defaults(func=cmd_reload)

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.set_defaults(func=cmd_cleanup)

    ensure_parser = subparsers.add_parser("ensure-server")
    ensure_parser.add_argument("--timeout", type=int, default=240)
    ensure_parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ensure_parser.add_argument("--device", default="cuda")
    ensure_parser.add_argument("--gallery-dir", default=DEFAULT_GALLERY_DIR)
    ensure_parser.set_defaults(func=cmd_ensure_server)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--image-path", action="append", required=True)
    submit_parser.add_argument("--export-dir", required=True)
    submit_parser.add_argument("--export-format", default="glb")
    submit_parser.add_argument("--process-res", type=int, default=1024)
    submit_parser.add_argument("--process-res-method", default="upper_bound_resize")
    submit_parser.add_argument("--export-feat", default="")
    submit_parser.add_argument(
        "--align-to-input-ext-scale", action="store_true", default=True
    )
    submit_parser.add_argument("--use-ray-pose", action="store_true")
    submit_parser.add_argument("--ref-view-strategy", default="saddle_balanced")
    submit_parser.add_argument("--conf-thresh-percentile", type=float, default=40.0)
    submit_parser.add_argument("--num-max-points", type=int, default=1_000_000)
    submit_parser.add_argument("--show-cameras", action="store_true", default=True)
    submit_parser.add_argument("--feat-vis-fps", type=int, default=15)
    submit_parser.add_argument("--extrinsics-json")
    submit_parser.add_argument("--intrinsics-json")
    submit_parser.add_argument("--timeout", type=int, default=240)
    submit_parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    submit_parser.add_argument("--device", default="cuda")
    submit_parser.add_argument("--gallery-dir", default=DEFAULT_GALLERY_DIR)
    submit_parser.set_defaults(func=cmd_submit)

    wait_parser = subparsers.add_parser("wait-task")
    wait_parser.add_argument("--task-id", required=True)
    wait_parser.add_argument("--poll-interval", type=float, default=5.0)
    wait_parser.add_argument("--timeout", type=int, default=3600)
    wait_parser.add_argument("--quiet", action="store_true")
    wait_parser.set_defaults(func=cmd_wait_task)

    auto_parser = subparsers.add_parser("auto")
    auto_parser.add_argument("--input-path", required=True)
    auto_parser.add_argument("--export-dir", required=True)
    auto_parser.add_argument("--export-format", default="glb")
    auto_parser.add_argument("--process-res", type=int, default=1024)
    auto_parser.add_argument("--process-res-method", default="upper_bound_resize")
    auto_parser.add_argument("--export-feat", default="")
    auto_parser.add_argument("--auto-cleanup", action="store_true")
    auto_parser.add_argument("--fps", type=float, default=1.0)
    auto_parser.add_argument("--sparse-subdir", default="")
    auto_parser.add_argument(
        "--align-to-input-ext-scale", action="store_true", default=True
    )
    auto_parser.add_argument("--use-ray-pose", action="store_true")
    auto_parser.add_argument("--ref-view-strategy", default="saddle_balanced")
    auto_parser.add_argument("--conf-thresh-percentile", type=float, default=40.0)
    auto_parser.add_argument("--num-max-points", type=int, default=1_000_000)
    auto_parser.add_argument("--show-cameras", action="store_true", default=True)
    auto_parser.add_argument("--feat-vis-fps", type=int, default=15)
    auto_parser.add_argument("--timeout", type=int, default=240)
    auto_parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    auto_parser.add_argument("--device", default="cuda")
    auto_parser.add_argument("--gallery-dir", default=DEFAULT_GALLERY_DIR)
    auto_parser.set_defaults(func=cmd_auto)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
