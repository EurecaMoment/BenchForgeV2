"""Import task evidence and resolve its source references."""
from collections import Counter
from pathlib import Path

from storage.artifacts import read_json as read
from storage.artifacts import read_jsonl as rows
from storage.artifacts import select
from storage.artifacts import write_jsonl as jsonl


def import_evidence(args, directory):
    source = Path(args["input"]).resolve()
    accepted = []
    ids = set()
    for record in rows(source):
        if record["id"] in ids:
            raise ValueError(f"Duplicate evidence id: {record['id']}")
        ids.add(record["id"])
        origin = record["provenance"]
        if origin["kind"] not in ("official", "simulation", "program", "human", "prediction"):
            raise ValueError("Unknown provenance kind")
        reference = Path(origin["path"])
        reference = reference if reference.is_absolute() else source.parent / reference
        if not reference.is_file():
            raise ValueError(f"Missing source evidence: {reference}")
        record["provenance"] = {**origin, "path": str(reference.resolve())}
        if origin["kind"] != "prediction":
            # Recompute fields from the source, rather than trusting supplied answers.
            if reference.suffix.lower() != '.json':
                raise ValueError('provenance.path must reference a JSON source record. For raw depth/images, compute a reproducible JSON oracle in task code and list binary inputs under private assets.')
            raw = read(reference)
            facts = {}
            for name, pointer in record["selectors"].items():
                facts[name] = select(raw, pointer)
            record["facts"] = facts
        for media in record.get("media", []):
            p = Path(media)
            if not (p if p.is_absolute() else source.parent / p).is_file():
                raise ValueError(f"Missing media: {p}")
        record["media"] = [str((source.parent / p).resolve()) for p in record.get("media", [])]
        record['assets'] = [str((source.parent / p).resolve()) for p in record.get('assets', [])]
        for asset in record['assets']:
            if not Path(asset).is_file():
                raise ValueError(f'Missing private evidence asset: {asset}')
        accepted.append(record)
    jsonl(directory / "evidence.jsonl", accepted)
    counts = Counter(r["provenance"]["kind"] for r in accepted)
    return {"evidence": str(directory / "evidence.jsonl"), "count": len(accepted), "provenance_counts": dict(counts)}
