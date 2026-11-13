"""Focused preset composition test; uses the official installed package exports."""
import importlib.util
from pathlib import Path
import unittest
from copy import deepcopy

INTEGRATIONS=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('combined_preset',INTEGRATIONS/'spatialforge/build_preset.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
spec=importlib.util.spec_from_file_location('development_preset',INTEGRATIONS/'spatialforge/build_development_preset.py')
development=importlib.util.module_from_spec(spec)
spec.loader.exec_module(development)
spec=importlib.util.spec_from_file_location('preset_catalog',INTEGRATIONS/'dsh/build_presets.py')
catalog=importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class PresetBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = builder.base.load_sources()

    def test_catalog_has_exactly_two_independent_v2_presets(self):
        before = deepcopy(self.sources)
        result = catalog.build(self.sources, None, 'python3', Path('config/benchforge.local.json'),
                                Path('config/spatialforge.local.json'), package_imports=True)
        rows = result[0]['insert']
        presets = [row['config'] for row in rows if row['name'] == '@deepseek-ai/dsh-agent-preset']
        self.assertEqual([(row['id'], row['name']) for row in presets], [
            ('benchforgev2', 'BenchForgeV2'),
            ('spatialforge-standard-ptc', 'BenchForgeV2_UI')])
        self.assertEqual(self.sources, before)
        headless, workbench = presets
        for preset in presets:
            self.assertNotIn('spatialforge-evaluation-ui', [p['id'] for p in preset['plugins']])
            persona = next(plugin['config']['prefix'] for plugin in preset['plugins'] if plugin['id'] == 'persona')
            self.assertIn(preset['name'], persona)
            self.assertNotIn('SpatialForge', persona)
            self.assertNotIn('SpatialForge', preset['description'])
        for key in ('spatialforge-tools', 'spatial-learning-tools'):
            a = next(p for p in headless['plugins'] if p['id'] == key)
            b = next(p for p in workbench['plugins'] if p['id'] == key)
            self.assertEqual(a, b)
            self.assertIsNot(a, b)
        ui = [row for row in rows if row['id'] == 'benchforge-workbench-ui']
        self.assertEqual(len(ui), 1)
        self.assertEqual(ui[0]['name'], '@eurecamoment/benchforge-dsh/spatialforge-ui')
        self.assertEqual(ui[0]['config']['productionConfig'], 'config/spatialforge.local.json')

    def test_development_retains_existing_identity_and_learning_subset(self):
        import copy
        sources=deepcopy(self.sources)
        before=copy.deepcopy(sources)
        result=development.build(sources,None,'python-development',Path('service.local.json'),package_imports=True)
        self.assertEqual(sources,before)
        row=result[0]['insert'][0]
        self.assertEqual(row['id'],'preset-spatialforge-standard-ptc')
        self.assertEqual(row['config']['id'],'spatialforge-standard-ptc')
        self.assertEqual(row['config']['name'],'BenchForgeV2_UI')
        plugins=row['config']['plugins']
        learning=next(p for p in plugins if p['id']=='spatial-learning-tools')
        self.assertEqual(learning['config']['includeTools'],development.LEARNING_TOOLS)
        self.assertIn('pipeline_run',learning['config']['includeTools'])
        self.assertIn('model_objectclear_fill',learning['config']['includeTools'])
        self.assertEqual(learning['config']['python'],'python-development')
        self.assertNotIn('configPath',learning['config'])
        self.assertEqual(learning['name'],'@eurecamoment/benchforge-dsh/benchforge-tools')
        self.assertEqual(next(p for p in plugins if p['id']=='spatialforge-tools')['name'],
                         '@eurecamoment/benchforge-dsh/spatialforge-tools')
        self.assertNotIn('spatialforge-evaluation-ui', [p['id'] for p in plugins])
        self.assertEqual(result[0]['insert'][1]['name'], '@eurecamoment/benchforge-dsh/spatialforge-ui')

    def test_preserves_official_presets_and_persistent_configuration(self):
        import copy
        sources=deepcopy(self.sources)
        original=copy.deepcopy(sources)
        minimal=next(row for patch in sources['minimal'] for row in patch.get('insert',[])
                     if row['id']=='preset-minimal')
        shells=next(p for p in minimal['config']['plugins'] if p['id']=='persistent-shell')
        for row in shells['config']:
            if row['id'] in ('persistent-bash','persistent-pwsh'):
                row['config'].update(backendType='shell',maxOutputChars=8192)
        before=copy.deepcopy(sources)
        result=builder.build(sources,None,'python3',Path('config/benchforge.local.json'),
                             Path('config/generated/spatialforge.local.json'),package_imports=True)
        self.assertEqual(sources,before)
        row=result[0]['insert'][0]
        self.assertEqual(row['id'],'preset-benchforgev2')
        self.assertEqual(row['config']['id'],'benchforgev2')
        self.assertEqual(row['config']['name'],'BenchForgeV2')
        self.assertEqual(len(result[0]['insert']), 1)
        plugins=row['config']['plugins']
        self.assertEqual(next(p for p in plugins if p['id']=='tool-presentation')['config']['mode'],'both')
        wrappers=next(p for p in plugins if p['id']=='persistent-shell')['config']
        for wrapper in wrappers:
            if wrapper['id'] in ('persistent-bash','persistent-pwsh'):
                self.assertEqual(wrapper['config']['backendType'],'shell')
                self.assertEqual(wrapper['config']['maxOutputChars'],8192)
                self.assertNotIn('dshRoot',wrapper['config'])
                self.assertEqual(wrapper['name'],'@eurecamoment/benchforge-dsh/persistent-shell')
        self.assertEqual(original['standard'],sources['standard'])
        self.assertEqual(original['ptc'],sources['ptc'])
        self.assertEqual(original['cordis'],sources['cordis'])


if __name__=='__main__':
    unittest.main()
