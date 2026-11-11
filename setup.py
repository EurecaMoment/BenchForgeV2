"""Bundle the shared, dependency-free scene contract in standalone core wheels."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        # Editable installs load the shared contract from the checkout through
        # scene_policy; setuptools does not create a wheel's package tree here.
        if self.editable_mode:
            return
        source = Path(__file__).parent / 'components/spatialforge/src/spatialforge/scene_design.py'
        target = Path(self.build_lib) / 'benchforge_core/pipelines/_scene_design.py'
        self.copy_file(str(source), str(target))


setup(cmdclass={'build_py': BuildPy})
