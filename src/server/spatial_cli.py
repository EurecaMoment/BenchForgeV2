"""Run spatial data, curriculum, training and evaluation operations."""
import argparse
import json
import sys
from pathlib import Path
from capabilities.task_catalog.spatial import catalog
from capabilities.dataset_authoring.spatial.generation import generate
from capabilities.dataset_authoring.spatial.export import export
from capabilities.evaluation.spatial.evaluation import evaluate
from pipelines.spatial_learning.curriculum import curriculum
from pipelines.spatial_learning.training import train
from pipelines.spatial_learning.experiments import experiment
from server.training_monitor import monitor
from storage.workspace_jobs import WorkspaceJobs

OPERATIONS = {
    'spatial_catalog': catalog, 'spatial_generate': generate,
    'spatial_export': export, 'spatial_evaluate': evaluate,
    'curriculum': curriculum, 'spatial_train': train,
    'spatial_experiment': experiment, 'training_monitor': monitor,
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
