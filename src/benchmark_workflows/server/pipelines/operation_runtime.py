"""Small artifact runtime. The host agent owns planning and task code."""
from __future__ import annotations

import json
import os
import shutil
import urllib.request
from collections import Counter
from pathlib import Path

from benchmark_workflows.server.storage.artifacts import read_json as read
from benchmark_workflows.server.storage.artifacts import read_jsonl as rows
from benchmark_workflows.server.storage.artifacts import select
from benchmark_workflows.server.storage.artifacts import write_json as write
from benchmark_workflows.server.storage.artifacts import write_jsonl as jsonl
from benchmark_workflows.server.source_acquisition.run_collector import collect
from service_access import configuration as provider_config


from service_access.workspace_jobs import WorkspaceJobs


class Runtime(WorkspaceJobs):
    def call(self, tool, args):
        if tool == "catalog":
            section = args.get('section', 'overview')
            if section == 'templates':
                from benchmark_workflows.server.assessment_planning.catalog import catalog
                result = catalog({'limit': 10, **args})
                return {'templates': result['items'], 'total': result['total'],
                        'next_offset': result['next_offset'], 'source': result['source']}
            if section != 'overview':
                raise ValueError('section must be overview or templates')
            return read(Path(__file__).resolve().parents[2] / "resources/capabilities.json")
        return super().call(tool, args)

    def execute(self, tool, args, directory):
        from benchmark_workflows.server.operations import OPERATIONS
        if tool in OPERATIONS:
            return OPERATIONS[tool](args, directory, self.config)
        if tool == "plan":
            write(directory / "brief.json", args)
            return {"brief": str(directory / "brief.json"), "next": "Choose sources, collect or import evidence, then build. No stage locks."}
        if tool == "model_infer":
            return self.annotation(args)
        if tool in ("habitat", "libero", "carla"):
            return collect(tool, args, directory, self.config, self.root)
        if tool == "evidence":
            return self.evidence(args, directory)
        if tool == "build":
            return self.build(args, directory)
        if tool == "evaluate":
            return self.evaluate(args, directory)
        raise ValueError(f"Unknown capability: {tool}")

    def annotation(self, args):
        config = provider_config.selected_model(self.config, 'annotation')
        if not config.get('url'):
            raise ValueError('Configure the annotation model under providers.DSpark4A100')
        base_url = provider_config.llm_base_url(config['url'])
        headers = {'Content-Type': 'application/json'}
        if token_env := config.get('token_env'):
            token = os.environ.get(token_env)
            if not token:
                raise ValueError(f'Annotation model token_env references unset {token_env}')
            headers['Authorization'] = f'Bearer {token}'
        if args.get('action') == 'models':
            request = urllib.request.Request(base_url + '/models', headers=headers)
        else:
            data = json.dumps({**args.get('payload', {}), 'model': config['model']}).encode('utf8')
            request = urllib.request.Request(base_url + '/chat/completions', data=data, headers=headers)
        from urllib.parse import urlsplit
        local = urlsplit(base_url).hostname in ('localhost', '127.0.0.1', '::1')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
        with opener.open(request, timeout=args.get('timeout_seconds', 300)) as response:
            return {'service_result': json.load(response), 'evidence_kind': 'model_prediction', 'gt_written': False}

    def evidence(self, args, directory):
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

    def build(self, args, directory):
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

    def evaluate(self, args, directory):
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
