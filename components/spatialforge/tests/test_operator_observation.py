import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from spatialforge.observation import observe,wait_for_change
from spatialforge.progress import record_progress


class OperatorObservation(unittest.TestCase):
    def test_capture_status_exposes_white_view_without_repeating_asset_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'sf_capture.scene0/revision_0';(folder/'capture').mkdir(parents=True)
            report={'status':'captured','frames':2,'renderable':False,'errors':[],
                    'asset_dependencies':[{'large_source_inventory':'x'*100000}],
                    'render_settings':{'renderer':'PathTracing'}}
            result={'operation':'capture_only','report':report,'files':[],
                    'scene_quality_assessed':False,'data_exported':False}
            class Store:
                def __init__(self):self.root=root
                def snapshot(self,rid):return {'state':'SUCCEEDED','tasks':[{
                    'id':'sf_capture.scene0','state':'SUCCEEDED','result':result,
                    'unit':{'workflow':'scene','phase':'complete','revision':0,'intent':{'capture_only':True}}}]}
            for i,(std,areas) in enumerate(((40.,[('chair',200),('table',300)]),(0.,[('ceiling',691200)]))):
                frame={'frame_id':f'view_{i}','rgb_std':std,'camera':{'position':[1,5.2,6.5],'target':[1,5.2,.4]},
                       'objects':[{'object_id':oid,'mask':{'area_px':area}} for oid,area in areas]}
                (folder/f'capture/view_{i}.json').write_text(json.dumps(frame))
            original=json.dumps(result,sort_keys=True)
            row=wait_for_change(Store(),'sf_capture')['tasks'][0]
            self.assertEqual(row['state'],'SUCCEEDED')
            self.assertEqual(row['next_action'],'inspect_capture_issues')
            self.assertFalse(row['result']['report']['renderable'])
            self.assertFalse(row['result']['scene_quality_assessed'])
            self.assertNotIn('quality',row)
            views=row['result']['views']
            self.assertEqual(views[0]['largest_visible_objects'][0]['object_id'],'table')
            self.assertEqual(views[1]['rgb_std'],0.)
            self.assertEqual(views[1]['largest_visible_objects'],[{'object_id':'ceiling','area_px':691200}])
            self.assertEqual(views[1]['camera']['position'],[1,5.2,6.5])
            self.assertNotIn('large_source_inventory',json.dumps(row))
            self.assertEqual(json.dumps(result,sort_keys=True),original)
            report['renderable']=True
            self.assertEqual(observe(Store(),'sf_capture')['tasks'][0]['next_action'],'inspect_captures')

    def test_passing_scene_with_realism_gaps_returns_original_review_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def snapshot(self,rid):return {'state':'SUCCEEDED','tasks':[{'id':rid+'.scene0','state':'SUCCEEDED',
                    'unit':{'workflow':'scene','phase':'complete','revision':1}}]}
            store=Store();folder=store.root/'sf_review.scene0/revision_1';folder.mkdir(parents=True)
            prior=folder.parent/'revision_0';prior.mkdir()
            (prior/'scene_review.json').write_text(json.dumps({'passed':False,'issues':['old issue']}))
            review={'passed':True,'interaction_passed':True,'visual_realism':{'status':'needs_improvement'},
                'issues':['地板拼贴重复','No instrument wood grain'],
                'repair_suggestions':['更换地板贴图或调色','Use a textured mesh'],
                'scene_quality':{'dimensions':{'geometry':{'capability_gaps':['long diagnostic']}}}}
            path=folder/'scene_review.json';path.write_text(json.dumps(review,ensure_ascii=False),encoding='utf8')
            original=path.read_bytes()
            (folder/'release').mkdir()
            (folder/'release/complete.json').write_text(json.dumps({'accepted':12,'target_reached':True,
                'scene_quality_passed':True,'publication_status':'pilot_candidate'}))
            row=wait_for_change(store,'sf_review')['tasks'][0]
            self.assertTrue(row['quality']['scene_quality_passed'])
            self.assertTrue(row['quality']['data_target_reached'])
            self.assertEqual(row['quality']['visual_realism'],'needs_improvement')
            self.assertEqual(row['quality']['feedback'],{'file':'scene_review.json',
                'issues':review['issues'],'repair_suggestions':review['repair_suggestions']})
            self.assertEqual(row['next_action'],'inspect_quality_gaps')
            self.assertNotIn('long diagnostic',json.dumps(row))
            self.assertEqual(path.read_bytes(),original)
            review.update(issues=[],repair_suggestions=[],visual_realism={'status':'passed'})
            path.write_text(json.dumps(review),encoding='utf8')
            self.assertEqual(observe(store,'sf_review')['tasks'][0]['next_action'],'inspect_products')

    def test_asset_wait_returns_selected_candidate_feedback_and_available_source_files(self):
        with tempfile.TemporaryDirectory() as temp:
            selected={'asset_id':'asset_selected','quality':{'semantic_review':'needs_improvement',
                'issues':['Incomplete segmentation'],'repair_prompt':'Inspect mask','3d_validated':False}}
            class Store:
                root=Path(temp)
                def snapshot(self,rid):return {'state':'SUCCEEDED','tasks':[{'id':rid+'.scene0','state':'SUCCEEDED',
                    'unit':{'workflow':'asset','phase':'complete','revision':0},'result':selected}]}
            store=Store();folder=store.root/'sf_asset.scene0/revision_0';folder.mkdir(parents=True)
            # The unselected initial receipt must not replace the selected result.
            (folder/'generation').mkdir();(folder/'generation/asset_ref.json').write_text('{"asset_id":"asset_initial"}')
            registered=store.root/'generated_assets/asset_selected';registered.mkdir(parents=True)
            for name in ('reference.png','mask.png','asset.glb'):(registered/name).write_bytes(b'asset evidence')
            frozen=json.dumps(selected,sort_keys=True)
            row=wait_for_change(store,'sf_asset')['tasks'][0]
            self.assertEqual(row['result'],selected)
            self.assertEqual(row['next_action'],'inspect_asset')
            self.assertEqual({f['file'] for f in row['asset_files']},{'reference.png','mask.png','asset.glb'})
            mask=next(f for f in row['asset_files'] if f['file']=='mask.png')
            self.assertEqual(Path(mask['source_path']).read_bytes(),b'asset evidence')
            self.assertEqual(mask['workspace_path'],'/assets/asset_selected/mask.png')
            self.assertEqual(json.dumps(selected,sort_keys=True),frozen)
            self.assertNotIn('quality',row) # Asset feedback does not imply scene approval.

    def test_upload_milestones_keep_waiting_but_errors_wake(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def snapshot(self,rid):return {'state':'RUNNING','tasks':[{'id':rid+'.scene0','state':'RUNNING','unit':{'phase':'capture','revision':0},'failure':None}]}
            store=Store();folder=store.root/'sf_test.scene0/revision_0';folder.mkdir(parents=True)
            record_progress(folder,'capture',started_at=1);a=observe(store,'sf_test')
            record_progress(folder,'capture',started_at=1);b=observe(store,'sf_test')
            self.assertEqual(a['cursor'],b['cursor'])
            self.assertIsInstance(b['tasks'][0]['progress']['updated_ns'],str)
            record_progress(folder,'upload',bytes_received=11,total_bytes=100,file='a.usda');a=observe(store,'sf_test')
            record_progress(folder,'upload',bytes_received=19,total_bytes=100,file='b.npy');b=observe(store,'sf_test')
            self.assertEqual(a['cursor'],b['cursor']);self.assertEqual(b['tasks'][0]['progress']['bytes_received'],19)
            record_progress(folder,'upload',bytes_received=99,total_bytes=100);c=observe(store,'sf_test')
            self.assertEqual(b['cursor'],c['cursor'])
            self.assertEqual(c['tasks'][0]['progress']['bytes_received'],99)
            self.assertNotIn('quality',c['tasks'][0])
            self.assertLess(len(c['cursor']),250)
            record_progress(folder,'upload_retry',errors=1,error='disconnected');d=observe(store,'sf_test')
            self.assertNotEqual(c['cursor'],d['cursor'])

    def test_export_and_success_never_hide_failed_scene_quality(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                state='RUNNING'
                def snapshot(self,rid):return {'state':self.state,'tasks':[{'id':rid+'.scene0','state':self.state,'unit':{'phase':'review','revision':3},'failure':None}]}
            store=Store();folder=store.root/'sf_test.scene0/revision_3';folder.mkdir(parents=True)
            (folder/'scene_review.json').write_text(json.dumps({'passed':False,'issues':['violin faces down'],
                'repair_suggestions':['Inspect the violin pose'],'interaction_passed':True,'visual_realism':{'status':'needs_improvement'},'publication_status':'exploration_requires_improvement'}))
            record_progress(folder,'data_export');a=observe(store,'sf_test')
            self.assertFalse(a['tasks'][0]['quality']['scene_quality_passed']);self.assertFalse(a['tasks'][0]['quality']['data_export_complete'])
            (folder/'release').mkdir();(folder/'release/complete.json').write_text(json.dumps({'accepted':8,'target_items':8,'shortfall':0,'target_reached':True,'publication_status':'exploration_requires_improvement','scene_quality_passed':False,'scene_self_contained':False}))
            store.state='SUCCEEDED';b=observe(store,'sf_test')
            self.assertTrue(b['terminal']);self.assertTrue(b['tasks'][0]['quality']['data_target_reached'])
            self.assertFalse(b['tasks'][0]['quality']['scene_quality_passed']);self.assertFalse(b['tasks'][0]['quality']['benchmark_approved'])
            self.assertEqual(b['tasks'][0]['next_action'],'inspect_quality_gaps')
            self.assertEqual(b['tasks'][0]['quality']['collection_acceptance'],'not_assessed')
            self.assertFalse(b['tasks'][0]['summary']['scene_self_contained'])
            self.assertEqual(b['tasks'][0]['quality']['feedback']['issues'],['violin faces down'])

    def test_compact_status_reports_asset_substage_without_repeating_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                def snapshot(self,rid):return {'state':'RUNNING','tasks':[{'id':rid+'.scene0','state':'RUNNING','unit':{'phase':'plan','revision':0,'intent':{'description':'long frozen intent'}},'failure':None}]}
            store=Store();folder=store.root/'sf_example.scene0'/'revision_0';folder.mkdir(parents=True)
            record_progress(folder,'sam3d',object_id='pot')
            value=observe(store,'sf_example')
            self.assertEqual(value['tasks'][0]['progress']['stage'],'sam3d')
            self.assertNotIn('long frozen intent',json.dumps(value))
            self.assertFalse(value['terminal'])

    def test_wait_is_read_only_and_returns_on_change_or_terminal(self):
        active={'terminal':False,'cursor':'a'};changed={'terminal':False,'cursor':'b'}
        with patch('spatialforge.observation.observe',side_effect=[active,changed]) as read,patch('spatialforge.observation.time.sleep') as sleep:
            result=wait_for_change(object(),'run','a',1)
        self.assertTrue(result['changed']);self.assertEqual(read.call_count,2);self.assertEqual(sleep.call_count,1)
        with patch('spatialforge.observation.observe',return_value={'terminal':True,'cursor':'a'}),patch('spatialforge.observation.time.sleep') as sleep:
            result=wait_for_change(object(),'run','a',1)
        self.assertTrue(result['terminal']);sleep.assert_not_called()
        with self.assertRaises(ValueError):wait_for_change(object(),'run',timeout_seconds=61)

    def test_wait_without_cursor_survives_upload_changes_then_wakes_for_review(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root=Path(temp)
                phase='capture'
                def snapshot(self,rid):return {'state':'RUNNING','tasks':[{'id':rid+'.scene0','state':'RUNNING','unit':{'phase':self.phase,'revision':0}}]}
            store=Store();folder=store.root/'sf_upload.scene0/revision_0';folder.mkdir(parents=True)
            record_progress(folder,'upload',bytes_received=20,total_bytes=100)
            clock=[0]
            def sleep(seconds):
                clock[0]+=seconds
                if clock[0]<6:record_progress(folder,'upload',bytes_received=20+int(clock[0])*10,total_bytes=100)
                else:
                    store.phase='review';record_progress(folder,'scene_review')
            with patch('spatialforge.observation.time.monotonic',side_effect=lambda:clock[0]),patch('spatialforge.observation.time.sleep',side_effect=sleep):
                result=wait_for_change(store,'sf_upload')
            self.assertEqual(result['waited_seconds'],6)
            self.assertTrue(result['changed'])
            self.assertEqual(result['tasks'][0]['phase'],'review')

if __name__=='__main__':unittest.main()
