"""Compatibility import for external dispatchers with an existing overlay."""
from pathlib import Path
import runpy


_path = Path(__file__).resolve().parents[2] / 'components/benchforge/deploy/dispatcher/dispatcher_overlay.py'
_overlay = runpy.run_path(str(_path))
CanonicalControl = _overlay['CanonicalControl']
ControlAdapterError = _overlay['ControlAdapterError']
OVERLAY_VERSION = _overlay['OVERLAY_VERSION']
