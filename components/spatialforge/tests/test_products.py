"""Small real geometry/export checks; only the model responses are fixtures."""
import json
import importlib.util
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from PIL import Image
HAS_HARNESS=importlib.util.find_spec('benchclaw') is not None
if HAS_HARNESS:
    from spatialforge import products


@unittest.skipUnless(HAS_HARNESS,'Requires the real BenchClaw spatial task generator')
class ProductExports(unittest.TestCase):
    def capture(self, directory):
        capture=directory/'capture';capture.mkdir()
        Image.new('RGB',(100,80),'#b37f42').save(capture/'view_0.png')
        objects=[{'object_id':name,'bbox_2d':{'xyxy':box},'confidence':{'value':1}}
                 for name,box in [('left',[5,10,25,30]),('right',[65,45,85,65])]]
        (capture/'evidence.json').write_text(json.dumps({'frames':[{
            'frame_id':'view_0','image':'view_0.png','image_size':{'width':100,'height':80},'objects':objects
        }]}))

    def test_render_only_selected_preserves_candidate_selection_and_gt(self):
        from benchclaw import spatial_tasks
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory);capture=directory/'capture'
            frame=json.loads((capture/'evidence.json').read_text())['frames'][0]
            # Two views and four objects supply substantially more candidates
            # than the three selected images, without a large real render run.
            frame['objects'] += [
                {'object_id':'upper_right','bbox_2d':{'xyxy':[40,2,52,14]},'confidence':{'value':1}},
                {'object_id':'lower_left','bbox_2d':{'xyxy':[28,60,40,74]},'confidence':{'value':1}}]
            Image.new('RGB',(100,80),'#315285').save(capture/'view_1.png')
            frames=[frame,{**frame,'frame_id':'view_1','image':'view_1.png'}];target=3
            spec=SimpleNamespace(template_ids=['T021','T022','T023','T024','T025','T034','T035'],seed=29,target_items=target)
            original=[]
            with patch.object(spatial_tasks,'render') as eager_render:
                for source in frames:
                    record=SimpleNamespace(record_id=source['frame_id'],data={'entities':{
                        'image_size':source['image_size'],'objects':source['objects']},'range_verified':False})
                    original.extend((row,record) for row in spatial_tasks.generate_spatial(
                        record,capture/source['image'],spec,directory/'original_question_images'))
            expected=spatial_tasks.select_diverse(original,target)
            self.assertGreater(eager_render.call_count,target)
            with patch.object(products,'generate_spatial',wraps=spatial_tasks.generate_spatial) as generate, \
                 patch.object(products,'render',wraps=spatial_tasks.render) as selected_render:
                candidates,selected=products._select_question_images(directory,capture,frames,target)
            self.assertEqual(selected_render.call_count,target)
            self.assertTrue(all(call.kwargs['output'] is None for call in generate.call_args_list))
            comparable=lambda pairs:[{k:v for k,v in row.items() if k!='image'} for row,_ in pairs]
            self.assertEqual(comparable(candidates),comparable(original))
            self.assertEqual(comparable(selected),comparable(expected))
            self.assertEqual(len(list((directory/'question_images').glob('*/*.png'))),target)
            self.assertEqual({record.record_id for _,record in selected},{'view_0','view_1'})
            for (row,record),call in zip(selected,selected_render.call_args_list):
                self.assertEqual(call.args[0],capture/(record.record_id+'.png'))
                self.assertEqual(call.args[1],row['provenance']['objects'])
                self.assertEqual(call.args[2],directory/'question_images'/record.record_id/(row['item_id']+'.png'))
                self.assertTrue(Path(row['image']).is_file())
            self.assertTrue(all('question_images' not in row['image'] for row,_ in candidates))

    def test_all_rejected_retains_candidates_without_publishing_empty_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory)
            replies=[{'items':[]},{'valid':False,'issues':['fixture rejection']}]*2
            with patch.object(products,'completion',side_effect=replies) as model:
                with self.assertRaisesRegex(ValueError,'No accepted items'):
                    products.produce(directory,intent={'target_items':1})
            self.assertEqual(model.call_count,4)
            self.assertFalse((directory/'release').exists())
            attempt=next((directory/'product_attempts').glob('export_*'))
            report=json.loads((attempt/'collection_report.json').read_text())
            self.assertEqual(report['accepted'],0)
            self.assertEqual(report['publication_status'],'empty_candidate')
            self.assertTrue(report['collection_diagnostics_performed'])
            self.assertEqual(report['collection_diagnostics']['statistics']['items'],0)
            self.assertIn('item coverage 0 < 1',report['collection_diagnostics']['findings'])
            self.assertFalse((attempt/'complete.json').exists())
            self.assertEqual(len(json.loads((attempt/'item_reviews.json').read_text())),2)
            selection=report['data_selection']
            self.assertEqual(selection['state'],'review_budget_exhausted')
            self.assertEqual(selection['review_budget'],2)
            self.assertEqual(selection['replenishment_candidates_reviewed'],1)
            self.assertEqual(len(set(selection['reviewed_item_ids'])),2)
            self.assertEqual(len(list((attempt/'question_images').glob('*/*.png'))),2)

    def test_marker_filter_removes_real_corner_counterexample_without_changing_gt(self):
        from spatialforge.data_selection import filter_readable_candidates
        from benchclaw.spatial_tasks import generate_spatial
        objects=[{'object_id':name,'bbox_2d':{'xyxy':box},'confidence':{'value':1}}
                 for name,box in [('tray_parts',[954,712,960,720]),
                                 ('healthy_a',[100,100,200,200]),('healthy_b',[500,400,600,500])]]
        record=SimpleNamespace(record_id='view_0',data={'entities':{
            'image_size':{'width':960,'height':720},'objects':objects},'range_verified':False})
        spec=SimpleNamespace(template_ids=['T021','T023'],seed=29,target_items=8)
        pairs=[(row,record) for row in generate_spatial(record,Path('unused.png'),spec,output=None)]
        before=json.dumps([row for row,_ in pairs],sort_keys=True)
        eligible,report=filter_readable_candidates(pairs)
        self.assertTrue(eligible)
        self.assertGreater(report['filtered_by_marker_size'],0)
        self.assertEqual(report['excluded_object_count'],1)
        self.assertEqual(report['excluded_objects'][0]['bbox_extent_px'],[6,8])
        self.assertEqual(report['excluded_objects'][0]['min_bbox_edge_px'],12)
        self.assertTrue(all('tray_parts' not in row['task_contract']['objects'] for row,_ in eligible))
        self.assertEqual(before,json.dumps([row for row,_ in pairs],sort_keys=True))
        for row,_ in eligible:self.assertTrue(any(row is original for original,_ in pairs))
        self.assertNotIn('"answer"',json.dumps(report));self.assertNotIn('gt_values',json.dumps(report))

    def test_replenishment_reaches_target_without_repeating_evidence_or_leaking_answers(self):
        from benchclaw.spatial_tasks import _signature
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory)
            replies=[{'items':[]},{'valid':False,'issues':['fixture rejection']},
                     {'items':[]},{'valid':True,'issues':[]}]
            with patch.object(products,'completion',side_effect=replies) as model, \
                 patch.object(products,'render',wraps=products.render) as render:
                summary=products.produce(directory,intent={'target_items':1})
            self.assertEqual(summary['accepted'],1);self.assertEqual(summary['candidates_reviewed'],2)
            self.assertEqual(render.call_count,2)
            self.assertEqual(summary['data_selection']['state'],'target_reached')
            self.assertEqual(summary['collection_diagnostics']['selection']['filtered_by_item_review'],1)
            pairs=products._question_candidates(directory/'capture',json.loads((directory/'capture/evidence.json').read_text())['frames'],1)
            reviewed=set(summary['data_selection']['reviewed_item_ids'])
            self.assertEqual(len({_signature(row,record) for row,record in pairs if row['item_id'] in reviewed}),2)
            receipt=json.loads((directory/'data_selection.json').read_text())
            self.assertNotIn('"answer"',json.dumps(receipt));self.assertNotIn('gt_values',json.dumps(receipt))
            for call in model.call_args_list:
                self.assertNotIn('"answer":',call.args[0]);self.assertNotIn('gt_values',call.args[0])
            self.assertEqual(json.loads((directory/'release/item_reviews.json').read_text())[0]['issues'],['fixture rejection'])
            with zipfile.ZipFile(directory/'release/authority_bundle.zip') as archive:
                self.assertEqual(json.loads(archive.read('data_selection.json')),receipt)

    def test_candidate_exhaustion_reports_shortfall_without_repeated_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory)
            with patch.object(products,'completion',side_effect=[{'items':[]},{'valid':True},{'valid':False}]) as model:
                summary=products.produce(directory,intent={'target_items':8})
            self.assertEqual(model.call_count,3)
            self.assertEqual(summary['accepted'],1);self.assertEqual(summary['shortfall'],7)
            self.assertEqual(summary['data_selection']['state'],'candidate_pool_exhausted')
            self.assertEqual(summary['data_selection']['review_budget'],16)
            self.assertEqual(summary['candidates_reviewed'],2)

    def test_interrupted_export_keeps_prior_rejection_and_isolates_next_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory)
            with patch.object(products,'completion',side_effect=[{'items':[]},{'valid':False,'issues':['preserve this']},RuntimeError('author interrupted')]):
                with self.assertRaisesRegex(RuntimeError,'author interrupted'):
                    products.produce(directory,intent={'target_items':1})
            old=next((directory/'product_attempts').glob('export_*'))
            old_review=(old/'item_reviews.json').read_bytes()
            old_images=list((old/'question_images').glob('*/*.png'))
            self.assertEqual(len(old_images),2)
            self.assertEqual(json.loads(old_review)[0]['issues'],['preserve this'])
            with patch.object(products,'completion',side_effect=[{'items':[]},{'valid':True}]) as model:
                result=products.produce(directory,intent={'target_items':1})
            self.assertTrue(result['target_reached'])
            self.assertEqual((old/'item_reviews.json').read_bytes(),old_review)
            self.assertTrue(all(p.is_file() for p in old_images))
            self.assertNotEqual(model.call_args_list[0].args[1].parent.parent,old)

    def test_small_only_candidates_make_no_model_calls_and_retain_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory)
            path=directory/'capture/evidence.json';evidence=json.loads(path.read_text())
            for obj in evidence['frames'][0]['objects']:
                box=obj['bbox_2d']['xyxy'];box[2]=box[0]+6;box[3]=box[1]+8
            path.write_text(json.dumps(evidence))
            with patch.object(products,'completion',side_effect=AssertionError('no eligible images')):
                with self.assertRaisesRegex(ValueError,'No accepted items'):
                    products.produce(directory,intent={'target_items':1})
            receipt=json.loads((directory/'data_selection.json').read_text())
            self.assertEqual(receipt['state'],'candidate_pool_exhausted')
            self.assertGreater(receipt['generated_candidates'],0)
            self.assertEqual(receipt['eligible_candidates'],0)
            self.assertFalse((directory/'release').exists())

    def test_training_zip_resolves_images_and_preserves_program_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory)
            (directory/'scene_review.json').write_text(json.dumps({
                'passed':False,'publication_status':'exploration_requires_improvement'}))
            with patch.object(products,'completion',side_effect=[{'items':[]},{'valid':True,'issues':[],'quality':5}]):
                summary=products.produce(directory,'train',{'target_items':1})
            self.assertTrue(summary['target_reached'])
            self.assertEqual(summary['candidates_reviewed'],1)
            self.assertEqual(len(list((directory/'release/question_images').glob('*/*.png'))),1)
            self.assertFalse(summary['collection_review_performed'])
            self.assertTrue(summary['collection_diagnostics_performed'])
            self.assertEqual(summary['collection_diagnostics']['statistics']['source_images'],1)
            self.assertEqual(summary['collection_diagnostics']['scope']['scene_families'],1)
            self.assertFalse(summary['scene_quality_passed'])
            self.assertEqual(summary['publication_status'],'exploration_requires_improvement')
            release=directory/'release'
            self.assertEqual(json.loads((release/'collection_report.json').read_text()),summary)
            self.assertEqual(json.loads((release/'complete.json').read_text()),summary)
            authority=json.loads((release/'authority_bundle.json').read_text())
            with zipfile.ZipFile(release/'training_bundle.zip') as archive:
                sample=json.loads(archive.read('sft.jsonl').decode().strip())
                self.assertIn(sample['images'][0],archive.namelist())
                self.assertEqual(json.loads(sample['messages'][1]['content']),authority[0]['answer'])
            # T021 means A left of B; independently check the saved geometry.
            objects=authority[0]['evidence']['objects']
            expected='A' if objects[0]['center'][0]<objects[1]['center'][0] else 'B'
            self.assertEqual(authority[0]['answer'],expected)
            with zipfile.ZipFile(release/'model_bundle.zip') as archive:
                visible=json.loads(archive.read('model_bundle.json'))
                self.assertNotIn('answer',visible[0])
                self.assertIn(visible[0]['image'],archive.namelist())
            with patch.object(products,'completion',side_effect=AssertionError('must reuse release')):
                self.assertEqual(products.produce(directory,'train'),summary)

    def test_scene_and_interaction_packages_keep_evidence_and_dependency_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.capture(directory);capture=directory/'capture'
            evidence=json.loads((capture/'evidence.json').read_text())
            action={'id':'push','success':True,'trajectory_file':'interaction_0_trajectory.json',
                    'before_image':'interaction_0_before.png','after_image':'interaction_0_after.png'}
            evidence['interaction']={'validated':True,'test_kind':'external_force_response','action_results':[action]}
            evidence['asset_dependencies']=[{'kind':'registered_usd','path':'C:/Isaac/native.usd'}]
            (capture/'evidence.json').write_text(json.dumps(evidence))
            (capture/'report.json').write_text(json.dumps({'status':'test_fixture'}))
            (capture/'scene.usda').write_text('#usda 1.0\ndef Xform "Fixture" {}\n')
            (directory/'program.json').write_text('{"fixture":true}')
            (capture/'view_0.json').write_text(json.dumps(evidence['frames'][0]))
            for suffix in ('_depth.npy','_semantic.npy','_instance.npy'):
                (capture/('view_0'+suffix)).write_bytes(b'packaging fixture')
            for key in ('before_image','after_image'):
                Image.new('RGB',(8,8),'blue').save(capture/action[key])
            (capture/action['trajectory_file']).write_text('{"trajectory":[{"position":[0,0,0]},{"position":[1,0,0]}]}')
            release=directory/'attempt';release.mkdir()
            summary=products._package_capture(directory,release,evidence)
            self.assertTrue(summary['interaction_validated'])
            with zipfile.ZipFile(release/'interaction_bundle.zip') as archive:
                self.assertEqual(len(archive.namelist()),4)
                self.assertIn(action['trajectory_file'],archive.namelist())
                self.assertNotIn('view_0.png',archive.namelist())
            with zipfile.ZipFile(release/'scene_bundle.zip') as archive:
                self.assertIn('scene.usda',archive.namelist())
                self.assertIn('program.json',archive.namelist())
                self.assertIn('view_0_depth.npy',archive.namelist())
                dependencies=json.loads(archive.read('dependencies.json'))
                self.assertFalse(dependencies['self_contained'])
                self.assertEqual(dependencies['asset_dependencies'],evidence['asset_dependencies'])
            (capture/action['trajectory_file']).unlink()
            with self.assertRaisesRegex(ValueError,'Missing capture evidence'):
                products._package_capture(directory,release,evidence)

    def test_binary_scene_bundle_contains_referenced_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);capture=directory/'capture';capture.mkdir()
            (directory/'program.json').write_text('{}')
            (capture/'scene.usda').write_text('#usda 1.0\n( subLayers = [@scene.usdc@] )\n')
            (capture/'scene.usdc').write_bytes(b'PXR-USDC packaging fixture')
            resources=[{'file':'scene_resource_000.hdr','source':'D:/library/sky.hdr'}]
            (capture/'report.json').write_text(json.dumps({'scene_format':'usdc','scene_resources':resources}))
            (capture/'scene_resource_000.hdr').write_bytes(b'hdr packaging fixture')
            (capture/'evidence.json').write_text('{"frames":[]}')
            release=directory/'release';release.mkdir()
            products._package_capture(directory,release,{'frames':[]})
            with zipfile.ZipFile(release/'scene_bundle.zip') as archive:
                self.assertEqual(archive.read('scene.usdc'),(capture/'scene.usdc').read_bytes())
                self.assertIn(b'@scene.usdc@',archive.read('scene.usda'))
                self.assertEqual(archive.read('scene_resource_000.hdr'),b'hdr packaging fixture')
                dependencies=json.loads(archive.read('dependencies.json'))
                self.assertEqual(dependencies['scene_resources'],resources)
                self.assertFalse(dependencies['self_contained'])
            (capture/'scene_resource_000.hdr').rename(capture/'retained.hdr')
            with self.assertRaisesRegex(ValueError,'Missing capture evidence'):
                products._package_capture(directory,release,{'frames':[]})
            (capture/'retained.hdr').rename(capture/'scene_resource_000.hdr')
            (capture/'scene.usdc').unlink()
            with self.assertRaisesRegex(ValueError,'Missing capture evidence'):
                products._package_capture(directory,release,{'frames':[]})

    def test_collection_diagnostics_measure_duplicates_bias_and_source_scope_without_gate(self):
        frames=[{'frame_id':f'view_{i}','image':f'view_{i}.png','objects':[{'object_id':name} for name in ('a','b')]}
                for i in range(3)]
        public=[];authority=[];candidates=[]
        for i,source in enumerate(('view_0','view_0','view_1','view_1')):
            item={'item_id':f'item_{i}','template_id':'T021','question':'same wording','options':{'A':'yes','B':'no'},
                  'answer_type':'single_choice','task_contract':{'source_record':source,'objects':['a','b']}}
            public.append(item);authority.append({'item_id':item['item_id'],'answer':'A'})
            candidates.append((item,SimpleNamespace(record_id=source)))
        original=json.dumps(authority)
        report=products._collection_diagnostics(public,authority,{'frames':frames},candidates,candidates,5,'one_scene')
        stats=report['statistics']
        self.assertEqual(stats['items'],4)
        self.assertEqual(stats['source_records'],2)
        self.assertEqual(stats['source_images'],2)
        self.assertEqual(stats['duplicate_evidence_groups'],2)
        self.assertEqual(stats['repeated_prompt_groups'],1)
        self.assertEqual(stats['templates']['T021']['majority_constant_baseline'],1.0)
        self.assertEqual(stats['templates']['T021']['semantic_answer_histogram'],{'"yes"':4})
        self.assertEqual(report['scope']['unused_source_frames'],['view_2'])
        self.assertEqual(report['selection']['shortfall'],1)
        self.assertEqual(report['mode'],'record_only')
        self.assertEqual(report['collection_acceptance'],'not_assessed')
        self.assertIn('repeated source/object comparison evidence',report['findings'])
        self.assertTrue(any('constant-answer baseline' in finding for finding in report['findings']))
        self.assertEqual(json.dumps(authority),original)

    def test_collection_diagnostics_reject_mismatched_authority_and_unknown_sources(self):
        item={'item_id':'item','template_id':'T021','question':'fixture','options':{'A':'yes'},
              'answer_type':'single_choice','task_contract':{'source_record':'missing','objects':['a','b']}}
        selected=[(item,SimpleNamespace(record_id='missing'))]
        with self.assertRaisesRegex(ValueError,'IDs must be unique and match'):
            products._collection_diagnostics([item],[],{'frames':[]},selected,selected,1,'scene')
        with self.assertRaisesRegex(ValueError,'unknown source frame'):
            products._collection_diagnostics([item],[{'item_id':'item','answer':'A'}],{'frames':[]},selected,selected,1,'scene')


if __name__=='__main__':unittest.main()
