"""Score predictions against the evidence dataset's saved answers."""
import json
from pathlib import Path

from storage.artifacts import read_jsonl as rows
from storage.artifacts import write_jsonl as jsonl


def evaluate(args, directory):
    gold = rows(Path(args["authority"]) / "gold.jsonl")
    predictions = rows(args["predictions"])
    mapped = {r["id"]: r["answer"] for r in predictions}
    if len(mapped) != len(predictions):
        raise ValueError("Duplicate prediction id")
    expected = {r["id"] for r in gold}
    extra = set(mapped) - expected
    if extra:
        raise ValueError(f"Unknown prediction IDs: {sorted(extra)}")
    scores = [{"id": r["id"], "present": r["id"] in mapped,
               "correct": r["id"] in mapped and json.dumps(mapped[r["id"]],sort_keys=True) == json.dumps(r["answer"],sort_keys=True)} for r in gold]
    jsonl(directory / "scores.jsonl", scores)
    return {"metric": "exact_match", "total": len(gold), "missing": len(expected - set(mapped)),
            "accuracy": sum(r["correct"] for r in scores) / len(gold) if gold else 0,
            "model_api_called": False}
