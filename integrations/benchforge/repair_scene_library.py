"""Entry point for the scene repair maintenance command."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('maintenance') / 'repair_scene_library.py'), run_name='__main__')
