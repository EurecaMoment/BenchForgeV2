import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from spatialforge.layout import prepare_layout,validate_layout
from spatialforge import engine
from test_contracts import sample


class LayoutGuidance(unittest.TestCase):
    def tools(self,root):
        class Tools:
            calls=[]
            def execute(self,name,request,work,stop):
                self.calls.append((name,request))
                Image.new('RGB',(32,24),'tan').save(request['output'])
                return {'status':'ok'}
            def source_path(self,value):
                p=Path(value).resolve()
                if not p.is_file() or not p.is_relative_to(root):raise ValueError('invalid source')
                return p
        return Tools()

    def test_generate_once_and_reuse_reference_across_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'revision_0';b=root/'revision_1';a.mkdir();b.mkdir()
            tools=self.tools(root);intent={'layout':{'mode':'generate','prompt':'Reading and work zones','seed':7}}
            prepare_layout(tools,intent,a,threading.Event());prepare_layout(tools,intent,b,threading.Event())
            self.assertEqual(len(tools.calls),1)
            self.assertEqual((a/'layout_reference.png').read_bytes(),(b/'layout_reference.png').read_bytes())
            receipt=json.loads((b/'layout_reference.json').read_text())
            self.assertFalse(receipt['gt_source']);self.assertFalse(receipt['metric_layout_verified'])
            with self.assertRaisesRegex(ValueError,'changed'):
                prepare_layout(tools,{'layout':{'mode':'generate','prompt':'Changed room'}},b,threading.Event())

    def test_edit_parent_view_uses_image_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent';(parent/'capture').mkdir(parents=True);directory=root/'child'/'revision_0';directory.mkdir(parents=True)
            source=parent/'capture'/'view_1.png';Image.new('RGB',(28,19),'blue').save(source);before=source.read_bytes()
            tools=self.tools(root)
            prepare_layout(tools,{'layout':{'mode':'edit','prompt':'Add a quiet reading zone','source_view':1}},directory,threading.Event(),parent)
            self.assertEqual(tools.calls[0][1]['image'],str(source))
            self.assertEqual(source.read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'unavailable'):
                prepare_layout(tools,{'layout':{'mode':'reference','source_view':9}},directory,threading.Event(),parent)

    def test_validation_and_reference_source_requirements(self):
        for value in ({'mode':'generate','prompt':'x','source_image':'x'},{'mode':'edit'},{'mode':'reference','source_view':-1},{'mode':'reference','source_view':True}):
            with self.assertRaises(ValueError):validate_layout(value)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'revision_0';directory.mkdir()
            with self.assertRaisesRegex(ValueError,'source_image'):
                prepare_layout(self.tools(root),{'layout':{'mode':'reference'}},directory,threading.Event())

    def test_unspecified_refine_layout_inherits_design_reference_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent/revision_2';parent.mkdir(parents=True)
            tools=self.tools(root)
            prepare_layout(tools,{'layout':{'mode':'generate','prompt':'photographic workroom'}},parent,threading.Event())
            before=(parent/'layout_reference.png').read_bytes()
            intent={'refine_task_id':'parent','description':'improve current scene'}
            for revision in (0,1):
                child=root/'child'/f'revision_{revision}';child.mkdir(parents=True)
                prepare_layout(tools,intent,child,threading.Event(),parent)
                self.assertEqual((child/'layout_reference.png').read_bytes(),before)
                receipt=json.loads((child/'layout_reference.json').read_text())
                self.assertEqual(receipt['tool'],'inherited_design_reference')
                self.assertEqual(receipt['inherited_from']['reference_receipt']['tool'],'FLUX.2-klein-9B')
                self.assertFalse(receipt['gt_source'])
            self.assertEqual(len(tools.calls),1);self.assertNotIn('layout',intent)
            self.assertEqual((parent/'layout_reference.png').read_bytes(),before)

    def test_explicit_layout_wins_and_missing_design_does_not_substitute_simulator_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent/revision_0';(parent/'capture').mkdir(parents=True)
            Image.new('RGB',(24,24),'blue').save(parent/'capture/view_0.png')
            child=root/'child/revision_0';child.mkdir(parents=True);tools=self.tools(root)
            self.assertIsNone(prepare_layout(tools,{},child,threading.Event(),parent))
            prepare_layout(tools,{'layout':{'mode':'generate','prompt':'new photographic reference'}},child,threading.Event(),parent)
            self.assertEqual(len(tools.calls),1)
            self.assertNotIn('inherited_from',json.loads((child/'layout_reference.json').read_text()))

    def test_incomplete_or_untrusted_parent_reference_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent';parent.mkdir();child=root/'child/revision_0';child.mkdir(parents=True)
            Image.new('RGB',(24,24),'blue').save(parent/'layout_reference.png')
            with self.assertRaisesRegex(ValueError,'incomplete'):prepare_layout(self.tools(root),{},child,threading.Event(),parent)
            (parent/'layout_reference.json').write_text('{"gt_source":true}')
            with self.assertRaisesRegex(ValueError,'provenance'):prepare_layout(self.tools(root),{},child,threading.Event(),parent)

    def test_scene_planner_receives_reference_and_native_gt_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            class Store:
                def __init__(self):self.root=root
                def directory(self,tid,revision):
                    p=root/tid/str(revision);p.mkdir(parents=True,exist_ok=True);return p
                def snapshot(self,*args):return {'state':'RUNNING'}
                def update(self,*args,**kwargs):self.updated=kwargs
            store=Store();image=root/'layout.png';Image.new('RGB',(32,24)).save(image)
            task={'id':'scene','run_id':'run','attempt':0,'unit':{'revision':0,'intent':{'layout':{'mode':'reference','source_image':str(image)}}}}
            with patch.object(engine,'completion',return_value=sample()) as model:
                engine.plan_scene(store,task,threading.Event())
            self.assertEqual(len(model.call_args.args[2]),1)
            self.assertIn('native GT',model.call_args.args[0])
            self.assertTrue((store.directory('scene',0)/'layout_reference.json').exists())
            self.assertEqual(store.updated['unit']['phase'],'capture')


if __name__=='__main__':unittest.main()
