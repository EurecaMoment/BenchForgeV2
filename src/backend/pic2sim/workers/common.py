from __future__ import annotations

import argparse
import json
import re
import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pic2sim.io import read_json, write_json_atomic


_invocation = contextvars.ContextVar('worker_invocation', default=None)
_models = {}


@contextmanager
def invocation(request):
    """Single-request adapter shared by CLI workers and the serial resident server."""
    value = {'request': request, 'response': None}
    token = _invocation.set(value)
    try:
        yield value
    finally:
        _invocation.reset(token)


def cached_model(key, factory):
    # One-shot CLI behavior remains unchanged. A resident worker is pinned to
    # one model configuration, so a changed model cannot silently occupy more VRAM.
    if _invocation.get() is None:
        return factory()
    if key not in _models:
        if _models:
            raise ValueError('Resident model configuration changed; restart this service explicitly')
        _models[key] = factory()
    return _models[key]


def worker_arguments() -> argparse.Namespace:
    if _invocation.get() is not None:
        return argparse.Namespace(request=None, response=None)
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    return parser.parse_args()


def load_request(arguments: argparse.Namespace) -> dict[str, Any]:
    if _invocation.get() is not None:
        return _invocation.get()['request']
    return read_json(arguments.request)


def finish(arguments: argparse.Namespace, **payload: Any) -> None:
    if _invocation.get() is not None:
        _invocation.get()['response'] = {'status': 'ok', **payload}
        return
    write_json_atomic(arguments.response, {"status": "ok", **payload})


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Model did not return a JSON object: {text[:500]}")
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


def require_file(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path
