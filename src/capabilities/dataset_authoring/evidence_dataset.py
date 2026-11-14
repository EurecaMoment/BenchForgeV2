"""Build public questions and their private answers from source evidence."""
import json
import shutil
from collections import Counter
from pathlib import Path

from storage.artifacts import read_json as read
from storage.artifacts import read_jsonl as rows
from storage.artifacts import select
from storage.artifacts import write_json as write
from storage.artifacts import write_jsonl as jsonl


def build(args, directory):
    records = rows(args["evidence"])
    evidence = {r["id"]: r for r in records}
    if len(evidence) != len(records):
        raise ValueError('Duplicate evidence IDs')
    items = rows(args["items"])
    if not items:
        raise ValueError("Cannot build an empty benchmark")
    public = directory / "public"
    private = directory / "authority"
    (public / "media").mkdir(parents=True)
    (private / "sources").mkdir(parents=True)
    (private / 'assets').mkdir()
    visible, gold, ids = [], [], set()
    for item in items:
        if item["id"] in ids:
            raise ValueError(f"Duplicate item id: {item['id']}")
        ids.add(item["id"])
        record = evidence[item["evidence_id"]]
        if record["provenance"]["kind"] == "prediction":
            raise ValueError("Prediction-only evidence cannot become benchmark GT")
        # Answers are selected from compiled source fields, never supplied by a reviewer.
        raw = read(record["provenance"]["path"])
        pointer = record["selectors"][item["answer_field"]]
        answer = select(raw, pointer)
        media_paths = []
        for index, media in enumerate(record.get("media", [])):
            if Path(media).suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.mp4','.webm','.wav','.mp3','.ogg'}:
                raise ValueError(f'Public media must be model-visible images/audio/video; put raw depth, labels and arrays in private assets: {media}')
            target = public / "media" / f"{len(visible)}_{index}{Path(media).suffix}"
            shutil.copyfile(media, target)
            media_paths.append(str(target.relative_to(public)).replace("\\", "/"))
        row = {"id": item["id"], "question": item["question"], "media": media_paths}
        if "choices" in item:
            row["choices"] = item["choices"]
        visible.append(row)
        source = Path(record["provenance"]["path"])
        target = private / "sources" / f"{len(gold)}{source.suffix}"
        shutil.copyfile(source, target)
        assets = []
        for index, asset in enumerate(record.get('assets', [])):
            asset_target = private / 'assets' / f'{len(gold)}_{index}{Path(asset).suffix}'
            shutil.copyfile(asset, asset_target)
            assets.append(str(asset_target.relative_to(private)).replace('\\', '/'))
        gold.append({"id": item["id"], "answer": answer, "evidence_id": record["id"],
                     "answer_field": item["answer_field"], "provenance": {**record["provenance"], "path": str(target.relative_to(private))},
                     'assets': assets,
                     "template": item.get("template", "unspecified"), "split": item.get("split", "dev")})
    jsonl(public / "items.jsonl", visible)
    jsonl(private / "gold.jsonl", gold)
    distribution = Counter(json.dumps(r["answer"], sort_keys=True) for r in gold)
    report = {"items": len(items), "source_count": len({r["evidence_id"] for r in gold}),
              "answer_distribution": dict(distribution), "majority_baseline": max(distribution.values()) / len(items),
              "templates": dict(Counter(r["template"] for r in gold)), "quality": "statistics_only",
              "limitations": "Provenance declarations and question semantics need task-specific replay; no model review is performed."}
    write(directory / "collection.json", report)
    shutil.make_archive(str(directory / "benchmark-public"), "zip", public)
    return {"package": str(directory / "benchmark-public.zip"), "public": str(public),
            "authority": str(private), "collection": report}
