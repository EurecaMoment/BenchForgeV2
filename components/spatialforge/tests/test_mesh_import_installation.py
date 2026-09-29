import json
from pathlib import Path
import tempfile
import unittest

import trimesh
from spatialforge.generation import GenerationTools


class MeshImportInstallation(unittest.TestCase):
    def test_mesh_conversion_needs_no_model_config_or_sam3d_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'cube.glb'
            trimesh.creation.box(extents=[.2,.3,.4]).export(source)
            tools = GenerationTools(root)
            converted, portable = tools._convert(source, root, 'z_up')
            result = json.loads(converted.read_text())
            self.assertTrue(result['vertices'])
            self.assertTrue(portable.is_file())
            loaded = trimesh.load(portable, force='mesh')
            self.assertEqual(len(loaded.faces), 12)


if __name__ == '__main__':
    unittest.main()
