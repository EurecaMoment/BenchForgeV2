"""Atomic JSON writes and confined paths for BenchForge artifacts."""

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4


def safe_path(root: Path, relative: str, must_exist: bool = False) -> Path:
    root = root.resolve()
    rel = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or rel.is_absolute()
        or any(part in {".", ".."} for part in relative.split("/"))
    ):
        raise ValueError(f"Invalid relative artifact path: {relative}")
    path = root
    for part in rel.parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"Symlinks are forbidden: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Artifact path escapes its root: {relative}")
    if must_exist and not path.is_file():
        raise FileNotFoundError(relative)
    return path


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp_{uuid4().hex}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
