"""Entry point for installing the DSH workbench."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).parents[1] / 'dsh/install_workbench.py'), run_name='__main__')
