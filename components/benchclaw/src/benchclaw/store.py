"""Immutable local artifacts; UUID identities, atomic directory commits, no hashes."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import ArtifactRef, HarnessError, uid


def safe_path(root: Path, relative: str, must_exist: bool = False) -> Path:
    root = root.resolve()
    rel = PurePosixPath(relative)
    if not relative or '\\' in relative or ':' in relative or rel.is_absolute() or any(p in {'.', '..'} for p in relative.split('/')):
        raise HarnessError('PATH_ESCAPE', f'Invalid relative artifact path: {relative}')
    path = root
    for part in rel.parts:
        path /= part
        if path.is_symlink():
            raise HarnessError('PATH_SYMLINK', f'Symlinks are forbidden: {relative}')
    if not path.resolve().is_relative_to(root):
        raise HarnessError('PATH_ESCAPE', relative)
    if must_exist and not path.is_file():
        raise HarnessError('ARTIFACT_MISSING', relative)
    return path


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{uid("tmp")}')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def staging(self, run_id: str, task_id: str, token: str) -> Path:
        return safe_path(self.root, f'staging/{run_id}/{task_id}/{token}')

    def destination(self, run_id: str, task_id: str, token: str) -> Path:
        return safe_path(self.root, f'runs/{run_id}/{task_id}/{token}')

    def allocate(self, run_id: str, task_id: str, token: str) -> Path:
        path = self.staging(run_id, task_id, token)
        path.mkdir(parents=True, exist_ok=False)
        path.chmod(0o700)
        return path

    def inventory(self, directory: Path) -> dict[str, int]:
        files = {}
        for path in directory.rglob('*'):
            rel = path.relative_to(directory).as_posix()
            safe_path(directory, rel)
            if path.is_file() and rel != 'receipt.json':
                size = path.stat().st_size
                if size == 0:
                    raise HarnessError('EMPTY_ARTIFACT', rel)
                files[rel] = size
        if not files:
            raise HarnessError('EMPTY_ARTIFACT', str(directory))
        return files

    def commit(self, run_id: str, task_id: str, token: str, result: dict) -> ArtifactRef:
        stage = self.staging(run_id, task_id, token)
        final = self.destination(run_id, task_id, token)
        files = self.inventory(stage)
        ref = ArtifactRef(artifact_id=token, run_id=run_id, work_item_id=task_id,
                          uri=final.relative_to(self.root).as_posix(), byte_size=sum(files.values()),
                          files=files, revision=token)
        write_json(stage / 'receipt.json', {'artifact': ref.model_dump(), 'result': result})
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            raise HarnessError('IMMUTABLE_ARTIFACT', ref.uri)
        os.rename(stage, final)
        if os.name == 'posix':
            fd = os.open(final.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return ref

    def recover(self, run_id: str, task_id: str, token: str):
        final = self.destination(run_id, task_id, token)
        receipt = safe_path(final, 'receipt.json')
        if not receipt.is_file():
            return None
        data = json.loads(receipt.read_text())
        ref = ArtifactRef.model_validate(data['artifact'])
        if (ref.run_id, ref.work_item_id, ref.artifact_id) != (run_id, task_id, token):
            raise HarnessError('RECEIPT_IDENTITY', 'Receipt identity mismatch')
        self.verify(ref)
        return ref, data['result']

    def verify(self, ref: ArtifactRef) -> Path:
        directory = safe_path(self.root, ref.uri)
        if self.inventory(directory) != ref.files:
            raise HarnessError('ARTIFACT_CHANGED', ref.uri)
        return directory

    def read(self, ref: ArtifactRef, relative: str) -> Path:
        if relative not in ref.files:
            raise HarnessError('UNDECLARED_ARTIFACT', relative)
        return safe_path(safe_path(self.root, ref.uri), relative, True)
