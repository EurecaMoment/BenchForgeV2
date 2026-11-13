"""Entry point for updating an existing DSH profile."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).parents[1] / 'dsh/hot_update.py'), run_name='__main__')
