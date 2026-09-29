"""Focused transport tests; no GPU or model API is involved."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import trimesh
from spatialforge.mesh_export import export_mesh
from spatialforge.mesh_appearance import inspect_mesh_appearance


class MeshTransport(unittest.TestCase):
    def test_pbr_uv_and_texture_payload_survive_export(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            texture = Image.new('RGBA', (2, 2), (220, 30, 40, 255))
            mesh = trimesh.creation.box()
            uv = np.tile([[0., 0.], [1., 0.], [1., 1.], [0., 1.]], (len(mesh.vertices) // 4 + 1, 1))[:len(mesh.vertices)]
            material = trimesh.visual.material.PBRMaterial(name='paint', baseColorTexture=texture, metallicFactor=.25, roughnessFactor=.35)
            mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, material=material)
            source = root / 'textured.glb'
            source.write_bytes(mesh.export(file_type='glb'))
            record = export_mesh(source, root / 'mesh.json', root / 'portable.glb', 'z_up')
            self.assertEqual(len(record['texcoords']), len(record['vertices']))
            self.assertEqual(record['appearance']['encoding'], 'pbr_materials')
            self.assertEqual(record['materials'][0]['metallic_factor'], .25)
            texture_rel = record['materials'][0]['textures']['base_color']
            self.assertTrue((root / texture_rel).is_file())
            self.assertGreater((root / texture_rel).stat().st_size, 0)

    def test_vertex_colors_and_scene_instances_survive_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = trimesh.creation.box(extents=[1, 2, 3])
            mesh.visual.vertex_colors = [255, 0, 0, 255]
            scene = trimesh.Scene()
            scene.add_geometry(mesh, node_name='left')
            transform = np.eye(4)
            transform[0, 3] = 10
            scene.add_geometry(mesh, node_name='right', transform=transform)
            source = root / 'source.glb'
            source.write_bytes(scene.export(file_type='glb'))
            record = export_mesh(source, root / 'mesh.json', root / 'portable.glb', 'z_up')
            self.assertEqual(len(record['faces']), 24)
            self.assertAlmostEqual(record['bounds'][1][0], 10.5)
            self.assertEqual(record['colors'][0], [1., 0., 0.])
            self.assertTrue((root / 'portable.glb').is_file())
            self.assertEqual(record['texcoords'], [])
            self.assertEqual(inspect_mesh_appearance(record)['uv_origin'], 'absent_in_source')

    def test_obj_diffuse_image_is_transported_without_resampling(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixels = np.array([[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [240, 220, 10]]], dtype=np.uint8)
            Image.fromarray(pixels).save(root / 'pattern.png')
            (root / 'source.mtl').write_text('newmtl patterned\nKd 1 1 1\nNs 20\nmap_Kd pattern.png\n')
            source = root / 'source.obj'
            source.write_text('mtllib source.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nusemtl patterned\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n')
            record = export_mesh(source, root / 'converted/mesh.json', root / 'portable.glb', 'z_up')
            material = record['materials'][0]
            with Image.open(root / 'converted' / material['textures']['base_color']) as actual:
                np.testing.assert_array_equal(actual.convert('RGB'), pixels)
            np.testing.assert_allclose(record['texcoords'], [[0, 0], [1, 0], [1, 1], [0, 1]])
            self.assertEqual(material['source_material_type'], 'SimpleMaterial')
            self.assertEqual(inspect_mesh_appearance(record)['desktop_sampling_candidate'], 'base_color_uv')

    def test_texture_without_source_uv_is_not_silently_mapped_to_zero(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            mesh = trimesh.creation.box()
            mesh.visual = trimesh.visual.texture.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB', (2, 2), 'red')))
            with patch('spatialforge.mesh_export.trimesh.load', return_value=trimesh.Scene(mesh)):
                with self.assertRaisesRegex(ValueError, 'no valid source UVs'):
                    export_mesh(Path(tmp) / 'source.glb', Path(tmp) / 'mesh.json')
            self.assertFalse((Path(tmp) / 'mesh.json').exists())

    def test_legacy_zero_uv_is_identified_without_claiming_capture(self):
        record = {'vertices': [[0, 0, 0], [1, 0, 0]], 'texcoords': [[0, 0], [0, 0]], 'materials': [{'textures': {'normal': 'textures/normal.png'}}]}
        result = inspect_mesh_appearance(record)
        self.assertEqual(result['uv_state'], 'constant')
        self.assertEqual(result['uv_origin'], 'legacy_origin_unrecorded')
        self.assertEqual(result['desktop_sampling_candidate'], 'pbr_texture_uv')
        self.assertEqual(result['transport_only_texture_slots'], [])
        self.assertIn('transport inspection', result['scope'])

    def test_y_up_conversion_keeps_positive_handedness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = trimesh.creation.box(extents=[1, 2, 3])
            source = root / 'source.glb'
            source.write_bytes(mesh.export(file_type='glb'))
            record = export_mesh(source, root / 'mesh.json', source_frame='y_up')
            converted = trimesh.Trimesh(vertices=record['vertices'], faces=record['faces'], process=False)
            self.assertGreater(converted.volume, 0)
            np.testing.assert_allclose(converted.extents, [1, 3, 2])
            self.assertEqual(record['coordinate_frame'], 'z_up')

    def test_sam3d_camera_coordinates_remain_declared_for_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mesh = trimesh.creation.box(extents=[1, 2, 3])
            source = root / 'source.glb'
            source.write_bytes(mesh.export(file_type='glb'))
            record = export_mesh(source, root / 'mesh.json')
            np.testing.assert_allclose(record['bounds'], mesh.bounds)
            self.assertEqual(record['coordinate_frame'], 'sam3d_camera')


if __name__ == '__main__':
    unittest.main()
