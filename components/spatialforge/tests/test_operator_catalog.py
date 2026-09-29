import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from spatialforge import operator_catalog as catalog
from spatialforge.generation import GenerationTools


class OperatorCatalog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SimpleNamespace(root=self.root, harness=self.root)
    def tearDown(self): self.temp.cleanup()

    def test_overview_does_not_load_meshes_or_legacy_data(self):
        with patch.object(catalog, '_load_rows', side_effect=AssertionError('overview must be cheap')):
            result = catalog.catalog_response(self.store, {})
        self.assertLess(len(catalog._encoded(result)), catalog.MAX_RESPONSE_BYTES)
        self.assertIn('spatialforge_layout', json.dumps(result))
        self.assertIn('scene_schema', result['sections'])
        self.assertFalse(result['model_can_edit_harness_code'])

    def test_utf8_byte_bound_and_complete_continuation(self):
        rows = [{'id': str(i), 'value': '陶瓷' * 600} for i in range(13)]
        seen = []; offset = 0
        with patch.object(catalog, '_load_rows', return_value=rows):
            while True:
                result = catalog.catalog_response(self.store, {'section': 'contracts', 'limit': 20, 'offset': offset})
                self.assertLessEqual(len(catalog._encoded(result)), catalog.MAX_RESPONSE_BYTES)
                seen.extend(row['id'] for row in result['items'])
                if result['next_offset'] is None: break
                self.assertGreater(result['next_offset'], offset)
                offset = result['next_offset']
        self.assertEqual(seen, [row['id'] for row in rows])

    def test_oversized_metadata_copied_losslessly_before_paging(self):
        rows = [{'id': 'long', 'value': 'bowl ' * 10000}, {'id': 'small', 'value': 'jar'}]
        with patch.object(catalog, '_load_rows', return_value=rows):
            result = catalog.catalog_response(self.store, {'section': 'contracts', 'limit': 1, 'workspace_id': 'read_catalog'})
            second = catalog.catalog_response(self.store, {'section': 'contracts', 'offset': result['next_offset'], 'limit': 1})
        self.assertTrue(result['items'][0]['inline_omitted'])
        self.assertEqual(second['items'][0]['id'], 'small')
        copy = Path(result['copy']['source_path'])
        self.assertEqual(json.loads(copy.read_text())['items'], rows)
        self.assertTrue(copy.is_relative_to(self.root / 'operator_workspaces'))
        copy.write_text('edited task copy')
        self.assertEqual(rows[0]['value'], 'bowl ' * 10000)

    def test_search_selected_detail_and_overview_avoid_unrelated_mesh_reads(self):
        for i, label in ((1, 'Ceramic Bowl'), (2, 'Watering Can')):
            folder = self.root / 'generated_assets' / f'asset_{i:016x}'; folder.mkdir(parents=True)
            (folder / 'asset.json').write_text(json.dumps({'asset_id': folder.name, 'label': label, 'appearance': {}}))
            (folder / 'mesh.json').write_text(json.dumps({'vertices': [[0,0,0]], 'bounds': [[0,0,0],[1,2,3]], 'coordinate_frame': 'z_up'}))
        original = Path.read_text; reads = []
        def tracked(path, *args, **kwargs):
            if path.name == 'mesh.json': reads.append(path.parent.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', tracked):
            result = catalog.catalog_response(self.store, {'section': 'generated_assets', 'query': 'CERAMIC'})
            self.assertEqual(reads, [])
            selected = catalog.catalog_response(self.store, {'section': 'generated_assets', 'item_id': result['items'][0]['id']})
        self.assertEqual(reads, ['asset_0000000000000001'])
        self.assertEqual(selected['items'][0]['value']['geometry']['source_extent'], [1,2,3])
        self.assertEqual(len(GenerationTools(self.root).catalog()), 2)

    def test_schema_copy_reconstructs_complete_contract_and_invalid_inputs_fail(self):
        result = catalog.catalog_response(self.store, {'section': 'scene_schema', 'workspace_id': 'schema_reader'})
        rows = json.loads(Path(result['copy']['source_path']).read_text())['items']
        self.assertEqual(''.join(row['text'] for row in rows), catalog.SCENE_SCHEMA_DESCRIPTION)
        for request in ({'section':'missing'}, {'section':'contracts','limit':True}, {'offset':-1}, {'limit':0}, {'query':42}, {'workspace_id':'../escape'}):
            with self.assertRaises(ValueError): catalog.catalog_response(self.store, request)
        outside=self.root/'outside';outside.mkdir()
        (self.root/'operator_workspaces/link').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): catalog.catalog_response(self.store, {'section':'scene_schema','workspace_id':'link'})

    def test_page_count_and_disk_copy_have_no_duplicate_caps(self):
        small=[{'id':str(i),'value':'item'} for i in range(40)]
        with patch.object(catalog,'_load_rows',return_value=small):
            default=catalog.catalog_response(self.store,{'section':'contracts'})
            selected=catalog.catalog_response(self.store,{'section':'contracts','limit':40})
        self.assertEqual(len(default['items']),20)
        self.assertEqual(len(selected['items']),40)
        rows=[{'id':'large','value':'x'*(8*1024*1024+1)}]
        with patch.object(catalog,'_load_rows',return_value=rows):
            result=catalog.catalog_response(self.store,{'section':'contracts','workspace_id':'large_copy'})
        self.assertEqual(json.loads(Path(result['copy']['source_path']).read_text())['items'],rows)
        self.assertLessEqual(len(catalog._encoded(result)),catalog.MAX_RESPONSE_BYTES)

    def test_dataset_lookup_is_lazy_and_excludes_evaluator_section(self):
        legacy={'templates':{'templates':[{'template_id':'T021','description':'left-right'}], 'sets':{'selected':['T021']}}}
        with patch('spatialforge.integration.catalog', return_value=legacy) as source:
            catalog.catalog_response(self.store, {'section':'contracts'})
            source.assert_not_called()
            result=catalog.catalog_response(self.store, {'section':'dataset_templates','item_id':'T021'})
            source.assert_called_once_with(self.root)
        self.assertEqual(result['items'][0]['value']['description'], 'left-right')
        self.assertNotIn('evaluators', catalog.SECTIONS)


if __name__ == '__main__': unittest.main()
