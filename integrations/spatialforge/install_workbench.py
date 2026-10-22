"""Install the BenchForge workbench as one root plugin in an already running DSH."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("benchforge_hot_update", ROOT / "integrations/spatialforge/hot_update.py")
hot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hot)
PLUGIN_ID = "benchforge-workbench-ui"
PACKAGE = "@eurecamoment/benchforge-spatialforge-ui"


def update_profile(profile, root, workspace_paths, revision=None):
    result = deepcopy(profile)
    # This is a host/root plugin. Session presets cannot own a global panel.
    inserted = [row for patch in result for row in patch.get("insert", [])]
    matches = [row for row in inserted if row.get("id") == PLUGIN_ID]
    if len(matches) > 1:
        raise ValueError("Duplicate workbench plugin rows")
    source = str(root / "integrations/spatialforge/ui/index.js")
    if revision:
        source += "?workbench_revision=" + revision
    config = deepcopy(matches[0].get("config", {})) if matches else {}
    if workspace_paths is not None:
        config["workspacePaths"] = [str(p) for p in workspace_paths]
    row = {"id": PLUGIN_ID, "name": source, "config": config}
    if matches:
        matches[0].clear()
        matches[0].update(row)
    else:
        result.append({"insert": [row]})
    return result


def graph_from_html(html):
    found = re.search(r'(?:window\.__DSH_BOOT__|globalThis\["__DSH_BOOT__"\])\s*=\s*(\{.*?\})\s*;?\s*</script>', html, re.S)
    if not found:
        raise RuntimeError("DSH did not return its client boot graph")
    return json.loads(found.group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path.home() / ".local/share/dsh-qwen/home/profiles/web/cordis.patch.yml")
    parser.add_argument("--workspace", type=Path, action="append")
    parser.add_argument("--dsh-service", default="dsh-qwen.service")
    parser.add_argument("--dsh-url", default="http://127.0.0.1:3080")
    args = parser.parse_args()
    before = {name: hot.service_state(name) for name in [args.dsh_service, "spatialforge.service"]}
    if before[args.dsh_service]["ActiveState"] != "active":
        raise RuntimeError("DSH must already be active; this installer never starts or restarts it")
    rpc = hot.DshRpc(args.dsh_url, args.dsh_service, before[args.dsh_service]["MainPID"])
    previous = args.profile.read_bytes()
    profile = hot.yaml.load(previous.decode("utf-8"), Loader=hot.Loader)
    updated = update_profile(profile, ROOT, args.workspace, str(time.time_ns()))
    deployment = ROOT / ".deployment"
    deployment.mkdir(exist_ok=True)
    backup = deployment / ("workbench-before-" + time.strftime("%Y%m%d-%H%M%S") + ".yml")
    backup.write_bytes(previous)
    hot.atomic_write(args.profile, hot.yaml.dump(updated, Dumper=hot.Dumper, sort_keys=False, allow_unicode=True).encode())
    try:
        deadline = time.monotonic() + 35
        while True:
            try:
                with rpc.opener.open(args.dsh_url + "/api/benchforge/workbench?view=summary", timeout=15) as response:
                    summary = json.load(response)
                with rpc.opener.open(args.dsh_url, timeout=15) as response:
                    graph = graph_from_html(response.read().decode())
                entry = next(row for row in graph["entries"] if row["id"] == PACKAGE)
                break
            except (OSError, RuntimeError, StopIteration):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        with rpc.opener.open(args.dsh_url.rstrip("/") + "/" + entry["url"].lstrip("/"), timeout=15) as response:
            bundle = response.read().decode()
        if PACKAGE not in bundle or "benchforge-workbench" not in bundle:
            raise RuntimeError("Workbench client bundle did not contain the registered panel")
        after = {name: hot.service_state(name) for name in before}
        if before != after:
            raise RuntimeError("A monitored service changed during the update")
        receipt = {"repository": str(ROOT), "plugin": PLUGIN_ID, "client_package": PACKAGE,
                   "profile_backup": str(backup), "services_before": before, "services_after": after,
                   "restarted": False, "api_runs": len(summary["runs"]), "api_datasets": len(summary["datasets"]),
                   "client_bundle_served": True, "browser_render_verified": False,
                   "scope": summary["scope"], "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        (deployment / "workbench-install.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False))
    except Exception:
        hot.atomic_write(args.profile, previous)
        raise


if __name__ == "__main__":
    main()

