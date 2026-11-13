"""Artifact helpers shared by callable production capabilities."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from .artifact_io import read_json, read_jsonl, write_json, write_jsonl
    from .processes import terminate_process_tree
else:
    from artifact_io import read_json, read_jsonl, write_json, write_jsonl
    from processes import terminate_process_tree

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
