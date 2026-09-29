"""Review and repair see the renderer used, without deriving it from intent."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from spatialforge import engine
from spatialforge.repair_context import build_repair_context, scene_changes
from test_contracts import sample


class RenderReceiptTests(unittest.TestCase):
    def test_gaussian_scope_reaches_review_and_repair_with_representation_diff(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);capture=root/'capture';capture.mkdir()
            program=sample()
            scope={'visible_surface':'gaussian_radiance','mesh_material_visibility':'hidden'}
            gaussian={'appearance':'source illumination retained', 'physics':'paired mesh',
                      'collision_visibility':'invisible','T_entity_from_gaussian':[[1,0,0,0]]*4}
            asset={'entity_id':'unknown_object','asset_id':'asset_fixture','render_representation':'gaussian',
                   'appearance_scope':scope,'gaussian':gaussian,'appearance':gaussian['appearance']}
            entity={'id':'unknown_object','kind':'mesh','render_representation':'gaussian','appearance_scope':scope}
            originals={root/'program.json':program,
                       capture/'report.json':{'status':'captured','renderable':True,'physics':{'stable':True}},
                       capture/'evidence.json':{'origin':'isaac_native','entities':{'unknown_object':entity},
                                                'asset_dependencies':[asset],
                                                'material_dependencies':[{'entity_id':'unknown_object','appearance_scope':scope}]}}
            for path,data in originals.items():path.write_text(json.dumps(data))
            class Store:
                def directory(self,*args):return root
                def snapshot(self,*args):return {'state':'CANCELED'}
                def update(self,*args,**kwargs):raise AssertionError('must not update test task')
            with patch.object(engine,'completion',return_value={'acceptable':False,'issues':['fixture']}) as model:
                engine.review_scene(Store(),{'id':'scene','run_id':'run','unit':{
                    'revision':0,'intent':{},'submitted_program':{'program':program}}},threading.Event())
            prompt=model.call_args.args[0]
            receipt=json.loads(prompt.split('\n实体与资产执行记录：',1)[1].split('\n',1)[0])
            for key in ('entities','asset_dependencies','material_dependencies'):
                self.assertEqual(receipt[key][0]['appearance_scope'],scope)
            self.assertEqual(receipt['entities'][0]['render_representation'],'gaussian')
            self.assertEqual(receipt['asset_dependencies'][0]['gaussian'],gaussian)
            context,_=build_repair_context(root)
            row=context['current_execution']['entities'][0]
            self.assertEqual(row['state']['appearance_scope'],scope)
            self.assertEqual(row['asset']['appearance_scope'],scope)
            self.assertEqual(row['asset']['render_representation'],'gaussian')
            self.assertEqual(row['asset']['gaussian']['appearance'],gaussian['appearance'])
            self.assertEqual(row['asset']['gaussian']['collision_visibility'],'invisible')
            self.assertNotIn('T_entity_from_gaussian',row['asset']['gaussian'])
            # Legacy captures already contain Gaussian metadata but lack the new scope.
            entity.pop('appearance_scope');asset.pop('appearance_scope')
            (capture/'evidence.json').write_text(json.dumps(originals[capture/'evidence.json']))
            legacy,_=build_repair_context(root)
            self.assertEqual(legacy['current_execution']['entities'][0]['asset']['gaussian']['appearance'],gaussian['appearance'])
            before={'objects':[{'id':'a','render_representation':'auto'}]}
            after={'objects':[{'id':'a','render_representation':'mesh'}]}
            self.assertEqual(scene_changes(before,after)['changes'][0]['field'],'render_representation')

    def test_compact_entities_after_twenty_four_are_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'capture').mkdir()
            entities={f'object_{i}':{'kind':'box'} for i in range(30)}
            entities['object_29']['render_representation']='gaussian'
            (root/'program.json').write_text(json.dumps({'objects':[{'id':oid} for oid in entities]}))
            (root/'capture/evidence.json').write_text(json.dumps({'entities':entities,
                'asset_dependencies':[{'entity_id':'object_29','render_representation':'gaussian',
                                       'gaussian':{'appearance':'source illumination retained'}}]}))
            context,_=build_repair_context(root)
            rows=context['current_execution']['entities']
            self.assertEqual(len(rows),30)
            self.assertEqual(rows[-1]['asset']['gaussian']['appearance'],'source illumination retained')
            self.assertEqual(context['current_execution']['omitted_entities'],0)

    def test_capture_settings_reach_review_and_repair_unchanged(self):
        for actual in ({'renderer':'PathTracing','samples_per_pixel':64,'exposure':.7,
                        'pathtracing_spp':64,'film_iso':162.4504792712471}, {}):
            with self.subTest(actual=actual),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);capture=root/'capture';capture.mkdir()
                program=sample()
                program['render_environment']={'renderer':'RaytracedLighting','exposure':-2}
                (root/'program.json').write_text(json.dumps(program))
                report={'status':'captured','renderable':True,'physics':{'stable':True}}
                if actual:report['render_settings']=actual
                (capture/'report.json').write_text(json.dumps(report))
                # Evidence intentionally lacks renderer settings: report is the current execution receipt.
                parts={'source':'executed_primitive_construction','coordinate_frame':'entity_local_meters',
                       'parts':[{'prim_path':'/World/Objects/spool/part0','usd_type':'Cylinder',
                                 'shape':'cylinder','size':[.055,.055,.008],'offset':[0,0,.0235]}]}
                (capture/'evidence.json').write_text(json.dumps({'origin':'isaac_native',
                    'entities':{'spool':{'id':'spool','kind':'composite','size':[.055,.055,.055],'geometry_parts':parts}}}))
                originals={p:p.read_bytes() for p in (root/'program.json',capture/'report.json',capture/'evidence.json')}
                class Store:
                    def directory(self,*args):return root
                    def snapshot(self,*args):return {'state':'CANCELED'}
                    def update(self,*args,**kwargs):raise AssertionError('canceled test must not update tasks')
                with patch.object(engine,'completion',return_value={'acceptable':False,'issues':['fixture']} ) as model,patch.object(engine,'produce') as produce:
                    engine.review_scene(Store(),{'id':'scene','run_id':'run','unit':{'revision':0,'intent':{},'submitted_program':{'program':program}}},threading.Event())
                prompt=model.call_args.args[0]
                received=json.loads(prompt.split('\n渲染执行记录：',1)[1].split('\n',1)[0])
                self.assertEqual(received,actual)
                entities=json.loads(prompt.split('\n实体与资产执行记录：',1)[1].split('\n',1)[0])['entities']
                self.assertEqual(entities[0]['geometry_parts'],parts)
                context,_=build_repair_context(root)
                self.assertEqual(context['current_execution']['render_settings'],actual)
                self.assertEqual(context['current_execution']['entities'][0]['state']['geometry_parts'],parts)
                self.assertFalse(json.loads((root/'scene_review.json').read_text())['passed'])
                produce.assert_not_called()
                for path,content in originals.items():self.assertEqual(path.read_bytes(),content)


if __name__=='__main__':unittest.main()
