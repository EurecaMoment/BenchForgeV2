"""Compatibility import for installed external dispatcher patches."""
from pathlib import Path
import runpy


_path = Path(__file__).resolve().parents[2] / 'components/benchforge/deploy/dispatcher/worker_cancellation.py'
finish_canceled_capture = runpy.run_path(str(_path))['finish_canceled_capture']
