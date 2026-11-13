"""Round-trip preservation checks for the lossless PNG/GLB export path."""
from pathlib import Path
import tempfile
import unittest
import importlib.util

import numpy as np
from PIL import Image
import trimesh

from benchforge_backend.trellis_export import export_glb_lossless, inpaint_pbr_channels


class LosslessExportTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV is required for inpainting')
    def test_parallel_inpaint_is_pixel_identical_to_original_channel_operations(self):
        import cv2
        rng = np.random.default_rng(317)
        channels = [rng.integers(0, 256, (96, 96, 3), dtype=np.uint8)] + [
            rng.integers(0, 256, (96, 96, 1), dtype=np.uint8) for _ in range(3)]
        mask = np.zeros((96, 96), dtype=np.uint8)
        mask[10:70, 30:60] = 1
        expected = [cv2.inpaint(value, mask, radius, cv2.INPAINT_TELEA)
                    for value, radius in zip(channels, [3, 1, 1, 1])]
        actual = inpaint_pbr_channels(*channels, mask)
        for index, (left, right) in enumerate(zip(actual, expected)):
            np.testing.assert_array_equal(left, right if index == 0 else right[..., None])

    def test_geometry_uvs_and_both_pbr_images_survive_the_real_glb_round_trip(self):
        rng = np.random.default_rng(412)
        color = rng.integers(0, 256, (64, 64, 4), dtype=np.uint8)
        material = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
        pbr = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(color),
            metallicRoughnessTexture=Image.fromarray(material), metallicFactor=1., roughnessFactor=1.)
        mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]],
            process=False, visual=trimesh.visual.TextureVisuals(uv=[[0, 0], [1, 0], [0, 1]], material=pbr))
        before = [image.save for image in (pbr.baseColorTexture, pbr.metallicRoughnessTexture)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset.glb'
            timing = export_glb_lossless(mesh, path)
            loaded = trimesh.load(path, force='mesh', process=False)
            np.testing.assert_array_equal(loaded.vertices, mesh.vertices)
            np.testing.assert_array_equal(loaded.faces, mesh.faces)
            np.testing.assert_array_equal(loaded.visual.uv, mesh.visual.uv)
            np.testing.assert_array_equal(np.asarray(loaded.visual.material.baseColorTexture), color)
            np.testing.assert_array_equal(np.asarray(loaded.visual.material.metallicRoughnessTexture), material)
        self.assertEqual(timing['png_images'], 2)
        after = [image.save for image in (pbr.baseColorTexture, pbr.metallicRoughnessTexture)]
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
