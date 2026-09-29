import json
from pathlib import Path
import tempfile
import unittest
from spatialforge.operator_evidence import evidence


class PublicEvidence(unittest.TestCase):
    def test_view_image_maps_pixels_to_captured_objects_in_selected_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root = Path(temp)
                def snapshot(self, rid):
                    return {'tasks': [{'id': rid+'.scene0', 'state': 'SUCCEEDED', 'unit': {'revision': 1}}]}
            store = Store()
            capture = store.root/'sf_pose.scene0/revision_0/capture'
            capture.mkdir(parents=True)
            newer = store.root/'sf_pose.scene0/revision_1/capture'
            newer.mkdir(parents=True)
            frame = {'image_size': {'width': 960, 'height': 720},
                'camera': {'position': [0, 0, 2.3], 'target': [0, 0, 0], 'up': [0, 1, 0]},
                'objects': [{'object_id': 'cand_0', 'label': 'spruce_90',
                    'bbox_2d': {'xyxy': [0, 331, 146, 404]}, 'mask': {'area_px': 3730},
                    'depth_z_median': 2.11}]}
            image = capture/'view_1.png'
            image.write_bytes(b'original capture image')
            metadata = capture/'view_1.json'
            metadata.write_text(json.dumps(frame))
            (newer/'view_1.png').write_bytes(b'new revision image')
            (newer/'view_1.json').write_text(json.dumps({**frame, 'objects': []}))
            before = (image.read_bytes(), metadata.read_bytes())
            direct = evidence(store, 'sf_pose.scene0', 0, 'capture/view_1.png')
            context = direct['image_context']
            self.assertEqual(context['metadata_file'], 'capture/view_1.json')
            self.assertEqual(context['visible_object_columns'], ['object_id', 'label', 'bbox_xyxy', 'visible_pixels'])
            self.assertEqual(context['visible_objects'], [['cand_0', 'spruce_90', [0, 331, 146, 404], 3730]])
            self.assertEqual(context['image_size'], frame['image_size'])
            self.assertEqual(context['camera'], frame['camera'])
            self.assertNotIn('depth_z_median', json.dumps(context))
            self.assertEqual(Path(direct['image_path']).read_bytes(), before[0])
            copied = evidence(store, 'sf_pose.scene0', 0, 'capture/view_1.png', 'inspect_pose')
            self.assertEqual(copied['image_context'], context)
            self.assertEqual(Path(copied['source_path']).read_bytes(), before[0])
            self.assertEqual(evidence(store, 'sf_pose.scene0', file='capture/view_1.png')['image_context']['visible_objects'], [])
            self.assertEqual(evidence(store, 'sf_pose.scene0', 0, 'capture/view_1.json')['data'], frame)
            self.assertEqual((image.read_bytes(), metadata.read_bytes()), before)

    def test_image_without_capture_metadata_still_returns_original_image(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root = Path(temp)
                def snapshot(self, rid):
                    return {'tasks': [{'id': rid+'.scene0', 'state': 'SUCCEEDED', 'unit': {'revision': 0}}]}
            store = Store()
            revision = store.root/'sf_image.scene0/revision_0'
            (revision/'capture').mkdir(parents=True)
            (revision/'generation').mkdir()
            (revision/'generation/reference.json').write_text('{"not_capture_metadata":true}')
            for file in ('capture/view_0.png', 'generation/reference.png'):
                with self.subTest(file=file):
                    (revision/file).write_bytes(b'image')
                    value = evidence(store, 'sf_image.scene0', file=file)
                    self.assertNotIn('image_context', value)
                    self.assertEqual(Path(value['image_path']).read_bytes(), b'image')

    def test_completed_export_is_discoverable_readable_and_copied_without_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            class Store:
                root = Path(temp)
                def snapshot(self, rid):
                    return {'tasks': [{'id': rid+'.scene0', 'state': 'SUCCEEDED', 'unit': {'revision': 1}}]}
            store = Store()
            release = store.root/'sf_export.scene0/revision_0/release'
            (release/'images').mkdir(parents=True)
            (store.root/'sf_export.scene0/revision_1').mkdir()
            question = [{'item_id': 'q1', 'prompt': 'Which object is nearer?', 'media_refs': ['images/q1.png']}]
            for name, value in [('model_bundle.json', question), ('complete.json', {'accepted': 1, 'scene_quality_passed': False}),
                                ('authority_bundle.json', [{'answer': 'A'}])]:
                (release/name).write_text(json.dumps(value))
            for name in ('model_bundle.zip', 'scene_bundle.zip', 'interaction_bundle.zip', 'authority_bundle.zip', 'training_bundle.zip', 'sft.jsonl'):
                (release/name).write_bytes(name.encode())
            (release/'images/q1.png').write_bytes(b'image payload')

            listing = evidence(store, 'sf_export.scene0', 0, 'release', 'inspect')
            names = {row['file'] for row in listing['files']}
            self.assertEqual(names, {'release/'+n for n in ('model_bundle.json', 'complete.json', 'model_bundle.zip',
                'scene_bundle.zip', 'interaction_bundle.zip', 'images/q1.png')})
            default = evidence(store, 'sf_export.scene0')['revisions'][0]
            self.assertTrue(names.issubset({row['file'] for row in default['files']}))
            self.assertEqual(evidence(store, 'sf_export.scene0', 0, 'release/model_bundle.json')['data'], question)
            self.assertFalse(evidence(store, 'sf_export.scene0', 0, 'release/complete.json')['data']['scene_quality_passed'])
            self.assertEqual(Path(evidence(store, 'sf_export.scene0', 0, 'release/images/q1.png')['image_path']).read_bytes(), b'image payload')
            copied = evidence(store, 'sf_export.scene0', 0, 'release/scene_bundle.zip', 'inspect')
            Path(copied['source_path']).write_bytes(b'edited task copy')
            self.assertEqual((release/'scene_bundle.zip').read_bytes(), b'scene_bundle.zip')
            for name in ('authority_bundle.json', 'authority_bundle.zip', 'training_bundle.zip', 'sft.jsonl'):
                with self.assertRaises(ValueError):
                    evidence(store, 'sf_export.scene0', 0, 'release/'+name, 'inspect')
            self.assertEqual(evidence(store, 'sf_export.scene0', 1, 'release')['files'], [])


if __name__ == '__main__':
    unittest.main()
