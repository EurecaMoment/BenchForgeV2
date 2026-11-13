"""Entry point for the external dispatcher overlay installer."""
from pathlib import Path
import runpy
import sys


if __name__ == '__main__':
    directory = Path(__file__).resolve().parents[2] / 'components/benchforge/deploy/dispatcher'
    sys.path.insert(0, str(directory))
    runpy.run_path(str(directory / 'deploy_dispatcher_overlay.py'), run_name='__main__')
