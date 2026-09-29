"""Small, dependency-free entry point for the SpatialForge integration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def load_config() -> dict:
    path = os.environ.get("SPATIALFORGE_CONFIG")
    if not path:
        return {"mode": "offline"}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def status(config: dict) -> int:
    if config.get("mode", "offline") == "offline":
        print(json.dumps({"mode": "offline", "service": "not contacted"}))
        return 0
    url = config["service_url"].rstrip("/") + "/status"
    token_name = config.get("operator_token_env", "SPATIALFORGE_OPERATOR_TOKEN")
    token = os.environ.get(token_name)
    if not token:
        raise SystemExit(f"missing {token_name}; credentials are not stored in the repository")
    request = Request(url, headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as response:
        print(response.read().decode("utf-8"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status"])
    args = parser.parse_args()
    return status(load_config())


if __name__ == "__main__":
    raise SystemExit(main())
