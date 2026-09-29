"""Bounded, offline checks of the real legacy data adapter (no model requests)."""
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

from spatialforge.integration import _brief, prepare_spec, run_dataset


class DataStatus(unittest.TestCase):
    def test_quarantine_gate_reasons_survive_status_export(self):
        issues=[{'code':'EMPTY_DATASET','severity':'error','message':'No accepted items'}]
        snapshot={'id':'run_gate','state':'FAILED_FINAL','tasks':[{
            'task_id':'validate','state':'QUARANTINED','attempt':1,'failure':None,
            'artifact':None,'result':{'issues':issues,'metrics':{'items':0},'bundle':{'answers':['private GT']}}
        }]}
        brief=_brief(snapshot)
        self.assertEqual(brief['tasks'][0]['issues'],issues)
        self.assertEqual(brief['tasks'][0]['metrics'],{'items':0})
        self.assertNotIn('bundle',brief['tasks'][0])


@unittest.skipUnless(importlib.util.find_spec('benchclaw'), 'Run with the installed BenchClaw Harness environment')
class DataIntegration(unittest.TestCase):
    def spec(self, root, split='test'):
        return {'name':'adapter_smoke', 'objective':'One-record development smoke test with preserved source answer',
                'sources':[{'source_id':'official', 'plugin':'source.evalset',
                            'parameters':{'path':str(root/'source.jsonl'), 'source_uri':'local:offline-test',
                                          'license_id':'synthetic-test-fixture', 'split':split, 'indices':[0]}}],
                'target_items':1, 'capabilities':['official_qa'], 'cleaning':'none'}

    def test_official_test_split_cannot_silently_become_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'already assigned to train'):
                prepare_spec({'spec':self.spec(Path(tmp)), 'split':'train'})

    def test_non_isaac_capture_is_excluded_before_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self.spec(Path(tmp))
            spec['sources'][0]['plugin'] = 'simulator.habitat'
            with self.assertRaisesRegex(ValueError, 'desktop Isaac'):
                prepare_spec({'spec':spec})

    def test_review_contract_preserves_source_and_has_no_evaluation(self):
        from benchclaw.compiler import compile_spec
        from benchclaw.plugins import Registry
        with tempfile.TemporaryDirectory() as tmp:
            spec = prepare_spec({'spec':self.spec(Path(tmp))})
            plan = compile_spec(spec, Registry())
            plugins = [u.plugin_id for u in plan.tasks]
            self.assertIn('review.semantic', plugins)
            self.assertIn('review.collection', plugins)
            self.assertEqual(spec.semantic_review['model_id'], 'Qwen/Qwen3.8-Flash-Next')
            self.assertFalse(any('evaluation' in p or 'evaluator' in p for p in plugins))

    def test_real_export_reuses_linked_run_and_stops_without_success(self):
        from PIL import Image, ImageDraw
        from sqlalchemy import select
        from benchclaw.metadata import Repository, runs, tasks
        from spatialforge.generation import ResourceWait
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image=Image.new('RGB', (80, 60), '#b37f42')
            ImageDraw.Draw(image).rectangle((10, 10, 40, 45), fill='#3181c5')
            image.save(root/'view.png')
            (root/'source.jsonl').write_text(json.dumps({'images':['view.png'], 'prompt':'Which source label was assigned?',
                                                        'choices':{'A':'brown', 'B':'blue'}, 'answer_type':'single_choice',
                                                        'gold':'A', 'rubric_id':'choice_exact/v1', 'language':'en'})+'\n')
            repo = Repository('sqlite:///'+str(root/'metadata.db'))
            intent = {'spec':self.spec(root), 'review':False}
            task = {'id':'sf_test.scene0', 'run_id':'sf_test', 'unit':{'intent':intent, 'phase':'dataset', 'revision':0}}
            with repo.transaction() as conn:
                conn.execute(runs.insert().values(id='sf_test', state='PENDING', plan={}, created_at='test', code_revision='spatialforge-0.2.0'))
                conn.execute(tasks.insert().values(id=task['id'], run_id='sf_test', task_id='scene0', unit=task['unit'],
                                                   state='RUNNING', attempt=0, ready_at=0))
            class Store:
                def __init__(self):
                    self.root=root/'runtime'; self.repo=repo
                def snapshot(self, rid): return repo.status(rid)
                def directory(self, tid, revision):
                    p=self.root/tid/f'revision_{revision}';p.mkdir(parents=True,exist_ok=True);return p
            store = Store()
            stop = threading.Event(); stop.set()
            with self.assertRaises(ResourceWait): run_dataset(store, task, stop)
            first = run_dataset(store, task)
            second = run_dataset(store, task)
            self.assertEqual(first['harness_run_id'], second['harness_run_id'])
            self.assertEqual(first['release']['release_id'], second['release']['release_id'])
            self.assertFalse(first['target_model_evaluation'])
            authority = Path(first['release']['authority_bundle_uri'])
            answers = [json.loads(line) for line in (authority/'answers.jsonl').read_text().splitlines()]
            self.assertEqual(answers[0]['gold'], 'A')
            self.assertTrue(list(Path(first['release']['visible_bundle_uri']).glob('media/*.png')))
            with repo.engine.connect() as conn:
                linked = conn.execute(select(tasks.c.unit).where(tasks.c.id == task['id'])).scalar_one()
            self.assertEqual(linked['harness_run_id'], first['harness_run_id'])


if __name__ == '__main__': unittest.main()
