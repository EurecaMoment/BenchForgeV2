import unittest
from pxr import Usd,UsdShade
from material_controls import apply_texture_tint
from scene_runtime import material_for


class TextureTint(unittest.TestCase):
    def test_named_tint_authors_only_local_texture_rgb_scale(self):
        stage=Usd.Stage.CreateInMemory()
        a=UsdShade.Shader.Define(stage,'/A');a.CreateIdAttr('UsdUVTexture')
        b=UsdShade.Shader.Define(stage,'/B');b.CreateIdAttr('UsdUVTexture')
        unchanged=stage.GetRootLayer().ExportToString()
        self.assertEqual(apply_texture_tint(a,{}),[1,1,1])
        self.assertEqual(stage.GetRootLayer().ExportToString(),unchanged)
        p={'materials':[{'id':'wood','appearance':{'texture_id':'wood_laminate','texture_tint':[.4,.25,.12]}}]}
        appearance=material_for(p,{'material_id':'wood','appearance':{'texture_tint':[.5,.25,.125]}})['appearance']
        self.assertEqual(apply_texture_tint(a,appearance),[.5,.25,.125])
        self.assertEqual(tuple(a.GetInput('scale').Get()),(.5,.25,.125,1))
        self.assertFalse(b.GetInput('scale'))
        self.assertFalse(a.GetInput('bias'))

if __name__=='__main__':unittest.main()
