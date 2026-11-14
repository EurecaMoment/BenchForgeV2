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
import subprocess
import sys
import uuid

if __package__:
    from service_access.processes import terminate_process_tree
else:
    from processes import terminate_process_tree


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


read = read_json
rows = read_jsonl
write = write_json
jsonl = write_jsonl


def run(script, argv, directory, *, config=None, env=None, timeout=600, name=None, accepted=(0,)):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = name or Path(script).stem
    command = list((config or {}).get('python_command', [sys.executable])) + [str(script), *map(str, argv)]
    write(directory/(stem+'.command.json'), {'command':command})
    with (directory/(stem+'.stdout.log')).open('w',encoding='utf-8') as out, (directory/(stem+'.stderr.log')).open('w',encoding='utf-8') as err:
        kwargs = {'start_new_session': True} if os.name != 'nt' else {
            'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        }
        result = subprocess.Popen(
            command, cwd=directory,
            env={**os.environ, 'PYTHONUTF8': '1', **(env or {})},
            stdout=out, stderr=err, **kwargs,
        )
        try:result.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process_tree(result)
            raise
    write(directory/(stem+'.exit.json'), {'exit_code':result.returncode})
    if result.returncode not in accepted:
        tail=(directory/(stem+'.stderr.log')).read_text(encoding='utf-8')[-3000:]
        tail+=(directory/(stem+'.stdout.log')).read_text(encoding='utf-8')[-2000:]
        raise RuntimeError(f'{stem} exited {result.returncode}; logs: {directory}; {tail}')
    return result.returncode


def unique(values, key='id'):
    result={}
    for row in values:
        identity=str(row[key])
        if not identity or identity in result:
            raise ValueError(f'Missing or duplicate {key}: {identity}')
        result[identity]=row
    return result


def select(raw, pointer):
    if pointer and not pointer.startswith('/'):
        raise ValueError('Selectors use RFC 6901 JSON pointers')
    value = raw
    for part in pointer.split('/')[1:]:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value
