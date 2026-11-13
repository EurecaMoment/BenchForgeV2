import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('repair_scene_library',Path(__file__).parents[1]/'maintenance/repair_scene_library.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RepairBaselineTest(unittest.TestCase):
    def test_captured_program_and_frozen_history_override_stale_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';capture=root/'capture';folder=root/'repairs'
            for p in (source,capture,folder/'attempt_1'):p.mkdir(parents=True)
            for p in (source/'program.json',capture/'program.json',folder/'attempt_1/program.json'):p.write_text('{}')
            frozen={'hard_requirements':['keep the original interaction'],'revision_history':[{'revision':3}]}
            (capture/'scene_brief.json').write_text(json.dumps(frozen))
            path,context,brief=module.repair_baseline({'source_directory':str(source)},folder,2,{'directory':str(capture)})
            self.assertEqual(path,capture/'program.json');self.assertEqual(context,capture);self.assertEqual(brief,frozen)


if __name__=='__main__':unittest.main()
