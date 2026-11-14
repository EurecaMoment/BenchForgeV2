"""Store training events and operator guidance in the run directory."""
import json
from datetime import datetime
from datetime import timezone
from pathlib import Path

from storage.artifacts import write_json


def emit(run, event, **fields):
    path = Path(run) / 'events.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
    with path.open('a', encoding='utf8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


def snapshot(run):
    path = Path(run) / 'events.jsonl'
    events = []
    if path.exists():
        with path.open(encoding='utf8') as handle:
            events = [json.loads(line) for line in handle if line.endswith('\n')]
    return {'events': events, 'latest': events[-1] if events else None}


def read_guidance(run):
    path = Path(run) / 'guidance.json'
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}


def guide(run, settings):
    guidance = {**read_guidance(run), **settings}
    write_json(Path(run) / 'guidance.json', guidance)
    emit(run, 'guidance_received', settings=settings)
    return guidance
