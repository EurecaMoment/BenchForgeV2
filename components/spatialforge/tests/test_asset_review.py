import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

# Local unit tests do not require the remote Harness package. Production loads
# its atomic writer from the installed Harness environment.
if "benchclaw.store" not in sys.modules:
    store = types.ModuleType("benchclaw.store")
    store.write_json = lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8")
    benchclaw = types.ModuleType("benchclaw")
    benchclaw.store = store
    sys.modules["benchclaw"] = benchclaw
    sys.modules["benchclaw.store"] = store

from spatialforge.asset_review import review_generated_asset


class _Stop:
    def is_set(self):
        return False


class _Tools:
    def __init__(self, root):
        self.root = Path(root)
        self.calls = 0

    def generate_asset(self, spec, work, stop):
        self.calls += 1
        work = Path(work)
        work.mkdir(parents=True)
        image = work / "reference.png"
        Image.new("RGB", (8, 8), "white").save(image)
        return {"asset_id": "asset_new0000000001", "source_work": str(work), "files": {"reference.png": 1}}


class AssetReview(unittest.TestCase):
    def test_rejected_operator_or_unchanged_source_returns_feedback_without_reconstruction(self):
        for operator in (True,False):
            with self.subTest(operator=operator),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);image=root/'reference.png'
                Image.new('RGB',(8,8),'white').save(image)
                original={'asset_id':'asset_old0000000001','source_work':str(root),'files':{'reference.png':1}}
                spec={'label':'violin back','prompt':'A violin viewed from the back'}
                if not operator:spec['source_image']=str(image)
                answer={'acceptable':False,'identity_match':True,'state_match':False,'completeness':2,
                        'issues':['Fine tuner is not visible'],'repair_prompt':'Show fine tuner'}
                tools=_Tools(root)
                with patch('spatialforge.asset_review.completion',return_value=answer) as review:
                    selected=review_generated_asset(tools,spec,original,root/'selection',_Stop(),repair=not operator)
                self.assertEqual(selected['asset_id'],original['asset_id'])
                self.assertEqual(selected['quality']['semantic_review'],'needs_improvement')
                self.assertEqual(selected['quality']['repair_prompt'],answer['repair_prompt'])
                self.assertFalse(selected['quality']['3d_validated'])
                self.assertEqual(tools.calls,0)
                review.assert_called_once()
                payload=json.loads((root/'selection/selection.json').read_text())
                self.assertEqual(len(payload['candidates']),1)
                self.assertEqual(payload['candidates'][0]['review'],answer)

    def test_pass_writes_selection_without_replacing_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "reference.png"
            Image.new("RGB", (8, 8), "white").save(image)
            original = {"asset_id": "asset_old0000000001", "source_work": str(root), "files": {"reference.png": 1}}
            answers = [{"acceptable": True, "identity_match": True, "state_match": True, "completeness": 5, "issues": [], "repair_prompt": ""}]
            with patch("spatialforge.asset_review.completion", side_effect=answers):
                selected = review_generated_asset(_Tools(root), {"label": "closed shears", "prompt": "closed"}, original, root / "selection", _Stop())
            self.assertEqual(selected["asset_id"], original["asset_id"])
            self.assertEqual(selected["quality"]["semantic_review"], "passed")
            self.assertTrue((root / "selection" / "selection.json").is_file())

    def test_failed_candidate_gets_one_repair_and_both_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "reference.png"
            Image.new("RGB", (8, 8), "white").save(image)
            original = {"asset_id": "asset_old0000000001", "source_work": str(root), "files": {"reference.png": 1}}
            answers = [
                {"acceptable": False, "identity_match": True, "state_match": False, "completeness": 3, "issues": ["open instead of closed"], "repair_prompt": "closed blades"},
                {"acceptable": True, "identity_match": True, "state_match": True, "completeness": 4, "issues": [], "repair_prompt": ""},
            ]
            tools = _Tools(root)
            with patch("spatialforge.asset_review.completion", side_effect=answers):
                selected = review_generated_asset(tools, {"label": "closed shears", "prompt": "closed"}, original, root / "selection", _Stop())
            self.assertEqual(selected["asset_id"], "asset_new0000000001")
            payload = json.loads((root / "selection" / "selection.json").read_text())
            self.assertEqual(len(payload["candidates"]), 2)
            self.assertEqual(tools.calls, 1)


if __name__ == "__main__":
    unittest.main()
