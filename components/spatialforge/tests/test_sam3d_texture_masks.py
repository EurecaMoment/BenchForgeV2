import unittest
import torch
from spatialforge.sam3d_texture_baking import view_samples


class TextureMaskTests(unittest.TestCase):
    def test_asymmetric_raster_and_per_view_masks_remain_aligned(self):
        # utils3d UV is bottom-up, while its mask is already top-down.
        # The two observations expose different pixels; keep per-view masks.
        uv=torch.tensor([[[.1,.1],[.8,.1]],[[.1,.8],[.8,.8]]])
        raster=torch.tensor([[1,1],[0,0]])
        image=torch.tensor([[[1.,0,0],[0,1.,0]],[[0,0,1.],[1.,1,1.]]])
        first=torch.tensor([[1,0],[0,0]])
        second=torch.tensor([[0,1],[0,0]])
        i,c=view_samples(uv,raster,image,first,2)
        self.assertEqual(i.tolist(),[0]);self.assertEqual(c.tolist(),[[1.,0,0]])
        i,c=view_samples(uv,raster,image,second,2)
        self.assertEqual(i.tolist(),[1]);self.assertEqual(c.tolist(),[[0,1.,0]])

    def test_uv_boundary_samples_last_texel(self):
        uv=torch.tensor([[[1.,1.]]]);mask=torch.ones((1,1))
        i,c=view_samples(uv,mask,torch.tensor([[[.2,.4,.6]]]),mask,4)
        self.assertEqual(i.tolist(),[3])


if __name__=='__main__':unittest.main()
