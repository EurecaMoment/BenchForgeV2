"""Hot-update the BenchForge preset and its workbench."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from urllib.request import Request
from urllib.request import ProxyHandler
from urllib.request import HTTPCookieProcessor
from urllib.request import build_opener

from build_presets import base
from build_presets import build
from build_presets import yaml
from profile_migration import migrate_profile

ROOT = Path(__file__).resolve().parents[3]
Loader, Dumper = base.Loader, base.Dumper


def update_profile(profile, python, mode_config, service_config, revision, *, sources):
    generated = build(sources, str(python), mode_config, service_config)
    return migrate_profile(profile, generated, revision)


def service_state(service):
    return dict(line.split("=", 1) for line in subprocess.check_output(
        ["systemctl", "--user", "show", service, "-p", "MainPID", "-p", "ActiveState"], text=True).splitlines())


def monitored_services(dsh_service):
    return {name: service_state(name) for name in (dsh_service, "benchforge.service")}


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
    temporary = path.with_name(path.name + ".benchforge-new")
    temporary.write_bytes(content)
    temporary.chmod(path.stat().st_mode)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base.add_source_arguments(parser)
    parser.add_argument("--profile", type=Path, default=Path.home() / ".local/share/dsh-qwen/home/profiles/web/cordis.patch.yml")
    parser.add_argument("--python", type=Path, default=ROOT / ".deployment/python-development")
    parser.add_argument("--mode-config", type=Path, default=ROOT / "config/benchforge.local.json")
    parser.add_argument("--service-config", type=Path, default=base.default_service_config(ROOT))
    parser.add_argument("--dsh-service", default="dsh-qwen.service")
    parser.add_argument("--dsh-url", default="http://127.0.0.1:3080")
    parser.add_argument("--pull", action="store_true", help="First fast-forward the checkout's current branch")
    args = parser.parse_args()
    if args.pull:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
        if not branch:
            raise RuntimeError("--pull requires a checked-out branch")
        subprocess.run(["git", "pull", "--ff-only", "origin", branch], cwd=ROOT, check=True)
        script = ROOT / 'src/dsh/presets/hot_update.py'
        remaining = [argument for argument in sys.argv[1:] if argument != '--pull']
        return subprocess.run([sys.executable, str(script), *remaining], check=True).returncode
    for file in [args.profile, args.python, args.mode_config, args.service_config]:
        if not file.is_file():
            raise FileNotFoundError(file)
    services_before = monitored_services(args.dsh_service)
    if services_before[args.dsh_service]["ActiveState"] != "active":
        raise RuntimeError("DSH must already be running; this script never starts or restarts it")
    rpc = DshRpc(args.dsh_url, args.dsh_service, services_before[args.dsh_service]["MainPID"])
    revision = str(time.time_ns())
    previous = args.profile.read_bytes()
    profile = yaml.load(previous.decode("utf-8"), Loader=Loader)
    sources = base.load_sources(args.dsh_root, args.node, args.dsh_resolve_from)
    updated = update_profile(profile, args.python, args.mode_config, args.service_config, revision, sources=sources)
    deployment = ROOT / ".deployment"
    deployment.mkdir(exist_ok=True)
    backup = deployment / "benchforge-before-hot-update.yml"
    backup.write_bytes(previous)
    atomic_write(args.profile, yaml.dump(updated, Dumper=Dumper, sort_keys=False, allow_unicode=True).encode("utf-8"))
    try:
        deadline = time.monotonic() + 40
        while True:
            roster = rpc.call("agentPresets/list", {})
            presets = {row['id']: row for row in roster['presets']}
            ready = all(preset_id in presets and not presets[preset_id].get('broken')
                        and presets[preset_id].get('name') == metadata['name']
                        for preset_id, metadata in base.PRESETS.items())
            if ready and all(revision in json.dumps(rpc.call('agentPresets/read', {'agentPreset': preset_id}))
                             for preset_id in base.PRESETS):
                try:
                    with rpc.opener.open(args.dsh_url.rstrip('/') + '/api/benchforge/workbench?view=runtime',
                                         timeout=10) as response:
                        runtime = json.load(response)
                    if runtime.get('ui_revision') == revision:
                        break
                except (OSError, ValueError):
                    pass  # The old reader may still be retiring; never count it as adoption.
            if time.monotonic() >= deadline:
                raise TimeoutError("DSH did not adopt the BenchForge preset within 40 seconds")
            time.sleep(2)
        services_after = {name: service_state(name) for name in services_before}
        if services_after != services_before:
            raise RuntimeError("A monitored service changed during the hot update")
        receipt = {"repository": str(ROOT), "preset": base.BENCHFORGE_ID, "revision": revision,
                   "presets": {key: value['name'] for key, value in base.PRESETS.items()},
                   "workbench_revision": runtime['ui_revision'],
                   "services_before": services_before,
                   "services_after": services_after, "restarted": False,
                   "profile_backup": str(backup), "heavy_model_start": False}
        (deployment / "benchforge-hot-update.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False))
    except Exception:
        atomic_write(args.profile, previous)
        raise


if __name__ == "__main__":
    main()
