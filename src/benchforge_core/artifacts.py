"""Artifact helpers shared by callable production capabilities."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import signal
from pathlib import Path

VENDOR = Path(__file__).with_name('vendor') / 'benchclaw'
BUILD = VENDOR / 'compiler'
COMPILER = BUILD


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def rows(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def jsonl(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False)+'\n')


def run(script, argv, directory, *, config=None, env=None, timeout=600, name=None, accepted=(0,)):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = name or Path(script).stem
    command = list((config or {}).get('python_command', [sys.executable])) + [str(script), *map(str, argv)]
    write(directory/(stem+'.command.json'), {'command':command})
    with (directory/(stem+'.stdout.log')).open('w',encoding='utf-8') as out, (directory/(stem+'.stderr.log')).open('w',encoding='utf-8') as err:
        kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NO_WINDOW}
        result = subprocess.Popen(command,cwd=directory,env={**os.environ,'PYTHONUTF8':'1',**(env or {})},stdout=out,stderr=err,**kwargs)
        try:result.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name!='nt':
                try:os.killpg(result.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            else:result.terminate()
            result.wait(timeout=10)
            raise
    write(directory/(stem+'.exit.json'), {'exit_code':result.returncode})
    if result.returncode not in accepted:
        tail=(directory/(stem+'.stderr.log')).read_text(encoding='utf-8')[-3000:]
        tail+=(directory/(stem+'.stdout.log')).read_text(encoding='utf-8')[-2000:]
        raise RuntimeError(f'{stem} exited {result.returncode}; logs: {directory}; {tail}')
    return result.returncode


def inside(root, relative):
    path=(Path(root)/relative).resolve()
    path.relative_to(Path(root).resolve())
    return path


def unique(values, key='id'):
    result={}
    for row in values:
        identity=str(row[key])
        if not identity or identity in result:
            raise ValueError(f'Missing or duplicate {key}: {identity}')
        result[identity]=row
    return result
