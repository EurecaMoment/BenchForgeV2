"""Focused preset composition test; uses the official installed package exports."""
import importlib.util
from pathlib import Path
import unittest

INTEGRATIONS=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('combined_preset',INTEGRATIONS/'spatialforge/build_preset.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
spec=importlib.util.spec_from_file_location('development_preset',INTEGRATIONS/'spatialforge/build_development_preset.py')
development=importlib.util.module_from_spec(spec)
spec.loader.exec_module(development)


class PresetBuilderTest(unittest.TestCase):
    def test_development_retains_existing_identity_and_learning_subset(self):
        import copy
        sources=builder.base.load_sources()
        before=copy.deepcopy(sources)
        result=development.build(sources,None,'python-development',Path('service.local.json'),package_imports=True)
        self.assertEqual(sources,before)
        row=result[0]['insert'][0]
        self.assertEqual(row['id'],'preset-spatialforge-standard-ptc')
        self.assertEqual(row['config']['id'],'spatialforge-standard-ptc')
        self.assertEqual(row['config']['name'],'SpatialForge')
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
        self.assertEqual(next(p for p in plugins if p['id']=='spatialforge-evaluation-ui')['name'],
                         '@eurecamoment/benchforge-spatialforge-ui')

    def test_preserves_official_presets_and_persistent_configuration(self):
        import copy
        sources=builder.base.load_sources()
        original=copy.deepcopy(sources)
        minimal=next(row for patch in sources['minimal'] for row in patch.get('insert',[])
                     if row['id']=='preset-minimal')
        shells=next(p for p in minimal['config']['plugins'] if p['id']=='persistent-shell')
        for row in shells['config']:
            if row['id'] in ('persistent-bash','persistent-pwsh'):
                row['config'].update(backendType='shell',maxOutputChars=8192)
        before=copy.deepcopy(sources)
        result=builder.build(sources,None,'python3',Path('config.local.json'),
                             Path('spatialforge.local.json'),package_imports=True)
        self.assertEqual(sources,before)
        row=result[0]['insert'][0]
        self.assertEqual(row['id'],'preset-benchforgev2')
        self.assertEqual(row['config']['id'],'benchforgev2')
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
