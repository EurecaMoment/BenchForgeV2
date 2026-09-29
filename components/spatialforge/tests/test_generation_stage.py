"""Stage composition with real artifact files and mocked inference, no GPU."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from spatialforge import generation_stage as stage
from spatialforge.generation import GenerationTools


class GenerationStage(unittest.TestCase):
    def test_independent_outputs_compose_and_register_only_on_request(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls, registrations, updates = [], [], []

            class Tools(GenerationTools):
                @property
                def config(self):
                    return SimpleNamespace(model=lambda name: {'path': str(root / name)},
                                           data={'sources': {'sam3d': str(root / 'sam3d')}})

                def execute(self, name, request, work, stop):
                    calls.append((name, request))
                    if name == 'diffusion':
                        Image.new('RGB', (64, 48), 'tan').save(request['output'])
                        return {'status': 'ok', 'output': request['output']}
                    output = Path(request['output_dir'])
                    output.mkdir(parents=True)
                    if name == 'sam3':
                        for index in range(2):
                            Image.new('L', (64, 48), 255).save(output / f'mask_{index}.png')
                        return {'status': 'ok', 'segments': [
                            {'mask': f'mask_{index}.png', 'label': label, 'score': .9 - index / 10}
                            for index, label in enumerate(request['prompts'])]}
                    assets = []
                    for item in request['objects']:
                        filename = item['object_id'] + '.glb'
                        (output / filename).write_bytes(b'raw-worker-mesh')
                        assets.append({'object_id': item['object_id'], 'asset': filename,
                                       'rotation_wxyz': [1, 0, 0, 0], 'translation': [1, 2, 3], 'scale': [2]})
                    return {'status': 'ok', 'assets': assets}

                def _publish(self, spec, work, source, frame, provenance, status, image=None, mask=None):
                    registrations.append({'spec': spec, 'source': str(source), 'frame': frame})
                    asset_id = 'asset_1234567890abcdef'
                    folder = self.assets / asset_id
                    folder.mkdir()
                    (folder / 'mesh.json').write_text('{}')
                    result = {'asset_id': asset_id, 'geometry': {'coordinate_frame': frame}}
                    (work / 'asset_ref.json').write_text(json.dumps(result))
                    return result

            class Store:
                def __init__(self):
                    self.root = root

                def directory(self, task_id, revision):
                    folder = root / task_id / f'revision_{revision}'
                    folder.mkdir(parents=True, exist_ok=True)
                    return folder

                def update(self, task_id, **value):
                    updates.append((task_id, value))

            store = Store()

            def run(name, parameters):
                task = {'id': name + '.scene0', 'unit': {'revision': 0, 'workflow': 'generation',
                        'phase': 'generation', 'intent': {'tool': name, 'parameters': parameters}}}
                result = stage.execute_generation_stage(store, task, Event())
                receipt = store.directory(task['id'], 0) / 'generation_stage.json'
                self.assertEqual(json.loads(receipt.read_text()), result)
                self.assertFalse(result['gt_source'])
                for artifact in result['files']:
                    self.assertTrue(Path(artifact['source_path']).is_file())
                    self.assertEqual(Path(artifact['source_path']), receipt.parent / artifact['file'])
                return result

            with patch.object(stage, 'GenerationTools', Tools):
                prompt = 'Keep the whole room and its two objects.'
                image = run('diffusion', {'prompt': prompt, 'width': 64, 'height': 48, 'steps': 6, 'seed': 13})
                self.assertEqual(calls[0][1]['prompt'], prompt)
                self.assertEqual(calls[0][1]['steps'], 6)
                self.assertEqual([name for name, _ in calls], ['diffusion'])
                segmentation = run('sam3', {'source_image': image['source_path'], 'prompts': ['cup', 'bowl']})
                self.assertEqual(len(segmentation['segments']), 2)
                self.assertEqual(sum(row['kind'] == 'mask' for row in segmentation['files']), 2)
                masks = [segment['source_path'] for segment in segmentation['segments']]
                meshes = run('sam3d', {'source_image': image['source_path'], 'objects': [
                    {'object_id': label, 'source_mask': mask, 'seed': 5 + index}
                    for index, (label, mask) in enumerate(zip(['cup', 'bowl'], masks))]})
                self.assertEqual(registrations, [])
                self.assertEqual(len(meshes['assets']), 2)
                self.assertEqual(meshes['assets'][0]['translation'], [1, 2, 3])
                self.assertEqual([item['mask'] for item in calls[-1][1]['objects']], masks)
                self.assertFalse(any('asset_id' in row for row in meshes['assets']))
                source = meshes['assets'][0]
                parameters = {'source_mesh': source['source_path'], 'label': 'cup',
                              'source_frame': source['source_frame']}
                imported = run('mesh_import', parameters)
                replay = run('mesh_import', parameters)
                self.assertEqual(len(registrations), 1)
                self.assertEqual(registrations[0]['frame'], 'sam3d_camera')
                self.assertEqual(imported['assets'][0]['asset_id'], replay['assets'][0]['asset_id'])
                self.assertEqual([name for name, _ in calls], ['diffusion', 'sam3', 'sam3d'])
                self.assertTrue(all(value['state'] == 'SUCCEEDED' and value['unit']['phase'] == 'complete'
                                    for _, value in updates))


if __name__ == '__main__':
    unittest.main()
