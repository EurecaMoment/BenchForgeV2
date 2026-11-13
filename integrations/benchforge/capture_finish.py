"""Entry point for the backend's capture acknowledgement command."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    integrations = Path(__file__).resolve().parents[1]
    adapter = integrations.parent / 'components/benchforge/src/benchforge_backend/dispatcher_control.py'
    if not adapter.is_file():
        adapter = integrations / 'dist/dispatcher/capture_finish.py'
    if adapter.is_file():
        runpy.run_path(str(adapter), run_name='__main__')
    else:
        runpy.run_module('benchforge_backend.dispatcher_control', run_name='__main__', alter_sys=True)
