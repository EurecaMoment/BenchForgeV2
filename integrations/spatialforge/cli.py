"""Read real SpatialForge status through its authenticated POST API."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

def load_config(path=None):
    path = path or os.environ.get('SPATIALFORGE_CONFIG')
    if not path:
        raise ValueError('Set SPATIALFORGE_CONFIG or pass --config PATH')
    return json.loads(Path(path).read_text(encoding='utf-8'))

def status(config, run_id=None):
    token = config.get('operator_token')
    if not token:
        raise ValueError('Configure operator_token in the SpatialForge configuration file')
    route, payload = ('/observe', {'run_id': run_id}) if run_id else ('/catalog', {})
    request = Request(config['service_url'].rstrip('/') + route,
                      data=json.dumps(payload).encode(),
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--run-id', help='Existing run ID, excluding .sceneN')
    args = parser.parse_args()
    print(json.dumps(status(load_config(args.config), args.run_id), ensure_ascii=False))

if __name__ == '__main__':
    main()
