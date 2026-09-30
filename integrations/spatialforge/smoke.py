"""Exercise the HTTP client and real delivery-review code without GPU/model calls."""
import shutil
import subprocess
import sys
from pathlib import Path

def main():
    root = Path(__file__).resolve().parent
    node = shutil.which('node')
    if not node:
        raise SystemExit('Install Node.js 22.19+ or 24+ to test the DSH review code')
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(root/'tests'), '-v'], check=True)
    subprocess.run([node, '--test', *map(str, sorted((root/'tests').glob('test_*.mjs')))], check=True)
    print('PASS: HTTP contract and delivery-review regressions. No model or Isaac execution.')

if __name__ == '__main__':
    main()
