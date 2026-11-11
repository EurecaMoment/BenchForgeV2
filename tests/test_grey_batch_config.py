import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from benchforge_core.vendor.benchclaw.compiler import grey_batch_eval as grey


class GreyBatchConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        legacy = self.root / 'upstream'
        (legacy / 'skills').mkdir(parents=True)
        (legacy / 'modelNeedMeasured').mkdir()
        self.config = {
            'provider': {
                'fixture': {
                    'options': {'baseURL': 'http://127.0.0.1:1/v1'},
                    'models': {'model': {'name': 'Fixture model'}},
                },
            },
            'grey_test': {'models': ['fixture/model']},
        }
        self.config_path = self.root / 'models.json'
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
        (legacy / 'modelNeedMeasured/model_config.json').write_text(
            json.dumps(self.config), encoding='utf-8'
        )
        self.gold = self.root / 'gold.jsonl'
        self.gold.write_text(json.dumps({
            'id': 'q1', 'eval_id': 'q1', 'question': 'Choose A.',
            'question_format': 'single_choice', 'answer': 'A',
        }) + '\n', encoding='utf-8')
        self.output = self.root / 'output'
        environment = mock.patch.dict(os.environ, {
            grey.MODEL_CONFIG_ENV: '',
            'BENCHCLAW_ROOT': str(legacy),
            'EPHONE_KEY_1': '', 'EPHONE_KEY_2': '', 'EPHONE_KEY_3': '',
        })
        environment.start()
        self.addCleanup(environment.stop)

    def arguments(self, *extra):
        return [
            'infer-ephone', '--gold', str(self.gold),
            '--out-dir', str(self.output), '--dry-run', *extra,
        ]

    def assert_dry_run_completed(self, *extra):
        # Exercise the entry point without network access or packaged credentials.
        with redirect_stdout(io.StringIO()), mock.patch.object(grey, 'requests', None):
            self.assertEqual(grey.main(self.arguments(*extra)), 0)
        manifest = json.loads((self.output / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['selected_items'], 1)
        self.assertEqual(manifest['selected_tiers'], ['grey_test'])
        result = json.loads(
            (self.output / 'model_overall_scores.json').read_text(encoding='utf-8')
        )
        self.assertEqual(result['rows'][0]['model'], 'fixture/model')

    def test_missing_config_rejects_even_with_legacy_root(self):
        for value in (None, '', '   '):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop(grey.MODEL_CONFIG_ENV, None)
                else:
                    os.environ[grey.MODEL_CONFIG_ENV] = value
                with self.assertRaisesRegex(SystemExit, '--config or BENCHFORGE_MODEL_CONFIG'):
                    grey.main(self.arguments())
        self.assertFalse(self.output.exists())

    def test_cli_config_takes_precedence_over_environment(self):
        os.environ[grey.MODEL_CONFIG_ENV] = str(self.root / 'missing.json')
        self.assert_dry_run_completed('--config', str(self.config_path))

    def test_environment_config_is_accepted(self):
        os.environ[grey.MODEL_CONFIG_ENV] = str(self.config_path)
        self.assert_dry_run_completed()

    def test_config_must_be_an_existing_file(self):
        for path in (self.root / 'missing.json', self.root):
            for source in ('cli', 'environment'):
                with self.subTest(path=path, source=source):
                    os.environ[grey.MODEL_CONFIG_ENV] = str(path)
                    extra = ('--config', str(path)) if source == 'cli' else ()
                    with self.assertRaisesRegex(FileNotFoundError, 'Config file does not exist'):
                        grey.main(self.arguments(*extra))
        self.assertFalse(self.output.exists())

    def test_config_schema_is_still_validated(self):
        self.config_path.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, 'opencode-style config'):
            grey.main(self.arguments('--config', str(self.config_path)))
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
