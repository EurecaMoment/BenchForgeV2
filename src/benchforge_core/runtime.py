"""Small artifact runtime. The host agent owns planning and task code."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import urllib.request
import uuid
import signal
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def jsonl(path, values):
    Path(path).write_text("".join(json.dumps(v, ensure_ascii=False)+"\n" for v in values), encoding="utf-8")


def select(raw, pointer):
    if pointer and not pointer.startswith('/'):
        raise ValueError('Selectors use RFC 6901 JSON pointers')
    value = raw
    for part in pointer.split('/')[1:]:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


class Runtime:
    def __init__(self, workspace, config=None):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.db = sqlite3.connect(self.root / "runs.sqlite", timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, tool TEXT, state TEXT, artifact TEXT, error TEXT)")
        self.db.commit()

    def close(self):
        self.db.close()

    def call(self, tool, args):
        if tool == "catalog":
            if args.get('section') == 'migration':
                inventory = read(Path(__file__).with_name('knowledge') / 'skill-migration.json')
                query = args.get('query', '').casefold()
                matches = [row for row in inventory['skills'] if query in json.dumps(row, ensure_ascii=False).casefold()]
                offset, limit = max(0, args.get('offset', 0)), max(1, min(100, args.get('limit', 10)))
                return {**{k: v for k, v in inventory.items() if k != 'skills'},
                        'skills': matches[offset:offset+limit], 'total': len(matches),
                        'next_offset': offset+limit if offset+limit < len(matches) else None}
            if args.get('section') == 'templates':
                import runpy
                module=Path(__file__).with_name('vendor')/'benchclaw/compiler/write_one_click_runtime.py'
                templates=runpy.run_path(str(module))['DEFAULT_TEMPLATES']
                query = args.get('query', '').casefold()
                matches = [t for t in templates if not query or any(word in json.dumps(t, ensure_ascii=False).casefold() for word in query.split())]
                offset, limit = args.get('offset', 0), args.get('limit', 10)
                return {'templates': matches[offset:offset+limit], 'total': len(matches),
                        'next_offset': offset+limit if offset+limit < len(matches) else None,
                        'status': 'Bundled executable templates; supported evidence and visible-anchor requirements still apply. Original broader taxonomy is available through method.'}
            return read(Path(__file__).with_name("capabilities.json"))
        if tool == "status":
            result = self.db.execute("SELECT id,tool,state,artifact,error FROM operations ORDER BY rowid DESC LIMIT 30").fetchall()
            return {"operations": [dict(zip(("id","tool","state","artifact","error"), row)) for row in result]}
        operation = uuid.uuid4().hex[:16]
        directory = self.root / "operations" / operation
        directory.mkdir(parents=True)
        self.db.execute("INSERT INTO operations VALUES (?,?,?,?,?)", (operation, tool, "running", str(directory), None))
        self.db.commit()
        write(directory / "request.json", {"tool": tool, "arguments": args, "time": datetime.now(timezone.utc).isoformat()})
        try:
            value = self.execute(tool, args, directory)
            write(directory / "result.json", value)
            self.db.execute("UPDATE operations SET state='completed' WHERE id=?", (operation,))
            self.db.commit()
            return {"operation_id": operation, "artifact_dir": str(directory), **value}
        except Exception as exc:
            self.db.execute("UPDATE operations SET state='failed',error=? WHERE id=?", (str(exc), operation))
            self.db.commit()
            raise

    def execute(self, tool, args, directory):
        from .workbench import OPERATIONS, execute
        if tool in OPERATIONS or tool == 'method':
            return execute(tool,args,directory,self.config)
        if tool == "plan":
            write(directory / "brief.json", args)
            return {"brief": str(directory / "brief.json"), "next": "Choose sources, collect or import evidence, then build. No stage locks."}
        if tool in ("sam3", "yoloe", "depthanything3", "llm_local"):
            return self.annotation(tool, args, directory)
        if tool in ("habitat", "libero", "carla", "isaac"):
            return self.collect(tool, args, directory)
        if tool == "evidence":
            return self.evidence(args, directory)
        if tool == "build":
            return self.build(args, directory)
        if tool == "evaluate":
            return self.evaluate(args, directory)
        raise ValueError(f"Unknown capability: {tool}")

    def annotation(self, tool, args, directory):
        routes = {"sam3": {"infer": ("POST", "/image/infer"), "health": ("GET", "/health")},
                  "yoloe": {"infer": ("POST", "/text-infer"), "visual": ("POST", "/visual-infer"), "health": ("GET", "/health")},
                  "depthanything3": {"infer": ("POST", "/inference"), "health": ("GET", "/status"), "task": ("GET", "/task/")},
                  "llm_local": {"infer": ("POST", "/v1/chat/completions"), "models": ("GET", "/v1/models")}}
        cfg = self.config.get('services', {}).get(tool)
        if not cfg:
            raise ValueError(f'Configure services.{tool}.url in config.local.json and pass --config; core tools do not require this backend.')
        action = args.get("action", "infer")
        method, route = routes[tool][action]
        if action == "task":
            from urllib.parse import quote
            route += quote(args["task_id"], safe="")
        body = json.dumps(args.get("payload", {})).encode() if method == "POST" else None
        headers = {"Content-Type": "application/json"}
        if cfg.get("token_env"):
            headers["Authorization"] = "Bearer " + os.environ[cfg["token_env"]]
        request = urllib.request.Request(cfg["url"].rstrip("/") + route, data=body, headers=headers, method=method)
        from urllib.parse import urlsplit
        local = urlsplit(cfg['url']).hostname in ('localhost', '127.0.0.1', '::1')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
        with opener.open(request, timeout=args.get("timeout_seconds", 300)) as response:
            result = json.loads(response.read())
        return {"service_result": result, "evidence_kind": "model_prediction", "gt_written": False,
                "note": "Model masks, labels and inferred depth remain predictions; depth scale requires calibration."}

    def collect(self, tool, args, directory):
        cfg = self.config.get('collectors', {}).get(tool)
        if not cfg:
            raise ValueError(f'Configure collectors.{tool}.command with the installed simulator Python environment; see config.example.json.')
        output = directory / "capture"
        output.mkdir()
        if tool == "isaac":
            write(directory / "capture-request.json", {**args, "output_dir": str(output)})
            script = cfg.get("script") or str(Path(__file__).with_name("collectors") / "isaac.py")
            command = list(cfg["command"]) + [script, "--request", str(directory / "capture-request.json")]
        else:
            script = Path(__file__).with_name("collectors") / (tool + ".py")
            command = list(cfg["command"]) + [str(script), *args.get("argv", []), "--output-dir", str(output)]
        env = {**os.environ, **cfg.get("env", {})}
        with (directory / "stdout.log").open("w", encoding="utf-8") as stdout, (directory / "stderr.log").open("w", encoding="utf-8") as stderr:
            options={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NO_WINDOW}
            completed = subprocess.Popen(command,cwd=self.root,env=env,stdout=stdout,stderr=stderr,**options)
            try:
                completed.wait(timeout=args.get('timeout_seconds',3600))
            finally:
                # Only the collector's own process group, including any explicitly
                # launched test server; attached shared servers are outside it.
                if os.name!='nt':
                    try:os.killpg(completed.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                elif completed.poll() is None:completed.terminate()
        if completed.returncode:
            detail = (directory / 'stderr.log').read_text(encoding='utf-8')[-6000:]
            raise RuntimeError(f"{tool} exited {completed.returncode}: {detail}; full log: {directory / 'stderr.log'}")
        if tool != 'isaac' and any(flag in args.get('argv', []) for flag in ('--help', '-h')):
            return {'help': (directory / 'stdout.log').read_text(encoding='utf-8'),
                    'capture_started': False, 'collector': tool}
        files = [str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()]
        if not files:
            raise RuntimeError(f"{tool} returned without capture artifacts; stdout: {directory / 'stdout.log'}")
        return {"output_dir": str(output), "files": files, "execution_complete": True,
                "quality": "not_assessed", "next": "Inspect real images and raw state before compiling benchmark evidence."}

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
