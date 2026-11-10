"""Build and smoke-test the independently installable Python release artifacts."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run(args, *, cwd, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def stage_root_context(destination):
    dockerfile = ROOT / "Dockerfile"
    copy_file(dockerfile, destination / "Dockerfile")
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        parts = shlex.split(line)
        if not parts or parts[0].upper() != "COPY":
            continue
        for source_name in parts[1:-1]:
            source = ROOT / source_name
            target = destination / source_name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                copy_file(source, target)


def stage_component(source, destination, names):
    destination.mkdir(parents=True)
    for name in names:
        item = source / name
        target = destination / name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            copy_file(item, target)


def main():
    with tempfile.TemporaryDirectory(prefix="benchforge-release-") as temporary:
        temp = Path(temporary)
        wheels = temp / "wheels"
        wheels.mkdir()

        root_context = temp / "docker-context"
        root_context.mkdir()
        stage_root_context(root_context)
        run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps",
             "--wheel-dir", str(wheels), str(root_context)], cwd=temp)

        benchclaw = ROOT / "components/benchclaw"
        benchclaw_stage = temp / "benchclaw"
        stage_component(benchclaw, benchclaw_stage,
                        ("pyproject.toml", "setup.py", "src", "BenchClaw", "examples"))
        run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps",
             "--wheel-dir", str(wheels), str(benchclaw_stage)], cwd=temp)

        spatialforge_stage = temp / "spatialforge"
        stage_component(ROOT / "components/spatialforge", spatialforge_stage, ("pyproject.toml", "src"))
        run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps",
             "--wheel-dir", str(wheels), str(spatialforge_stage)], cwd=temp)

        artifacts = sorted(wheels.glob("*.whl"))
        expected = {"benchforge", "benchclaw_harness", "spatialforge"}
        found = {wheel.name.split("-", 1)[0].replace("-", "_") for wheel in artifacts}
        if found != expected:
            raise RuntimeError(f"Expected wheels {sorted(expected)}, found {sorted(found)}")

        install = temp / "installed"
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps",
             "--target", str(install), *(str(wheel) for wheel in artifacts)], cwd=temp)

        probe = temp / "probe"
        probe.mkdir()
        env = {**os.environ, "PYTHONPATH": str(install)}
        code = r"""
import importlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from benchclaw.resources import resource_path
from benchclaw.template_engine import catalogue

importlib.import_module('benchforge_core.pipelines._scene_design')
importlib.import_module('spatialforge.observation')
assert catalogue()['templates']
resources = (
    'BenchClaw/annotation-tool/default-annotation/run_image_to_semantic_depth.py',
    'BenchClaw/annotation-tool/depthanything3/depthanything3_client.py',
    'BenchClaw/annotation-tool/llm-local/llm_local_client.py',
    'BenchClaw/annotation-tool/sam3/sam3_client.py',
    'BenchClaw/annotation-tool/sam3/sam3_service.py',
    'BenchClaw/annotation-tool/yoloe/yoloe_client.py',
    'BenchClaw/annotation-tool/yoloe/yoloe_service.py',
    'BenchClaw/templates/template_library/executable_template_coverage.json',
    'BenchClaw/templates/tools/synthesize_static_vlm_benchmark.py',
    'BenchClaw/tools/cdm_irt_analysis.py',
    'BenchClaw/tools/gt_kinship_base.py',
    'BenchClaw/simulatorCards/CARLA/quick_capture.py',
    'examples/minimal/dataset.yaml',
)
assert all(resource_path(*name.split('/')).is_file() for name in resources)
from benchclaw.cli import main
spec = Path(sys.argv[1]) / 'initialized.yaml'
with redirect_stdout(io.StringIO()):
    assert main(['init', str(spec)]) == 0
saved = yaml.safe_load(spec.read_text(encoding='utf-8'))
assert saved['sources'][0]['parameters']['path'] == './images'
with redirect_stdout(io.StringIO()):
    assert main(['plan', str(spec)]) == 0
"""
        run([sys.executable, "-c", code, str(probe)], cwd=probe, env=env)

    print("Built and smoke-tested independent BenchForge, BenchClaw, and SpatialForge wheels.")


if __name__ == "__main__":
    main()
