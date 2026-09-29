import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from benchforge_core.evaluation import score_predictions,model_eval
from benchforge_core.artifacts import jsonl
from benchforge_core.research import review,design
from benchforge_core.recipes import compute,generate


class ProductionTests(unittest.TestCase):
    def test_collection_rejects_constant_answer_shortcut(self):
        from benchforge_core.collection import assess
        items=[{'id':str(i),'question':'Compare A and B','template_id':'relation','source':str(i%2),
            'media':[str(i)+'.png'],'evidence_refs':[str(i)],'answer':'A',
            'answerability_proof':{'visible_media':[str(i)+'.png'],'question_references_visible_anchor':True,
            'why_visible_anchor_is_sufficient':'A and B identify the visible regions'}} for i in range(4)]
        report=assess(items,{'max_template_majority':0.75,'min_sources':2})
        self.assertEqual(report['failures'],['constant_answer_shortcut'])
    def test_temporal_recipe_rejects_unordered_evidence_and_ties(self):
        self.assertEqual(compute({'op':'difference','inputs':['/start','/end']},{'start':2,'end':5}),3)
        with self.assertRaisesRegex(ValueError,'tie'):
            compute({'op':'order','inputs':['/a','/b'],'labels':['A','B']},{'a':3,'b':3})
        result,rejected=generate('.', [{'id':'frame','provenance':{'kind':'simulation'},'sequence_semantics':'independent_capture'}],
            [{'template_id':'motion','sequence_semantics':'ordered_sequence'}])
        self.assertEqual(result,[])
        self.assertIn('Sequence semantics',rejected[0]['reason'])

    def test_native_replay_detects_drift(self):
        import numpy as np
        from benchforge_core.replay import replay
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);np.save(root/'depth.npy',np.ones((3,3)))
            jsonl(root/'evidence_index.jsonl',[{'id':'native','raw_depth_path':'depth.npy',
                'camera':{'fx':2,'fy':2,'cx':1,'cy':1},'objects':[{'object_id':'patch','bbox_xyxy':[1,1,2,2],'depth_median':1}]}])
            self.assertEqual(replay(root)['status'],'passed')
            np.save(root/'depth.npy',np.ones((3,3))*2)
            self.assertEqual(replay(root)['status'],'failed')

    def test_metrics_and_incomplete_responses(self):
        items=[{'id':'a','answer':['A','C'],'metric_id':'set_f1'},
               {'id':'b','answer':['A','B','C'],'metric_id':'order_exact_accuracy'},
               {'id':'c','answer':3.0,'metric_id':'numeric_tolerance','tolerance':0.1}]
        result=score_predictions(items,[{'id':'a','answer':['A']},{'id':'c','answer':3.05}])
        self.assertAlmostEqual(result['overall']['score'],(2/3+1)/3)
        self.assertEqual(result['overall']['missing'],1)
        wrapped=score_predictions([{'id':'x','answer':'A','metric_id':'accuracy'}],[{'id':'x','answer':{'answer':'A'}}])
        self.assertEqual(wrapped['overall']['score'],1)
        blank=score_predictions([{'id':'x','answer':'A','metric_id':'accuracy'}],[{'id':'x','answer':''}])
        self.assertEqual(blank['overall']['missing'],1)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            score_predictions(items,[{'id':'a','answer':[]},{'id':'a','answer':[]}])
        with self.assertRaisesRegex(ValueError,'Unknown'):
            score_predictions(items,[{'id':'wrong','answer':'A'}])

    def test_inference_never_sends_authority(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.end_headers()
                answer='' if len(received)==1 else 'A'
                self.wfile.write(json.dumps({'choices':[{'message':{'content':answer}}]}).encode())
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever);worker.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);source=root/'items.jsonl'
                jsonl(source,[{'id':'q','question':'Choose a letter','answer':'SECRET_GOLD','raw_depth':'SECRET_BUFFER','media':[]}])
                result=model_eval({'public_items':str(source),'models':['fixture']},root,
                    {'models':{'fixture':{'model':'fixture','url':f'http://127.0.0.1:{server.server_port}'}}})
                self.assertEqual(result['status'],'completed')
                self.assertEqual(len(received),2)
                self.assertNotIn('SECRET',json.dumps(received))
        finally:server.shutdown();worker.join();server.server_close()

    def test_citation_and_design_contract_reject_unconsumed_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);text=root/'paper.txt'
            text.write_text('A verifiable passage about deterministic benchmark scoring and original labels.',encoding='utf-8')
            index=root/'index.jsonl';jsonl(index,[{'id':'paper','access_status':'downloaded','text':str(text)}])
            result=review({'index':str(index),'claims':[{'paper_id':'paper','claim':'invented','quote':'This quotation is deliberately absent from the downloaded full text.'}]},root,{})
            self.assertEqual(result['rejected'],1)
            with self.assertRaisesRegex(ValueError,'Source binding'):
                design({'spec':{'objective':'test','capabilities':[{'id':'spatial'}],'sources':[{'id':'real'}],
                    'templates':[{'id':'t','capabilities':['spatial'],'metric':'accuracy','sources':['nonexistent']}],
                    'metrics':[{'id':'accuracy'}]}},root,{})


if __name__=='__main__':unittest.main()
