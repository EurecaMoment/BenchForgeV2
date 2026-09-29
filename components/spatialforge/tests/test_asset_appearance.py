import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatialforge.generation import GenerationTools


class AssetAppearance(unittest.TestCase):
    def test_catalog_inspects_legacy_uv_without_rewriting_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = GenerationTools(tmp)
            folder = tools.assets / ('asset_' + 'a' * 16)
            folder.mkdir()
            original = json.dumps({'asset_id': folder.name, 'appearance': {'encoding': 'vertex_color'}})
            (folder / 'asset.json').write_text(original)
            (folder / 'mesh.json').write_text(json.dumps({'vertices': [[0, 0, 0], [1, 1, 1]], 'texcoords': [[0, 0], [0, 0]], 'bounds': [[0, 0, 0], [1, 1, 1]]}))
            info = tools.catalog()[0]['appearance']['transport']
            self.assertEqual(info['uv_state'], 'constant')
            self.assertEqual(info['desktop_sampling_candidate'], 'vertex_color_fallback')
            self.assertEqual((folder / 'asset.json').read_text(), original)

    def test_publish_reports_transported_texture_even_for_generated_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = GenerationTools(root)
            work = root / 'work'; work.mkdir()
            textures = work / 'textures'; textures.mkdir()
            (textures / 'albedo.png').write_bytes(b'test texture payload')
            mesh = {'coordinate_frame': 'z_up', 'watertight': True, 'vertices': [[0, 0, 0], [1, 1, 1]], 'texcoords': [[0, 0], [1, 1]], 'appearance': {'encoding': 'pbr_materials'}, 'materials': [{'textures': {'base_color': 'textures/albedo.png'}}]}
            conversion = work / 'mesh_data.json'; conversion.write_text(json.dumps(mesh))
            glb = work / 'portable.glb'; glb.write_bytes(b'test source payload')
            with patch.object(tools, '_convert', return_value=(conversion, glb)):
                asset = tools._publish({'label': 'fixture'}, work, glb, 'z_up', {'tools': ['fixture']}, 'generated')
            self.assertEqual(asset['appearance']['pbr_textures'], 'transported')
            self.assertEqual(asset['appearance']['desktop_texture_sampling'], 'pending_capture')
            self.assertEqual(asset['appearance']['transport']['desktop_sampling_candidate'], 'base_color_uv')
            self.assertEqual((tools.assets / asset['asset_id'] / 'textures/albedo.png').read_bytes(), b'test texture payload')


if __name__ == '__main__':
    unittest.main()
