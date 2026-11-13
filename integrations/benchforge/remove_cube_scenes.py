"""Entry point for the scene library maintenance command."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('maintenance') / 'remove_cube_scenes.py'), run_name='__main__')
