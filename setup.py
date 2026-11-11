"""Bundle the shared, dependency-free scene contract in standalone core wheels."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent / 'components/spatialforge/src/spatialforge/scene_design.py'
        target = Path(self.build_lib) / 'benchforge_core/pipelines/_scene_design.py'
        target.parent.mkdir(parents=True, exist_ok=True)
        self.copy_file(str(source), str(target))


setup(cmdclass={'build_py': BuildPy})
