from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


RESOURCE_FILES = (
    ("BenchClaw/annotation-tool/default-annotation/run_image_to_semantic_depth.py", "resources/BenchClaw/annotation-tool/default-annotation/run_image_to_semantic_depth.py"),
    ("BenchClaw/annotation-tool/depthanything3/depthanything3_client.py", "resources/BenchClaw/annotation-tool/depthanything3/depthanything3_client.py"),
    ("BenchClaw/annotation-tool/llm-local/llm_local_client.py", "resources/BenchClaw/annotation-tool/llm-local/llm_local_client.py"),
    ("BenchClaw/annotation-tool/sam3/sam3_client.py", "resources/BenchClaw/annotation-tool/sam3/sam3_client.py"),
    ("BenchClaw/annotation-tool/sam3/sam3_service.py", "resources/BenchClaw/annotation-tool/sam3/sam3_service.py"),
    ("BenchClaw/annotation-tool/yoloe/yoloe_client.py", "resources/BenchClaw/annotation-tool/yoloe/yoloe_client.py"),
    ("BenchClaw/annotation-tool/yoloe/yoloe_service.py", "resources/BenchClaw/annotation-tool/yoloe/yoloe_service.py"),
    ("BenchClaw/templates/template_library/executable_template_coverage.json", "resources/BenchClaw/templates/template_library/executable_template_coverage.json"),
    ("BenchClaw/templates/tools/synthesize_static_vlm_benchmark.py", "resources/BenchClaw/templates/tools/synthesize_static_vlm_benchmark.py"),
    ("BenchClaw/tools/cdm_irt_analysis.py", "resources/BenchClaw/tools/cdm_irt_analysis.py"),
    ("BenchClaw/tools/gt_kinship_base.py", "resources/BenchClaw/tools/gt_kinship_base.py"),
    ("BenchClaw/simulatorCards/CARLA/quick_capture.py", "resources/BenchClaw/simulatorCards/CARLA/quick_capture.py"),
    ("examples/minimal/dataset.yaml", "resources/examples/minimal/dataset.yaml"),
)


class BuildPy(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        package = Path(self.build_lib) / "benchclaw"
        for source_name, target_name in RESOURCE_FILES:
            source = root / source_name
            if not source.is_file():
                raise FileNotFoundError(f"BenchClaw wheel resource is missing: {source}")
            target = package / target_name
            self.mkpath(str(target.parent))
            self.copy_file(str(source), str(target))


setup(cmdclass={"build_py": BuildPy})
