"""Entry point for the question set maintenance command."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('maintenance') / 'rewrite_question_set.py'), run_name='__main__')
