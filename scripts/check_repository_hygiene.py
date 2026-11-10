"""Reject private configuration and disposable artifacts in the Git index.

Only tracked path names are inspected. This does not scan media, calculate
checksums, or attempt to replace a dedicated secret scanner.
"""

from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


GENERATED_DIRECTORIES = {
    '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', '.deployment', '.benchforge', '.spatialforge',
    'test-results', 'playwright-report',
}
DISPOSABLE_ROOTS = {'work', 'outputs', 'tmp', 'temp', 'runs', 'build', 'dist'}
PRIVATE_NAME = re.compile(r'\.local\.(json|ya?ml)$|\.bak($|[-.])|\.backup$')
GENERATED_SUFFIXES = {'.pyc', '.pyo', '.log', '.sqlite', '.sqlite3', '.db', '.whl', '.tgz'}


def rejection(path):
    file = PurePosixPath(path)
    if any(part in GENERATED_DIRECTORIES for part in file.parts):
        return 'generated dependency/runtime/test directory'
    if file.parts and file.parts[0] in DISPOSABLE_ROOTS:
        return 'disposable output directory'
    if PRIVATE_NAME.search(file.name):
        return 'private configuration or backup'
    if file.name == '.env' or file.name.endswith('.env'):
        return 'private environment file'
    if file.suffix in GENERATED_SUFFIXES:
        return 'generated binary, log, database, or package'
    return None


def main():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=root, check=True, capture_output=True
    )
    paths = result.stdout.decode('utf-8').split('\0')
    problems = [(path, reason) for path in paths if path and (reason := rejection(path))]
    if problems:
        for path, reason in problems:
            print(f'{path}: {reason}', file=sys.stderr)
        return 1
    print('Tracked files contain no private configuration or disposable outputs.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
