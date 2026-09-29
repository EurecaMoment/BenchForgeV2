import json
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from spatialforge import engine
from spatialforge.generation import GenerationTools


class AssetLabel(unittest.TestCase):
    def test_semantic_label_reaches_sam_and_registration_while_name_remains_task_name(self):
        for label,baking in product(('leather stitching awl',None),(None,False,True)):
            with self.subTest(label=label,texture_baking=baking),TemporaryDirectory() as tmp:
                root=Path(tmp);stop=Event();calls=[];published=[];updates=[]
                source=root/'source.png';Image.new('RGB',(32,32),'gray').save(source)
                intent={'name':'studio_hero_tool_v2','description':'Exact caller asset description','source_image':str(source)}
                if label is not None:intent['label']=label
                if baking is not None:intent['texture_baking']=baking
                task={'id':'label.scene0','run_id':'label','state':'PENDING','unit':{'phase':'asset','revision':0,'intent':intent}}
                class Tools(GenerationTools):
                    def source_path(self,path):return Path(path)
                    @property
                    def config(self):return SimpleNamespace(model=lambda name:{'path':str(root/name)},data={'sources':{'sam3d':str(root/'sam3d')}})
                    def execute(self,name,request,work,signal):
                        calls.append((name,request))
                        out=Path(request['output_dir']);out.mkdir(parents=True,exist_ok=True)
                        if name=='sam3':
                            Image.new('L',(32,32),255).save(out/'mask.png')
                            return {'segments':[{'mask':'mask.png','box':[0,0,32,32],'score':1}]}
                        (out/'subject.glb').write_bytes(b'geometry fixture')
                        return {'assets':[{'object_id':'subject','asset':'subject.glb'}]}
                    def _publish(self,spec,*args):
                        published.append(spec);return {'asset_id':'asset_0123456789abcdef','label':spec['label']}
                class Store:
                    def __init__(self):self.root=root
                    def directory(self,*args):
                        path=root/'task';path.mkdir(exist_ok=True);return path
                    def all_work(self):return [task]
                    def snapshot(self,*args):return {'state':'RUNNING'}
                    def settle_runs(self):pass
                    def update(self,task_id,**values):
                        updates.append(values)
                        if values['state'] in {'SUCCEEDED','FAILED_FINAL'}:stop.set()
                with patch.object(engine,'GenerationTools',Tools),patch.object(engine,'review_generated_asset',side_effect=lambda tools,spec,result,*args,**kwargs:result) as review:
                    engine.coordinate(Store(),stop)
                self.assertIs(review.call_args.kwargs['repair'],False)
                expected=label if label is not None else intent['name']
                self.assertEqual(updates[-1]['state'],'SUCCEEDED',updates[-1])
                self.assertEqual(calls[0][0],'sam3')
                self.assertEqual(calls[0][1]['prompts'],[expected])
                self.assertEqual(published[0]['label'],expected)
                self.assertEqual(published[0]['prompt'],intent['description'])
                self.assertEqual(task['unit']['intent']['name'],'studio_hero_tool_v2')
                self.assertEqual(calls[1][0],'sam3d')
                if baking is True:self.assertIs(calls[1][1]['texture_baking'],True)
                else:self.assertNotIn('texture_baking',calls[1][1])


if __name__=='__main__':unittest.main()
