"""Generate the SpatialForge development mode with its existing learning tools."""
import argparse
import importlib.util
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('benchforge_preset', ROOT / 'integrations/dsh/build_preset.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

LEARNING_TOOLS = ['spatial_catalog', 'spatial_generate', 'spatial_export', 'spatial_evaluate',
                  'curriculum', 'spatial_train', 'spatial_experiment', 'training_monitor',
                  'pipeline_catalog', 'pipeline_plan', 'pipeline_run', 'pipeline_status', 'pipeline_evaluate']

PERSONA = """You operate SpatialForge to produce scenes and data with the user.
Keep the standard conversational interaction: explain meaningful decisions and show useful artifacts. Choose direct tools, task code, run_code or available subagents according to the objective; independent work can run in parallel when the shared workspace and execution ownership are clear.
Use persistent shells when a sequence benefits from a retained environment. Filesystem, jobs, file tools and runtime inspection remain available. Use SpatialForge tools for production operations; the configured queue owns the connected desktop Isaac instance.
Diffusion, SAM3, SAM3D, depth, mesh import, geometry preview, capture, run and asset operations are composable capabilities. Inspect the returned images and artifacts, then select the representation and next operation that fit the scene. Gaussian, mesh and paired assets are all valid when their appearance, physics and portability meet the request; do not impose a representation that the task does not need.
Use an existing reference when supplied and create or reuse a design reference when it helps the requested result. A reference guides composition and appearance; native Isaac, task programs and official records provide the relevant geometry or GT. Build and revise SceneProgram from observed evidence, and keep useful references linked to later captures.
Share concise progress through spatialforge_collaboration: publish role, inputs, findings, artifacts, blockers, decisions and next actions, and reply to or relate other handoffs when agents work in parallel. This is a shared record rather than a fixed workflow or approval gate.
Keep the objective open while a requested deliverable is missing or a repairable gap remains; a successful tool call, capture, or checked TODO is not completion. At the end of a turn, give a formal user-facing delivery note with the outcome, evidence and artifacts, plus any unresolved blocker or next action. Do not expose scratch reasoning or present a TODO list as the final result.
Task code and scene inputs are editable. Preserve the configured service, acceptance rules and GT provenance. Do not call target-model evaluation APIs. Use actual images and simulation evidence for visual and physical claims, and distinguish capture completion, data export, scene quality and interaction evidence in the delivery.
For capability-based data production, use pipeline_catalog's user-supplied 89-task/267-template registry. Interpret the user objective, select exact templates and record selections with counts and reasons in pipeline_plan. Capability links are candidate associations; preserve each template's measurement conditions and output. Compose pipeline steps through their artifacts, execute/resume with pipeline_run and inspect pipeline_status. A waiting or needs_evidence state is unfinished work: produce the required exact evidence using task code, official data or the existing Isaac queue, then resume. Do not silently substitute legacy synthetic templates for these protocols. Preserve interactive episodes and history access rules; a static action answer cannot satisfy an interactive task.
"""


def build(sources, dsh_root, python, service_config, *, package_imports=False):
    result = base.build(sources, dsh_root, python, service_config, package_imports=package_imports)
    preset = result[0]['insert'][0]
    preset['id'] = 'preset-spatialforge-standard-ptc'
    config = preset['config']
    config.update(id='spatialforge-standard-ptc', name='SpatialForge', order=-1,
                  description='Development branch: Standard, PTC, persistent shell, SpatialForge and spatial learning.')
    plugins = config['plugins']
    persona = next(row for row in plugins if row['id'] == 'persona')
    persona['config'].update(prefix=PERSONA, suffix='Your working directory is {{cwd}}. You are using {{model}}.')
    learning = next(row for row in plugins if row['id'] == 'benchforge-tools')
    learning['id'] = 'spatial-learning-tools'
    learning['config'] = {'python': python, 'includeTools': LEARNING_TOOLS}
    plugins.append({'id': 'spatialforge-tools',
                    'name': '@eurecamoment/benchforge-dsh/spatialforge-tools' if package_imports else str(ROOT / 'integrations/spatialforge/plugin/tools.mjs'),
                    'config': {'serviceConfig': str(service_config.resolve())}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base.add_source_arguments(parser)
    parser.add_argument('--python', required=True)
    parser.add_argument('--service-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sources = base.load_sources(args.dsh_root, args.node, args.dsh_resolve_from)
    result = build(sources, args.dsh_root, args.python, args.service_config)
    args.output.write_text(yaml.dump(result, Dumper=base.Dumper, sort_keys=False, allow_unicode=True), encoding='utf-8')


if __name__ == '__main__':
    main()
