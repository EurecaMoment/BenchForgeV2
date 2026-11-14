"""Run spatial data, curriculum, training and evaluation operations."""
import argparse
import json
import sys
from pathlib import Path
from spatial_learning import api
from service_access.workspace_jobs import WorkspaceJobs

OPERATIONS = {
    'spatial_catalog': api.catalog, 'spatial_generate': api.generate,
    'spatial_export': api.export, 'spatial_evaluate': api.evaluate,
    'curriculum': api.curriculum, 'spatial_train': api.train,
    'spatial_experiment': api.experiment, 'training_monitor': api.monitor,
}

class Runtime(WorkspaceJobs):
    def execute(self, tool, args, directory):
        return OPERATIONS[tool](args, directory, self.config)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=[*OPERATIONS, 'status'])
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--config')
    parser.add_argument('--input')
    args = parser.parse_args()
    request = json.load(sys.stdin) if args.input == '-' else json.loads(Path(args.input).read_text(encoding='utf8')) if args.input else {}
    config = json.loads(Path(args.config).read_text(encoding='utf8')) if args.config else {}
    runtime = Runtime(args.workspace, config)
    try:
        print(json.dumps(runtime.call(args.tool, request), ensure_ascii=False))
    finally:
        runtime.close()

if __name__ == '__main__':
    main()
