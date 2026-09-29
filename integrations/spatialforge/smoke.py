"""Offline contract smoke test for the public SpatialForge integration."""

from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).with_name("fixtures") / "delivery.json"


def main() -> int:
    delivery = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = {"capture", "visual_review", "interaction", "scene_file"}
    missing = required - set(delivery)
    if missing:
        raise SystemExit("missing delivery fields: " + ", ".join(sorted(missing)))
    if delivery["capture"]["status"] != "captured":
        raise SystemExit("fixture capture is not captured")
    if not delivery["interaction"]["success"]:
        raise SystemExit("fixture interaction is not successful")
    if not delivery["scene_file"]["loadable"]:
        raise SystemExit("fixture scene file is not loadable")
    print("SpatialForge integration smoke: PASS (offline; no model or Isaac started)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
