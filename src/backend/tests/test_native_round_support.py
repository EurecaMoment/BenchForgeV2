import copy
import unittest
from benchforge_backend.scene_relations import supported_by_native_parts


class NativeRoundSupportTest(unittest.TestCase):
    def test_round_table_accepts_centered_book_but_rejects_empty_square_corner(self):
        entity={'world_transform':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,.5,1]],
                'geometry_parts':{'source':'executed_primitive_construction','coordinate_frame':'entity_local_meters',
                    'parts':[{'prim_path':'/table/top','shape':'cylinder','size':[1,1,.1],'offset':[0,0,0]}]}}
        self.assertTrue(supported_by_native_parts(([-.1,-.1,.55],[.1,.1,.75]),entity))
        self.assertFalse(supported_by_native_parts(([.35,.35,.55],[.45,.45,.75]),entity))
        self.assertFalse(supported_by_native_parts(([-.1,-.1,.65],[.1,.1,.85]),entity))
        tilted=copy.deepcopy(entity);tilted['geometry_parts']['parts'][0]['rotation_deg_xyz']=[30,0,0]
        self.assertFalse(supported_by_native_parts(([-.1,-.1,.55],[.1,.1,.75]),tilted))


if __name__=='__main__':unittest.main()
