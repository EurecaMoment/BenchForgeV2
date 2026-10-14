"""HTTP protocol tests: no model libraries, weights or GPU processes."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from benchforge_core.model_services import CLIENTS
from benchforge_core.model_services.client import ModelService
from benchforge_core.runtime import Runtime


class ModelClients(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.jobs = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, value, code=200):
                data = json.dumps(value).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    self.reply({"status": "ready", "host": "fixture"})
                else:
                    self.reply(owner.jobs[self.path.rsplit("/", 1)[-1]])

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(payload)
                job = {"id": str(len(owner.requests)), "status": "queued", "tool": payload["tool"]}
                owner.jobs[job["id"]] = job
                self.reply(job, 202)

            def do_DELETE(self):
                job = owner.jobs[self.path.rsplit("/", 1)[-1]]
                job["status"] = "canceled"
                self.reply(job)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {"url": "http://127.0.0.1:" + str(self.server.server_port),
                       "tools": {"lama": {"request_defaults": {"model_path": "/external/lama.pt"}}}}

    def test_each_independent_module_uses_native_route_without_model_import(self):
        for name, route in CLIENTS.items():
            client = importlib.import_module("benchforge_core.model_services." + name)
            work = self.root / name
            result = client.call(request={"image": "/shared/input.png"}, work=work, config=self.config)
            self.assertEqual(result["inference_status"], "queued")
            self.assertNotIn("result", result)
            self.assertEqual(self.requests[-1]["tool"], route)
            self.assertEqual(self.requests[-1]["work"], str(work))
        self.assertEqual(self.requests[3]["request"]["model_path"], "/external/lama.pt")
        code = "import importlib,sys; from benchforge_core.model_services import CLIENTS; [importlib.import_module('benchforge_core.model_services.'+n) for n in CLIENTS]; assert not any(n in sys.modules for n in ['torch','transformers','diffusers','pic2sim'])"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_async_status_result_failure_and_explicit_cancel(self):
        client = ModelService(self.config)
        queued = client.call("lama", work=self.root / "job", request={"image": "/shared/image"})
        job_id = queued["job_id"]
        self.assertEqual(client.call("lama", action="wait", job_id=job_id, timeout_seconds=0)["inference_status"], "queued")
        self.jobs[job_id].update(status="completed", result={"status": "ok", "output": "/shared/result.png"})
        self.assertEqual(client.call("lama", action="result", job_id=job_id)["result"]["output"], "/shared/result.png")
        self.jobs[job_id].update(status="failed", error="provider failed")
        self.assertEqual(client.call("lama", action="status", job_id=job_id)["error"], "provider failed")
        self.assertEqual(client.call("lama", action="cancel", job_id=job_id)["inference_status"], "canceled")
        self.assertEqual(len(self.requests), 1)

    def test_standalone_cli_and_runtime_return_service_receipts(self):
        result = subprocess.run([sys.executable, "-m", "benchforge_core.model_services.yoloe",
                                 "--endpoint", self.config["url"], "--action", "health"],
                                capture_output=True, text=True,
                                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["health"]["status"], "ready")
        runtime = Runtime(self.root / "runtime", {"model_services": self.config})
        self.addCleanup(runtime.close)
        result = runtime.call("model_lama", {"request": {"image": "/shared/input"}})
        self.assertEqual(result["inference_status"], "queued")
        self.assertTrue((Path(result["artifact_dir"]) / "result.json").is_file())
        self.assertEqual(runtime.call("model_lama", {"action": "health"})["health"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
