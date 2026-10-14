"""Standard-library client for existing asynchronous model service endpoints."""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import Request, ProxyHandler, build_opener


class ModelService:
    def __init__(self, config=None):
        self.config = config or {}
        self.url = (self.config.get("url") or os.environ.get("BENCHFORGE_INFERENCE_URL", "")).rstrip("/")
        if not self.url:
            raise ValueError("Configure model_services.url or BENCHFORGE_INFERENCE_URL")
        self.opener = build_opener(ProxyHandler({}))

    def rpc(self, route, payload=None, method=None):
        headers = {"Content-Type": "application/json"}
        if self.config.get("token_env"):
            headers["Authorization"] = "Bearer " + os.environ[self.config["token_env"]]
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(self.url + route, data=body, headers=headers, method=method)
        with self.opener.open(request, timeout=self.config.get("http_timeout_seconds", 30)) as response:
            return json.load(response)

    def call(self, tool, *, action="submit", request=None, work=None, job_id=None, timeout_seconds=300):
        if action == "health":
            return {"service": self.url, "health": self.rpc("/health")}
        if action == "submit":
            if work is None:
                raise ValueError("submit requires an absolute shared work directory")
            directory = Path(work).expanduser()
            if not directory.is_absolute():
                raise ValueError("work must be an absolute path visible to the inference service")
            directory.mkdir(parents=True, exist_ok=True)
            defaults = self.config.get("tools", {}).get(tool, {}).get("request_defaults", {})
            job = self.rpc("/jobs", {"tool": tool, "request": {**defaults, **(request or {})}, "work": str(directory)})
            (directory / "model-service-job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        else:
            if not job_id:
                raise ValueError(action + " requires job_id")
            route = "/jobs/" + quote(job_id, safe="")
            if action == "cancel":
                job = self.rpc(route, {}, method="DELETE")
            elif action in {"status", "result", "wait"}:
                job = self.rpc(route)
            else:
                raise ValueError("Unknown model service action: " + action)
            if action == "wait":
                deadline = time.monotonic() + timeout_seconds
                while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                    job = self.rpc(route)
        return {"service": self.url, "job_id": job["id"], "inference_status": job["status"], "job": job,
                **({"result": job["result"]} if "result" in job else {}),
                **({"error": job["error"]} if "error" in job else {})}


def load_config(path=None):
    path = path or os.environ.get("BENCHFORGE_MODEL_SERVICES_CONFIG")
    return json.loads(Path(path).read_text(encoding="utf-8")).get("model_services", {}) if path else {}


def module_main(tool):
    parser = argparse.ArgumentParser(description="Call an existing model API; never starts a model or GPU process.")
    parser.add_argument("--action", choices=["submit", "status", "result", "wait", "cancel", "health"], default="submit")
    parser.add_argument("--config", help="Private JSON file containing model_services")
    parser.add_argument("--endpoint", help="Override the configured inference API URL")
    parser.add_argument("--input", help="Native model request JSON; '-' reads stdin")
    parser.add_argument("--work", help="Absolute shared artifact directory")
    parser.add_argument("--job-id")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.endpoint:
        config["url"] = args.endpoint
    if args.input == "-":
        import sys
        request = json.load(sys.stdin)
    else:
        request = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else {}
    value = ModelService(config).call(tool, action=args.action, request=request, work=args.work,
                                    job_id=args.job_id, timeout_seconds=args.timeout_seconds)
    print(json.dumps(value, ensure_ascii=False))
