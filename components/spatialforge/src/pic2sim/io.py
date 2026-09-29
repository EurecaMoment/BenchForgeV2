from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class ArtifactError(RuntimeError):
    pass


def write_json_atomic(path: str | Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, destination)


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"Cannot read JSON {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"Expected a JSON object in {source}")
    return value


def inspect_required_files(config_data: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name, spec in sorted(config_data["models"].items()):
        root = Path(spec["path"])
        python = Path(spec["python"])
        required = [root / relative for relative in spec.get("required", [])]
        marker = root / spec["completion_marker"] if spec.get("completion_marker") else None
        records.append(
            {
                "component": name,
                "root": str(root),
                "python": str(python),
                "root_exists": root.is_dir(),
                "python_exists": python.is_file(),
                "python_size": python.stat().st_size if python.is_file() else 0,
                "completion_marker": str(marker) if marker else None,
                "completion_marker_exists": marker.is_file() if marker else True,
                "required": [
                    {
                        "path": str(path),
                        "exists": path.is_file(),
                        "size": path.stat().st_size if path.is_file() else 0,
                    }
                    for path in required
                ],
            }
        )
    return records
