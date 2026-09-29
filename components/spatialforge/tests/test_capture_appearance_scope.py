"""Exercise the capture's USD authoring functions without starting Kit."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade, Vt

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from imported_appearance import bind_imported_materials
from material_controls import apply_dielectric_controls, apply_texture_tint
from spatialforge.mesh_geometry import transform_mesh_geometry, transform_mesh_normals


class CaptureAppearanceScopeTests(unittest.TestCase):
    def test_receipt_matches_visible_gaussian_and_explicit_mesh_shader(self):
        source=Path(__file__).resolve().parents[1]/'desktop/isaac_capture.py'
        functions=[node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
                   if isinstance(node,ast.FunctionDef) and node.name in
                   {'visual_material','add_missing_colliders','generated_mesh'}]
        code=compile(ast.Module(body=functions,type_ignores=[]),str(source),'exec')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            record={'vertices':[[0,0,0],[1,0,0],[0,1,1]],'faces':[[0,1,2]],
                    'colors':[[.5,.2,.1]]*3,'coordinate_frame':'z_up','materials':[
                        {'roughness_factor':.6,'metallic_factor':0.,'base_color_factor':[1,1,1,1]}],
                    'material_index':[0], 'gaussian':{'file':'gaussian.npz','sh_degree':0,
                        'T_mesh_from_gaussian':np.eye(4).tolist(),
                        'appearance':'SAM3D radiance; source illumination retained, not relightable PBR'}}
            (root/'mesh.json').write_text(json.dumps(record))
            np.savez(root/'gaussian.npz',positions=np.asarray(record['vertices']),
                     scales=np.ones((3,3))*.02,orientations=np.tile([1,0,0,0],(3,1)),
                     opacities=np.ones(3),features=np.zeros((3,1,3)))
            for choice in ('auto','mesh'):
                with self.subTest(choice=choice):
                    stage=Usd.Stage.CreateInMemory();UsdGeom.Xform.Define(stage,'/World/Object')
                    materials=[]
                    env={**globals(),'stage':stage,'material_dependencies':materials,'material_catalog':{},
                         'job':{'asset_paths':{'asset_fixture':str(root/'mesh.json')}}}
                    exec(code,env)
                    _,receipt=env['generated_mesh']('/World/Object',{'asset_id':'asset_fixture',
                        'id':'fixture','size':[1,1,1],'render_representation':choice,
                        'appearance':{'roughness':.2,'specular':.3}})
                    mesh=UsdGeom.Mesh(stage.GetPrimAtPath('/World/Object/Geometry'))
                    hidden=mesh.ComputeVisibility()==UsdGeom.Tokens.invisible
                    self.assertEqual(hidden,choice=='auto')
                    self.assertTrue(mesh.GetPrim().HasAPI(UsdPhysics.CollisionAPI))
                    self.assertEqual(receipt['appearance_scope']['mesh_material_visibility'],
                                     'hidden' if hidden else 'visible')
                    self.assertEqual(receipt['render_representation'],'gaussian' if hidden else 'mesh')
                    if hidden:
                        self.assertEqual(receipt['appearance'],record['gaussian']['appearance'])
                        self.assertFalse(stage.GetPrimAtPath(receipt['gaussian']['prim_path']).HasAPI(UsdPhysics.CollisionAPI))
                    else:
                        self.assertFalse(stage.GetPrimAtPath('/World/Object/GaussianNormalization'))
                    for row in receipt['appearance_overrides']+materials:
                        self.assertEqual(row['appearance_scope'],receipt['appearance_scope'])
                    shader=UsdShade.Shader(stage.GetPrimAtPath('/World/Materials/fixture_pbr_0/Surface'))
                    self.assertAlmostEqual(shader.GetInput('roughness').Get(),.2)


if __name__=='__main__':unittest.main()
