import json
import tempfile
import unittest
from pathlib import Path
from benchforge_core.spatial_learning.registry import graph,templates
from benchforge_core.spatial_learning.scenes import create_scene
from benchforge_core.spatial_learning.generation import make_item,generate
from benchforge_core.spatial_learning.scoring import score
from benchforge_core.spatial_learning.graph_tasks import shortest
from benchforge_core.spatial_learning.curriculum import update_state,allocate
from benchforge_core.spatial_learning.environments import Manipulation,demonstration
from benchforge_core.runtime import Runtime


class SpatialLearningTests(unittest.TestCase):
    def test_source_nodes_and_every_template_executes(self):
        self.assertEqual([n['id'] for n in graph()['nodes']],[f'N{i:02}' for i in range(1,28)])
        self.assertEqual(len(templates()),3240)
        for template in templates():
            q,a=make_item(template,45671,2,'independent-check')
            self.assertNotIn('answer',q)
            if a['scorer']=='environment':self.assertTrue(a['demonstration']['success'],template['id'])
            else:self.assertTrue(score(a,json.dumps(a['answer']))['success'],template['id'])

    def test_original_examples_and_equivalent_paths(self):
        t=next(t for t in templates('N15') if t['query']=='future_point')
        from benchforge_core.spatial_learning.reasoning_tasks import task
        s=create_scene(t,17);s['motion'].update(initial=[2,1],velocity=[0,1],acceleration=[0,0],prediction_t=2)
        s['transform']={'angle':90,'origin':[0,0]}
        actual=task(s,'N15','future_point')['answer']
        self.assertAlmostEqual(actual[0],-3);self.assertAlmostEqual(actual[1],2)
        g={'nodes':['S','A','B','G'],'start':'S','goal':'G','body_width':.6,'directed':False,
            'edges':[{'a':a,'b':b,'cost':c,'width':w,'open':True} for a,b,c,w in [('S','A',1,1),('A','G',1,.5),('S','B',2,1),('B','G',2,.9)]]}
        self.assertEqual(shortest(g),(['S','B','G'],4))
        g['edges'][1]['width']=1;g['edges'][2]['cost']=g['edges'][3]['cost']=1
        a={'scorer':'path','answer':['S','A','G'],'path_graph':g,'path_rule':{'feasible':True,'start':'S','goal':'G','optimal_cost':2}}
        self.assertTrue(score(a,['S','B','G'])['success'])
        self.assertFalse(score(a,['S','G'])['success'])

    def test_failure_feedback_requires_actual_recovery(self):
        t=templates('N24')[0];scene=create_scene(t,13);scene['episode']['failure']='rotation_failure'
        env=Manipulation(scene);demo=demonstration(env)
        self.assertTrue(demo['success'])
        feedback=[r['response']['feedback'] for r in demo['trajectory']]
        self.assertIn('rotation_failed_angle_unchanged',feedback)
        self.assertEqual(sum(r['action']['action']=='rotate' for r in demo['trajectory']),2)
        broken=Manipulation(scene)
        for action in [{'action':'move','destination':'part'},{'action':'grasp'},{'action':'move','destination':'slot'},{'action':'insert'}]:broken.step(action)
        self.assertFalse(broken.success())

    def test_group_split_and_no_dev_answers_in_sft(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids=[templates('N11')[0]['id'],templates('N11')[10]['id']]
            result=generate({'template_ids':ids,'groups_per_profile':20,'conditions':['natural','supplied_intermediate','isolated']},Path(tmp))
            root=Path(result['dataset']);seen={}
            for part in ['train','curriculum_dev','selection_dev','sealed_test']:
                for line in (root/part/'questions.jsonl').read_text(encoding='utf8').splitlines():
                    row=json.loads(line);self.assertNotIn('answer',row)
                    self.assertEqual(seen.setdefault(row['scene_group'],part),part)
                    for image in row['images']:
                        self.assertFalse(Path(image).is_absolute());self.assertTrue((root/image).is_file())
                if part!='train':self.assertEqual((root/part/'sft.jsonl').read_text(encoding='utf8'),'')

    def test_matched_map_control_and_sampling_coverage(self):
        from benchforge_core.spatial_learning.conditions import apply_condition
        t=next(t for t in templates('N23') if t['query']=='route')
        q,a=make_item(t,482,2,'matched')
        natural,_=apply_condition(q,a,'natural');given,_=apply_condition(q,a,'supplied_intermediate')
        self.assertNotIn('map',natural['inputs']);self.assertIn('visits',natural['inputs'])
        self.assertIn('map',given['inputs']);self.assertEqual(natural['scene_group'],given['scene_group'])
        plans=[allocate({},54,seed=i) for i in range(3)]
        for plan in plans:
            chosen=[r for r in plan['allocation'] if r['count']]
            self.assertEqual(len({r['template_id'].split('.')[0] for r in chosen}),27)
        self.assertNotEqual([r['count'] for r in plans[0]['allocation']],[r['count'] for r in plans[1]['allocation']])

    def test_valid_alternative_constraint_solution(self):
        authority={'scorer':'constraints','answer':{'A':0,'B':1},'facts':[['A','left_of','B']]}
        self.assertTrue(score(authority,{'A':-7,'B':18})['success'])
        self.assertFalse(score(authority,{'A':18,'B':-7})['success'])

    def test_structural_holdout_never_enters_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids=['N21.consistent.scatter.v1','N21.consistent.grid.v1']
            r=generate({'template_ids':ids,'groups_per_profile':20,'render':False,'heldout_profiles':['grid']},Path(tmp))
            root=Path(r['dataset'])
            train=[json.loads(l) for l in (root/'train/questions.jsonl').read_text(encoding='utf8').splitlines()]
            self.assertTrue(all('.grid.' not in q['template_id'] for q in train))
            sealed=[json.loads(l) for l in (root/'sealed_test/questions.jsonl').read_text(encoding='utf8').splitlines()]
            self.assertEqual(sum(q['holdout']=='structural_profile' for q in sealed),20)

    def test_hint_and_difficulty_change_actual_selection(self):
        import random
        from benchforge_core.spatial_learning.training import select_record
        rows=[{'id':'natural','condition':'natural','difficulty':1},{'id':'assisted','condition':'supplied_intermediate','difficulty':2}]
        self.assertEqual(select_record(rows,{'hint_fraction':1,'difficulty':2},random.Random(0))['id'],'assisted')
        self.assertEqual(select_record(rows,{'hint_fraction':0,'difficulty':1},random.Random(0))['id'],'natural')

    def test_execution_requires_placement_and_assembly(self):
        scene=create_scene(templates('N24')[0],39)
        env=Manipulation(scene,'assemble');demo=demonstration(env)
        self.assertTrue(demo['success'])
        self.assertIn('fasten',[r['action']['action'] for r in demo['trajectory']])
        env=Manipulation(scene,'place');demo=demonstration(env)
        self.assertTrue(demo['success']);self.assertIn('place',[r['action']['action'] for r in demo['trajectory']])

    def test_arrow_pixels_match_declared_bounding_rectangle(self):
        from benchforge_core.spatial_learning.scenes import render
        from PIL import ImageChops,Image
        scene=create_scene(templates('N11')[0],19);scene['objects']=scene['objects'][:1]
        scene['objects'][0].update(shape='arrow',position=[5,5],size=[2,2],color='red')
        with tempfile.TemporaryDirectory() as tmp:
            image=render(scene,Path(tmp)/'arrow.png',hide_labels=True)
            # The arrow tip and both extremal corners must be actual colored pixels.
            for point in [(380,320),(332,260),(332,380)]:self.assertEqual(image.getpixel(point),(201,72,66))

    def test_nested_profile_keeps_full_shape_queries_visible(self):
        from benchforge_core.spatial_learning.geometry_tasks import intersection
        t=next(t for t in templates('N03') if t['scene_profile']=='nested')
        for seed in [42000,42004,42005,42006]:
            s=create_scene(t,seed,1+seed%3)
            for i,a in enumerate(s['objects']):
                for b in s['objects'][i+1:]:self.assertEqual(intersection(a,b),0)

    def test_mastery_uses_dev_and_retains_initial_reference(self):
        template=templates('N11')[0]['id']
        def rows(success):return [dict(template_id=template,input_mode='image',condition='natural',difficulty=1,capabilities=['N11'],partition='curriculum_dev',scene_group=f'g{i}',success=success,parse_ok=True) for i in range(100)]
        state=update_state({},rows(True),'base','0')
        state=update_state(state,rows(False),'w1','1')
        row=next(iter(state['mastery'].values()));self.assertEqual(row['regression'],1)
        plan=allocate(state,17,'C',[template]);self.assertEqual(sum(r['count'] for r in plan['allocation']),17)
        bad=rows(True);bad[0]['partition']='sealed_test'
        with self.assertRaisesRegex(ValueError,'development'):update_state(state,bad,'w2','2')

    def test_core_tool_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp)
            try:result=runtime.call('spatial_catalog',{'section':'templates','capability':'N01','limit':1})
            finally:runtime.close()
            self.assertEqual(result['total'],120)

    def test_exclusions_preserve_worlds_and_run_before_media_validation(self):
        ids=['N21.consistent.scatter.v1','N21.consistent.grid.v1']
        with tempfile.TemporaryDirectory() as tmp:
            full=generate({'template_ids':ids,'groups_per_profile':1,'render':False},Path(tmp)/'full')
            subset=generate({'template_ids':ids+['N03.shape.scatter.v1'],
                'exclude_template_ids':[ids[1],'N03.shape.scatter.v1'],
                'groups_per_profile':1,'render':False},Path(tmp)/'subset')
            def authority(result):
                return [json.loads(line) for line in (Path(result['dataset'])/'train/authority.jsonl').read_text().splitlines()]
            expected=next(row for row in authority(full) if row['template_id']==ids[0])
            self.assertEqual(authority(subset),[expected])

    def test_shape_worlds_include_positive_and_negative_morphology(self):
        from benchforge_core.spatial_learning.generation import build_task
        for profile in sorted({t['scene_profile'] for t in templates('N03')}):
            for query in ['holes','convex','reflected_match','rotated_match']:
                template=next(t for t in templates('N03') if t['scene_profile']==profile and t['query']==query)
                answers=[build_task(create_scene(template,61003+i,2),template)['answer'] for i in range(20)]
                self.assertGreaterEqual(len(set(answers)),2,template['id'])
                self.assertLessEqual(max(answers.count(a) for a in set(answers)),16,template['id'])

    def test_camera_profiles_move_visible_landmarks_and_vary_endpoint(self):
        import math
        from benchforge_core.spatial_learning.motion_tasks import observed_scenes
        from benchforge_core.spatial_learning.scenes import bbox
        for profile in ['linear','turning','orbit','reversal']:
            template=next(t for t in templates('N04') if t['scene_profile']==profile)
            endpoints=set()
            for seed in range(62100,62112):
                scene=create_scene(template,seed,3);poses=scene['motion']['camera_poses']
                self.assertEqual(poses[0],[0,0,0])
                self.assertGreater(sum(math.dist(a[:2],b[:2]) for a,b in zip(poses,poses[1:])),.01)
                endpoints.add(tuple(round(v,5) for v in poses[-1]))
                frames,_=observed_scenes(scene,'N04')
                self.assertNotEqual(frames[0]['objects'][0]['position'],frames[-1]['objects'][0]['position'])
                for frame in frames:
                    for obj in frame['objects']:
                        self.assertTrue(all(0<=v<=10 for v in bbox(obj)),(profile,seed,bbox(obj)))
            self.assertGreater(len(endpoints),1,profile)

    def test_turning_motion_retains_observed_turns_and_stationary_controls(self):
        import math
        template=next(t for t in templates('N05') if t['scene_profile']=='turning')
        turns=stationary=0
        for seed in range(62100,62140):
            positions=create_scene(template,seed,2)['motion']['positions']
            steps=[[b[j]-a[j] for j in range(2)] for a,b in zip(positions,positions[1:])]
            stationary+=sum(math.hypot(*s) for s in steps)<.01
            turns+=any(abs(a[0]*b[1]-a[1]*b[0])>.001 for a,b in zip(steps,steps[1:]))
        self.assertGreater(turns,10)
        self.assertGreater(stationary,0)

    def test_learning_installer_keeps_venv_interpreter_path(self):
        import os
        import subprocess
        import sys
        import venv
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);environment=root/'venv'
            venv.EnvBuilder(with_pip=False,symlinks=os.name!='nt').create(environment)
            python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            preset=root/'custom.patch.yml'
            preset.write_text(yaml.safe_dump([{'insert':[{'name':'@deepseek-ai/dsh-agent-preset','config':{'id':'learning','plugins':[]}}]}]))
            installer=Path(__file__).resolve().parents[1]/'integrations/dsh/install_learning.py'
            subprocess.run([sys.executable,str(installer),'--preset',str(preset),'--python',str(python),'--dsh-root',str(root)],check=True,capture_output=True)
            config=yaml.safe_load(preset.read_text())[0]['insert'][0]['config']['plugins'][0]['config']
            self.assertEqual(config['python'],str(python.absolute()))


if __name__=='__main__':unittest.main()
