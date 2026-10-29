"""Hot-update only the SpatialForge preset in a running, unmodified DSH."""
import argparse
from copy import deepcopy
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from urllib.request import Request, ProxyHandler, HTTPCookieProcessor, build_opener

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("spatialforge_development", ROOT / "integrations/spatialforge/build_development_preset.py")
development = importlib.util.module_from_spec(spec)
spec.loader.exec_module(development)
yaml = development.yaml
Loader, Dumper = development.base.Loader, development.base.Dumper
PRESET_ID = "spatialforge-standard-ptc"


def update_profile(profile, root, python, mode_config, service_config, revision):
    result = deepcopy(profile)
    preset = next(row for patch in result for row in patch.get("insert", [])
                  if isinstance(row.get("config"), dict) and row["config"].get("id") == PRESET_ID)
    config = preset["config"]
    config["description"] = "SpatialForge development, runtime revision " + revision
    plugins = {
        "spatial-learning-tools": root / "integrations/dsh/tools.mjs",
        "spatialforge-tools": root / "integrations/spatialforge/plugin/tools.mjs",
        "persistent-bash": root / "integrations/dsh/persistent-shell.mjs",
        "persistent-pwsh": root / "integrations/dsh/persistent-shell.mjs",
    }

    def walk(rows):
        for row in rows:
            name = row.get("id")
            if name in plugins:
                row["name"] = str(plugins[name]) + "?spatialforge_revision=" + revision
            if name == "spatial-learning-tools":
                row["config"].update(python=str(python), configPath=str(mode_config),
                                     includeTools=development.LEARNING_TOOLS)
            if name == "spatialforge-tools":
                row["config"]["serviceConfig"] = str(service_config)
            if name == "persona":
                row["config"]["prefix"] = development.PERSONA
            if isinstance(row.get("config"), list):
                walk(row["config"])
    walk(config["plugins"])
    return result


def service_state(service):
    return dict(line.split("=", 1) for line in subprocess.check_output(
        ["systemctl", "--user", "show", service, "-p", "MainPID", "-p", "ActiveState"], text=True).splitlines())


class DshRpc:
    def __init__(self, url, service, pid):
        auth_url = os.environ.get("DSH_ADMIN_URL")
        if not auth_url:
            log = subprocess.check_output(["journalctl", "--user", "-u", service, "_PID=" + pid,
                                           "-n", "100", "--no-pager", "-o", "cat"], text=True)
            matches = re.findall(r"dsh web: (http[^\s]+\?token=[A-Za-z0-9_-]+)", log)
            if not matches:
                raise RuntimeError("Set DSH_ADMIN_URL to the current authenticated startup URL")
            auth_url = matches[-1]
        self.url = url.rstrip("/")
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.opener.open(auth_url, timeout=15).read()

    def call(self, method, args):
        body = {"type": "client-request", "rpcId": str(uuid.uuid4()), "method": method, "payload": {"args": args}}
        request = Request(self.url + "/api/" + method, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Origin": self.url})
        with self.opener.open(request, timeout=15) as response:
            result = json.load(response)["result"]
        if not result["ok"]:
            raise RuntimeError("DSH RPC failed: " + method)
        return result["value"]


def atomic_write(path, content):
    temporary = path.with_name(path.name + ".spatialforge-new")
    temporary.write_bytes(content)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path.home() / ".local/share/dsh-qwen/home/profiles/web/cordis.patch.yml")
    parser.add_argument("--python", type=Path, default=ROOT / ".deployment/python-development")
    parser.add_argument("--mode-config", type=Path, default=ROOT / "config/benchforge.local.json")
    parser.add_argument("--service-config", type=Path, default=ROOT / "config/spatialforge.local.json")
    parser.add_argument("--dsh-service", default="dsh-qwen.service")
    parser.add_argument("--dsh-url", default="http://127.0.0.1:3080")
    parser.add_argument("--pull", action="store_true", help="First fast-forward the existing SpatialForge checkout")
    args = parser.parse_args()
    if args.pull:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
        if branch != "SpatialForge":
            raise RuntimeError("--pull requires the SpatialForge branch")
        subprocess.run(["git", "pull", "--ff-only", "origin", "SpatialForge"], cwd=ROOT, check=True)
    for file in [args.profile, args.python, args.mode_config, args.service_config]:
        if not file.is_file():
            raise FileNotFoundError(file)
    services_before = {name: service_state(name) for name in [args.dsh_service, "spatialforge.service"]}
    if services_before[args.dsh_service]["ActiveState"] != "active":
        raise RuntimeError("DSH must already be running; this script never starts or restarts it")
    rpc = DshRpc(args.dsh_url, args.dsh_service, services_before[args.dsh_service]["MainPID"])
    revision = str(time.time_ns())
    previous = args.profile.read_bytes()
    profile = yaml.load(previous.decode("utf-8"), Loader=Loader)
    updated = update_profile(profile, ROOT, args.python, args.mode_config, args.service_config, revision)
    deployment = ROOT / ".deployment"
    deployment.mkdir(exist_ok=True)
    backup = deployment / "spatialforge-before-hot-update.yml"
    backup.write_bytes(previous)
    atomic_write(args.profile, yaml.dump(updated, Dumper=Dumper, sort_keys=False, allow_unicode=True).encode("utf-8"))
    try:
        deadline = time.monotonic() + 40
        while True:
            details = rpc.call("agentPresets/read", {"agentPreset": PRESET_ID})
            roster = rpc.call("agentPresets/list", {})
            preset = next(row for row in roster["presets"] if row["id"] == PRESET_ID)
            if revision in json.dumps(details) and not preset.get("broken"):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("DSH did not adopt the SpatialForge revision within 40 seconds")
            time.sleep(.5)
        services_after = {name: service_state(name) for name in services_before}
        if services_after != services_before:
            raise RuntimeError("A monitored service changed during the hot update")
        receipt = {"repository": str(ROOT), "preset": PRESET_ID, "revision": revision,
                   "model_tools": development.MODEL_TOOLS, "services_before": services_before,
                   "services_after": services_after, "restarted": False,
                   "existing_sessions": "keep their already-bound revision; new sessions use this update",
                   "profile_backup": str(backup), "heavy_model_start": False}
        (deployment / "spatialforge-hot-update.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False))
    except Exception:
        atomic_write(args.profile, previous)
        raise


if __name__ == "__main__":
    main()
