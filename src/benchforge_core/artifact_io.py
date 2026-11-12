"""Small JSON artifacts with atomic replacement for concurrent readers.

Each file update is atomic. A workflow still needs an execution lock to
coordinate changes to several files and external services.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import uuid


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


@contextmanager
def atomic_text(path):
    """Publish a complete UTF-8 file, preserving the old file on write failure."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            if destination.exists():
                os.chmod(temporary, stat.S_IMODE(destination.stat().st_mode))
            yield stream
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    with atomic_text(path) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path, values):
    with atomic_text(path) as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
