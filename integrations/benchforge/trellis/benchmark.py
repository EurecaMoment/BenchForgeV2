"""Entry point for the TRELLIS deployment benchmark."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    source = Path(__file__).resolve().parents[3] / 'components/benchforge/deploy/trellis/benchmark.py'
    runpy.run_path(str(source), run_name='__main__')
