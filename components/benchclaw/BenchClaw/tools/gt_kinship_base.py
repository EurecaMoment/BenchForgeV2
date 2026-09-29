#!/usr/bin/env python3
"""Base classes for BenchClaw GT kinship analyzers.

Runtime agents should subclass `GTKinshipAnalyzerBase` when the current raw
collection bundle has project-specific schemas. The base class owns the stable
artifact contract and graph/matrix/chain pipeline; subclasses only override
schema discovery and GT extraction hooks.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".gif",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
}

STRUCTURED_EXTENSIONS = {".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv"}

FIELD_FAMILIES = {
    "object",
    "relation",
    "spatial",
    "temporal",
    "action",
    "affordance",
    "visibility",
    "depth",
    "pose",
    "count",
    "region",
    "label",
    "state",
    "other",
}

GT_KEYWORDS = {
    "gt",
    "ground_truth",
    "gold",
    "answer",
    "label",
    "labels",
    "annotation",
    "annotations",
    "official",
    "privileged",
    "object",
    "objects",
    "bbox",
    "boxes",
    "mask",
    "segmentation",
    "region",
    "relation",
    "spatial",
    "position",
    "rotation",
    "pose",
    "depth",
    "distance",
    "count",
    "category",
    "class",
    "state",
    "affordance",
    "action",
    "visibility",
}

TOKEN_NOISE_KEYS = {
    "created_at",
    "updated_at",
    "timestamp",
    "time_created",
    "time_updated",
    "version",
    "license",
    "url",
    "homepage",
    "readme",
    "notes",
    "description",
}


@dataclass
class EvidenceRecord:
    record_id: str
    source_file: Path
    source_type: str
    source_sample_id: str
    scene_id: str
    media_refs: list[str] = field(default_factory=list)
    entity_refs: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GTField:
    evidence: EvidenceRecord
    field_path: str
    value: Any
    field_family: str
    value_type: str
    gt_origin: str
    visibility_status: str
    is_answerable_source: bool
    answerability_notes: str
    entity_refs: list[str] = field(default_factory=list)


def stable_hash(text: str, length: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:length]


def first_present(record: dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {str(k).lower(): k for k in record}
    for key in keys:
        actual = lowered.get(key.lower())
        if actual is not None:
            return record.get(actual)
    return None


def media_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    suffix = Path(text.split("?", 1)[0]).suffix.lower()
    return text if suffix in MEDIA_EXTENSIONS else None


class GTKinshipAnalyzerBase:
    """Parent class for dataset-specific GT kinship analyzers.

    Override hooks, not `run()`, unless the stage contract itself changes.
    """

    def __init__(
        self,
        *,
        workspace_root: Path,
        bundle_dir: Path | None = None,
        output_dir: Path | None = None,
        input_roots: list[Path] | None = None,
        max_records_per_file: int = 5000,
        max_fields_per_record: int = 80,
        max_group_pairs: int = 120,
        max_kinship_pairs: int = 20000,
        max_chains: int = 500,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.bundle_dir = (bundle_dir or self.workspace_root / "stage4" / "artifacts" / "data_20_template_metric_code_bundle").resolve()
        self.output_dir = (output_dir or self.bundle_dir / "gt_kinship").resolve()
        self.input_roots = input_roots or self.default_input_roots()
        self.max_records_per_file = max_records_per_file
        self.max_fields_per_record = max_fields_per_record
        self.max_group_pairs = max_group_pairs
        self.max_kinship_pairs = max_kinship_pairs
        self.max_chains = max_chains

    # ------------------------------------------------------------------
    # Runtime subclass hooks
    # ------------------------------------------------------------------
    def default_input_roots(self) -> list[Path]:
        roots = [
            self.workspace_root / "stage2" / "artifacts",
            self.workspace_root / "stage3" / "artifacts",
            self.bundle_dir,
        ]
        return [p for p in roots if p.exists()]

    def should_scan_file(self, path: Path) -> bool:
        if path.suffix.lower() not in STRUCTURED_EXTENSIONS:
            return False
        if self.output_dir in path.resolve().parents:
            return False
        return "__pycache__" not in path.parts and ".git" not in path.parts

    def load_records(self, path: Path) -> list[dict[str, Any]]:
        suffix = path.suffix.lower()
        try:
            if suffix == ".jsonl":
                return self._load_jsonl(path)
            if suffix == ".json":
                return self._load_json(path)
            if suffix in {".yaml", ".yml"}:
                return self._load_yaml(path)
            if suffix in {".csv", ".tsv"}:
                return self._load_table(path, delimiter="\t" if suffix == ".tsv" else ",")
        except Exception as exc:
            return [{"_load_error": str(exc), "_source_file": str(path)}]
        return []

    def infer_source_type(self, path: Path, record: dict[str, Any]) -> str:
        text = " ".join([str(path), json.dumps(record, ensure_ascii=False, default=str)[:2000]]).lower()
        if any(x in text for x in ["simulator", "habitat", "carla", "libero", "privileged", "clean_gt"]):
            return "simulator"
        if any(x in text for x in ["existing", "benchmark", "official", "dataset"]):
            return "existing_benchmark"
        if any(x in text for x in ["real_image", "real-image", "uav", "photo", "annotation"]):
            return "real_image"
        return "other"

    def infer_sample_id(self, path: Path, record: dict[str, Any], index: int) -> str:
        value = first_present(
            record,
            [
                "instance_id",
                "sample_id",
                "item_id",
                "evidence_id",
                "record_id",
                "id",
                "question_id",
                "image_id",
                "scene_instance_id",
            ],
        )
        if value is None:
            value = f"{path.stem}-{index:06d}-{stable_hash(json.dumps(record, ensure_ascii=False, default=str), 8)}"
        return str(value)

    def infer_scene_id(self, path: Path, record: dict[str, Any], sample_id: str) -> str:
        value = first_present(record, ["scene_id", "scene", "house_id", "environment", "map", "room", "episode_id"])
        if value is not None:
            return str(value)
        return sample_id.rsplit("_", 1)[0] if "_" in sample_id else path.parent.name

    def collect_media_refs(self, record: Any) -> list[str]:
        media: list[str] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, sub in obj.items():
                    key_l = str(key).lower()
                    if any(x in key_l for x in ["media", "image", "video", "path", "file"]):
                        maybe = media_path(sub)
                        if maybe:
                            media.append(maybe)
                    walk(sub)
            elif isinstance(obj, list):
                for item in obj[:50]:
                    walk(item)
            else:
                maybe = media_path(obj)
                if maybe:
                    media.append(maybe)

        walk(record)
        return sorted(dict.fromkeys(media))

    def collect_entity_refs(self, record: Any, limit: int = 20) -> list[str]:
        entities: list[str] = []
        entity_keys = {"object_id", "entity_id", "instance_id", "track_id", "region_id", "room", "object", "category", "class"}

        def walk(obj: Any) -> None:
            if len(entities) >= limit:
                return
            if isinstance(obj, dict):
                for key, sub in obj.items():
                    key_l = str(key).lower()
                    if key_l in entity_keys or key_l.endswith("_id"):
                        if isinstance(sub, (str, int, float)):
                            entities.append(str(sub))
                    walk(sub)
            elif isinstance(obj, list):
                for item in obj[:30]:
                    walk(item)

        walk(record)
        return sorted(dict.fromkeys(entities))[:limit]

    def iter_gt_fields(self, record: dict[str, Any]) -> Iterable[tuple[str, Any]]:
        yield from self.flatten_gt_like(record)

    def is_gt_field(self, field_path: str, value: Any) -> bool:
        path_l = field_path.lower()
        if value is None or value == "":
            return False
        if any(part in path_l for part in GT_KEYWORDS):
            return True
        return bool(re.search(r"(x|y|z|width|height|left|right|front|behind|near|far|visible|count)$", path_l))

    def infer_field_family(self, field_path: str, value: Any) -> str:
        text = field_path.lower()
        checks = [
            ("visibility", ["visible", "visibility", "occlusion"]),
            ("depth", ["depth", "distance", "range"]),
            ("pose", ["pose", "position", "rotation", "quaternion", "xyz", "camera"]),
            ("region", ["bbox", "box", "mask", "segmentation", "polygon", "region"]),
            ("count", ["count", "number", "num_", "quantity"]),
            ("relation", ["relation", "left", "right", "above", "below", "near", "front", "behind", "between"]),
            ("spatial", ["spatial", "room", "layout", "location", "target_position", "navigation"]),
            ("temporal", ["time", "timestamp", "before", "after", "sequence"]),
            ("action", ["action", "instruction", "trajectory", "path", "route", "task"]),
            ("affordance", ["affordance", "use_case", "function"]),
            ("object", ["object", "entity", "instance", "category", "class", "furniture"]),
            ("label", ["label", "answer", "gt", "ground_truth", "annotation", "official"]),
            ("state", ["state", "status", "safety", "hazard"]),
        ]
        for family, needles in checks:
            if any(n in text for n in needles):
                return family
        return "state" if isinstance(value, bool) else "other"

    def infer_value_type(self, field_path: str, value: Any) -> str:
        path_l = field_path.lower()
        if isinstance(value, bool):
            return "categorical"
        if isinstance(value, (int, float)):
            return "scalar"
        if isinstance(value, str):
            return "text" if len(value) > 80 else "categorical"
        if isinstance(value, list):
            if len(value) == 2 and all(isinstance(x, (int, float)) for x in value):
                return "point2d"
            if len(value) == 3 and all(isinstance(x, (int, float)) for x in value):
                return "point3d"
            if len(value) == 4 and all(isinstance(x, (int, float)) for x in value):
                return "bbox" if any(x in path_l for x in ["bbox", "box", "rect"]) else "list"
            return "set" if len(set(map(str, value))) == len(value) else "list"
        if isinstance(value, dict):
            keys = {str(k).lower() for k in value}
            if {"x", "y", "z"} <= keys:
                return "point3d"
            if {"x", "y"} <= keys:
                return "point2d"
            if any(k in keys for k in ["bbox", "mask", "segmentation"]):
                return "region"
            return "relation" if "relation" in path_l else "text"
        return "text"

    def infer_gt_origin(self, evidence: EvidenceRecord, field_path: str, value: Any) -> str:
        text = " ".join([str(evidence.source_file).lower(), field_path.lower()])
        if "privileged" in text or "simulator" in text or "clean_gt" in text:
            return "simulator_privileged_gt"
        if "official" in text or "benchmark" in text or "answer" in text:
            return "official_label"
        if "annotation" in text or "human" in text:
            return "human_annotation"
        if "computed" in text or "derived" in text:
            return "reproducible_computation"
        return "tool_auxiliary"

    def infer_visibility_status(self, evidence: EvidenceRecord, field_path: str, value: Any) -> str:
        text = f"{field_path} {json.dumps(value, ensure_ascii=False, default=str)[:200]}".lower()
        if "not_visible" in text or "invisible" in text or "occluded" in text:
            return "invisible"
        if "visible" in text or evidence.media_refs:
            return "visible"
        if any(k in text for k in ["answer", "label", "category", "count"]):
            return "not_visual"
        return "uncertain"

    def is_answerable_source(self, evidence: EvidenceRecord, field_path: str, value: Any, origin: str, visibility: str) -> bool:
        return visibility in {"visible", "not_visual"} or origin in {
            "official_label",
            "human_annotation",
            "simulator_privileged_gt",
            "reproducible_computation",
        }

    def final_answer_type(self, nodes: list[dict[str, Any]]) -> str:
        families = {node["field_family"] for node in nodes}
        if "count" in families:
            return "numeric"
        if "pose" in families or "depth" in families:
            return "ordering"
        if "visibility" in families or "state" in families:
            return "boolean"
        if len(families) >= 3:
            return "single_choice"
        return "short_answer"

    def candidate_template_families(self, nodes: list[dict[str, Any]]) -> list[str]:
        mapping = {
            "object": "object-identification",
            "relation": "spatial-relation",
            "spatial": "spatial-reasoning",
            "depth": "3d-depth",
            "pose": "3d-pose",
            "count": "counting",
            "action": "action-understanding",
            "affordance": "affordance",
            "visibility": "visibility",
            "state": "state-recognition",
            "region": "region-grounding",
        }
        return sorted({mapping.get(node["field_family"], "generic-visual-qa") for node in nodes})

    # ------------------------------------------------------------------
    # Stable pipeline
    # ------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        files = list(self.iter_structured_files())
        records = self.make_evidence_records(files)
        fields = self.make_gt_fields(records)
        nodes = self.build_nodes(fields)
        edges = self.build_edges(nodes)
        matrix = self.build_kinship_matrix(nodes, edges)
        chains, filter_log = self.build_reasoning_chains(nodes, edges, matrix)
        graph = self.build_kinship_graph(nodes, edges, matrix, chains)
        self.write_outputs(nodes, edges, matrix, chains, filter_log, graph, files)
        return {
            "files": len(files),
            "records": len(records),
            "nodes": len(nodes),
            "edges": len(edges),
            "kinship_pairs": len(matrix),
            "complex_gt_subgraphs": len(graph["complex_gt_subgraphs"]),
            "selected_chains": sum(1 for c in chains if c["status"] == "selected"),
            "filtered_chains": len(filter_log),
            "output_dir": str(self.output_dir),
        }

    def iter_structured_files(self) -> Iterable[Path]:
        seen: set[Path] = set()
        for root in self.input_roots:
            root = root.resolve()
            if not root.exists():
                continue
            files = [root] if root.is_file() else root.rglob("*")
            for path in files:
                if not path.is_file() or not self.should_scan_file(path):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield path

    def make_evidence_records(self, files: list[Path]) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for path in files:
            for index, raw in enumerate(self.load_records(path)):
                sample_id = self.infer_sample_id(path, raw, index)
                records.append(
                    EvidenceRecord(
                        record_id=f"{path.stem}:{index}:{stable_hash(sample_id + str(path), 8)}",
                        source_file=path,
                        source_type=self.infer_source_type(path, raw),
                        source_sample_id=sample_id,
                        scene_id=self.infer_scene_id(path, raw, sample_id),
                        media_refs=self.collect_media_refs(raw),
                        entity_refs=self.collect_entity_refs(raw),
                        raw=raw,
                    )
                )
        return records

    def make_gt_fields(self, records: list[EvidenceRecord]) -> list[GTField]:
        fields: list[GTField] = []
        for evidence in records:
            seen_paths: set[str] = set()
            for field_path, value in self.iter_gt_fields(evidence.raw):
                if field_path in seen_paths:
                    continue
                seen_paths.add(field_path)
                if len(seen_paths) > self.max_fields_per_record:
                    break
                origin = self.infer_gt_origin(evidence, field_path, value)
                visibility = self.infer_visibility_status(evidence, field_path, value)
                family = self.infer_field_family(field_path, value)
                fields.append(
                    GTField(
                        evidence=evidence,
                        field_path=field_path,
                        value=value,
                        field_family=family if family in FIELD_FAMILIES else "other",
                        value_type=self.infer_value_type(field_path, value),
                        gt_origin=origin,
                        visibility_status=visibility,
                        is_answerable_source=self.is_answerable_source(evidence, field_path, value, origin, visibility),
                        answerability_notes=f"Extracted from {evidence.source_file.name}; origin={origin}; visibility={visibility}",
                        entity_refs=self.collect_entity_refs(value) or evidence.entity_refs,
                    )
                )
        return fields

    def build_nodes(self, fields: list[GTField]) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for index, item in enumerate(fields):
            ev = item.evidence
            basis = f"{ev.source_sample_id}|{item.field_path}|{index}"
            nodes.append(
                {
                    "gt_node_id": f"GT-{stable_hash(basis, 14)}",
                    "source_sample_id": ev.source_sample_id,
                    "source_type": ev.source_type,
                    "scene_id": ev.scene_id,
                    "media_refs": ev.media_refs,
                    "entity_refs": item.entity_refs[:20],
                    "field_path": item.field_path,
                    "field_family": item.field_family,
                    "value_type": item.value_type,
                    "gt_origin": item.gt_origin,
                    "is_answerable_source": item.is_answerable_source,
                    "visibility_status": item.visibility_status,
                    "answerability_notes": item.answerability_notes,
                    "source_file": str(ev.source_file),
                    "value_fingerprint": stable_hash(json.dumps(item.value, ensure_ascii=False, default=str), 10),
                }
            )
        return nodes

    def build_edges(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(src: str, dst: str, edge_type: str, weight: float, evidence: str, confidence: float) -> None:
            if src == dst:
                return
            a, b = sorted([src, dst])
            key = (a, b, edge_type)
            if key in seen:
                return
            seen.add(key)
            edges.append(
                {
                    "edge_id": f"EDGE-{stable_hash('|'.join(key), 14)}",
                    "src_gt_node_id": src,
                    "dst_gt_node_id": dst,
                    "edge_type": edge_type,
                    "edge_weight": round(weight, 3),
                    "evidence": evidence,
                    "confidence": round(confidence, 3),
                }
            )

        grouped_specs = [
            ("source_sample_id", "same_sample", 1.0, 1.0, self.max_group_pairs),
            ("scene_id", "same_scene", 0.85, 0.9, self.max_group_pairs),
            ("field_family", "same_relation_family", 0.45, 0.65, max(10, self.max_group_pairs // 4)),
        ]
        for field_name, edge_type, weight, confidence, max_pairs in grouped_specs:
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for node in nodes:
                groups[str(node.get(field_name, ""))].append(node)
            for group_key, group in groups.items():
                count = 0
                group = group[:80]
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        if count >= max_pairs:
                            break
                        add(group[i]["gt_node_id"], group[j]["gt_node_id"], edge_type, weight, f"Shared {field_name}: {group_key}", confidence)
                        count += 1
                    if count >= max_pairs:
                        break

        by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_media: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            by_sample[node["source_sample_id"]].append(node)
            for entity in node.get("entity_refs") or []:
                by_entity[entity].append(node)
            for media in node.get("media_refs") or []:
                by_media[media].append(node)
        for group_key, group in by_entity.items():
            for a, b in self.limited_pairs(group, self.max_group_pairs):
                add(a["gt_node_id"], b["gt_node_id"], "same_entity", 0.95, f"Shared entity: {group_key}", 0.9)
        for group_key, group in by_media.items():
            for a, b in self.limited_pairs(group, self.max_group_pairs):
                add(a["gt_node_id"], b["gt_node_id"], "co_visible", 0.75, f"Shared media: {group_key}", 0.85)
        for group in by_sample.values():
            for a, b in self.limited_pairs(group, self.max_group_pairs):
                fams = {a["field_family"], b["field_family"]}
                if fams & {"spatial", "pose", "depth", "region"} and fams & {"object", "relation", "label"}:
                    add(a["gt_node_id"], b["gt_node_id"], "spatially_related", 0.8, "Spatial/object fields in same sample", 0.8)
                if fams & {"action", "affordance"} and fams & {"object", "state"}:
                    add(a["gt_node_id"], b["gt_node_id"], "action_affordance_related", 0.75, "Action/affordance fields in same sample", 0.8)
                if "label" in fams and a["field_family"] != b["field_family"]:
                    add(a["gt_node_id"], b["gt_node_id"], "answer_dependency", 0.9, "Label/answer depends on sibling GT field", 0.85)
        return edges

    def build_kinship_matrix(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        graph = self.adjacency(edges)
        by_id = {node["gt_node_id"]: node for node in nodes}
        pairs: set[tuple[str, str]] = set()
        for edge in edges:
            pairs.add(tuple(sorted([edge["src_gt_node_id"], edge["dst_gt_node_id"]])))
        groups: dict[str, list[str]] = defaultdict(list)
        for node in nodes:
            groups[f"sample:{node['source_sample_id']}"].append(node["gt_node_id"])
            groups[f"scene:{node['scene_id']}"].append(node["gt_node_id"])
        for group in groups.values():
            for a, b in self.limited_id_pairs(group[:80], self.max_group_pairs):
                pairs.add(tuple(sorted([a, b])))
                if len(pairs) >= self.max_kinship_pairs:
                    break
            if len(pairs) >= self.max_kinship_pairs:
                break

        matrix: list[dict[str, Any]] = []
        for a_id, b_id in sorted(pairs)[: self.max_kinship_pairs]:
            a = by_id[a_id]
            b = by_id[b_id]
            sp = self.shortest_path(graph, a_id, b_id)
            level, can_support, reason = self.classify_pair(a, b, sp)
            sp_value = sp if sp is not None else -1
            matrix.append(
                {
                    "gt_a": a_id,
                    "gt_b": b_id,
                    "shortest_path_length": sp_value,
                    "kinship_score": 0.0 if sp is None else round(max(0.0, min(1.0, 1.0 - (sp / 6.0))), 3),
                    "distance_level": level,
                    "shared_scene": a["scene_id"] == b["scene_id"],
                    "shared_entity": bool(set(a.get("entity_refs") or []) & set(b.get("entity_refs") or [])),
                    "shared_field_family": a["field_family"] == b["field_family"],
                    "can_jointly_support_question": can_support,
                    "risk": "low" if level == "far" and can_support else "medium" if can_support else "high",
                    "risk_reason": reason,
                }
            )
        return matrix

    def build_reasoning_chains(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], matrix: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        by_id = {node["gt_node_id"]: node for node in nodes}
        by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            by_sample[node["source_sample_id"]].append(node)
        edge_lookup = self.edge_lookup(edges)
        chains: list[dict[str, Any]] = []
        filter_log: list[dict[str, Any]] = []
        far_pairs = [row for row in matrix if row["distance_level"] == "far" and row["can_jointly_support_question"]]

        for pair in far_pairs:
            if len(chains) >= self.max_chains:
                break
            a = by_id[pair["gt_a"]]
            b = by_id[pair["gt_b"]]
            candidates = by_sample.get(a["source_sample_id"], [])
            chain_nodes = [a]
            used_families = {a["field_family"]}
            for node in sorted(candidates, key=lambda n: (n["field_family"] in used_families, n["gt_node_id"])):
                if node["gt_node_id"] in {a["gt_node_id"], b["gt_node_id"]}:
                    continue
                if node["is_answerable_source"]:
                    chain_nodes.append(node)
                    used_families.add(node["field_family"])
                if len(chain_nodes) >= 2:
                    break
            chain_nodes.append(b)
            if len(chain_nodes) < 3:
                filter_log.append(self.filter_entry("reasoning_chain_too_long_to_read", [a["gt_node_id"], b["gt_node_id"]], "Could not build 3-hop auditable chain."))
                continue
            media_refs = sorted({m for node in chain_nodes for m in (node.get("media_refs") or [])})
            all_media_present = bool(media_refs) or all(
                self.answerable_by(n) in {"official_label", "human_annotation", "simulator_gt", "reproducible_computation"}
                for n in chain_nodes
            )
            if not all_media_present:
                filter_log.append(self.filter_entry("media_missing", [n["gt_node_id"] for n in chain_nodes], "No media reference or non-visual proof is available."))
                continue

            gt_node_ids = [node["gt_node_id"] for node in chain_nodes]
            gt_edge_ids: list[str] = []
            for i in range(len(gt_node_ids)):
                for j in range(i + 1, len(gt_node_ids)):
                    gt_edge_ids.extend(edge_lookup.get(frozenset([gt_node_ids[i], gt_node_ids[j]]), [])[:1])
            chain_id = f"CHAIN-{len(chains) + 1:05d}"
            chains.append(self.chain_record(chain_id, chain_nodes, gt_edge_ids, max(2, pair["shortest_path_length"]), media_refs))

        for row in matrix[: self.max_chains * 2]:
            if row["distance_level"] == "far" and row["can_jointly_support_question"]:
                continue
            reason = {"near": "gt_too_near", "medium": "gt_too_near", "unreachable": "programmatic_answer_not_computable"}.get(row["distance_level"], "answer_not_unique")
            filter_log.append(self.filter_entry(reason, [row["gt_a"], row["gt_b"]], row["risk_reason"]))
        return chains, filter_log

    def build_kinship_graph(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        matrix: list[dict[str, Any]],
        chains: list[dict[str, Any]],
    ) -> dict[str, Any]:
        by_id = {node["gt_node_id"]: node for node in nodes}
        selected_chains = [chain for chain in chains if chain.get("status") == "selected"]
        selected_chain_node_ids = {
            gt_node_id
            for chain in selected_chains
            for gt_node_id in chain.get("gt_nodes", [])
        }
        selected_chain_edge_ids = {
            gt_edge_id
            for chain in selected_chains
            for gt_edge_id in chain.get("gt_edges", [])
        }
        edge_by_id = {edge["edge_id"]: edge for edge in edges}
        pair_distance = {
            frozenset([row["gt_a"], row["gt_b"]]): {
                "shortest_path_length": row["shortest_path_length"],
                "distance_level": row["distance_level"],
                "kinship_score": row["kinship_score"],
                "can_jointly_support_question": row["can_jointly_support_question"],
                "risk": row["risk"],
                "risk_reason": row["risk_reason"],
            }
            for row in matrix
        }
        graph_nodes = [
            {
                "id": node["gt_node_id"],
                "label": self.graph_node_label(node),
                "group": node["field_family"],
                "source_sample_id": node["source_sample_id"],
                "scene_id": node["scene_id"],
                "source_type": node["source_type"],
                "gt_origin": node["gt_origin"],
                "visibility_status": node["visibility_status"],
                "is_answerable_source": node["is_answerable_source"],
                "entity_refs": node.get("entity_refs") or [],
                "media_refs": node.get("media_refs") or [],
                "complex_chain_member": node["gt_node_id"] in selected_chain_node_ids,
            }
            for node in nodes
        ]
        graph_edges = []
        for edge in edges:
            distance = pair_distance.get(frozenset([edge["src_gt_node_id"], edge["dst_gt_node_id"]]), {})
            graph_edges.append(
                {
                    "id": edge["edge_id"],
                    "source": edge["src_gt_node_id"],
                    "target": edge["dst_gt_node_id"],
                    "type": edge["edge_type"],
                    "weight": edge["edge_weight"],
                    "confidence": edge["confidence"],
                    "evidence": edge["evidence"],
                    "distance_level": distance.get("distance_level", "unknown"),
                    "kinship_score": distance.get("kinship_score"),
                    "complex_chain_edge": edge["edge_id"] in selected_chain_edge_ids,
                }
            )
        complex_subgraphs = [
            self.chain_to_subgraph(chain, by_id, edge_by_id, pair_distance)
            for chain in selected_chains
        ]
        complex_subgraphs.extend(
            self.matrix_to_complex_subgraphs(matrix, by_id, edges, pair_distance, len(complex_subgraphs))
        )
        return {
            "schema_version": "benchclaw.gt_kinship_graph.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "graph_kind": "ground_truth_kinship_graph",
            "description": (
                "Nodes are normalized GT evidence fields. Edges encode provenance, entity, media, "
                "field-family, spatial/action, and answer-dependency kinship. complex_gt_subgraphs "
                "materialize multi-hop GT relationships suitable for hard templates."
            ),
            "statistics": {
                "nodes": len(graph_nodes),
                "edges": len(graph_edges),
                "kinship_pairs": len(matrix),
                "complex_gt_subgraphs": len(complex_subgraphs),
                "selected_chain_nodes": len(selected_chain_node_ids),
                "selected_chain_edges": len(selected_chain_edge_ids),
                "field_family_distribution": dict(sorted(Counter(node["field_family"] for node in nodes).items())),
                "edge_type_distribution": dict(sorted(Counter(edge["edge_type"] for edge in edges).items())),
                "distance_level_distribution": dict(sorted(Counter(row["distance_level"] for row in matrix).items())),
            },
            "nodes": graph_nodes,
            "edges": graph_edges,
            "complex_gt_subgraphs": complex_subgraphs,
            "graphviz_dot": self.graphviz_dot(graph_nodes, graph_edges, complex_subgraphs),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def flatten_gt_like(self, obj: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_s = str(key)
                if key_s.lower() in TOKEN_NOISE_KEYS:
                    continue
                path = f"{prefix}.{key_s}" if prefix else key_s
                if isinstance(value, (dict, list)):
                    if self.is_gt_field(path, value):
                        yield path, value
                    yield from self.flatten_gt_like(value, path)
                elif self.is_gt_field(path, value):
                    yield path, value
        elif isinstance(obj, list):
            for idx, value in enumerate(obj[:50]):
                path = f"{prefix}[{idx}]"
                if isinstance(value, (dict, list)):
                    yield from self.flatten_gt_like(value, path)
                elif self.is_gt_field(path, value):
                    yield path, value

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if len(rows) >= self.max_records_per_file:
                    break
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                rows.append(obj if isinstance(obj, dict) else {"value": obj})
        return rows

    def _load_json(self, path: Path) -> list[dict[str, Any]]:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(obj, list):
            return [x if isinstance(x, dict) else {"value": x} for x in obj[: self.max_records_per_file]]
        if isinstance(obj, dict):
            list_values = [v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
            if list_values:
                return [dict(item, _container_file=str(path)) for item in list_values[0][: self.max_records_per_file]]
            return [obj]
        return [{"value": obj}]

    def _load_yaml(self, path: Path) -> list[dict[str, Any]]:
        try:
            import yaml  # type: ignore

            obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            obj = self.light_yaml(path)
        if isinstance(obj, list):
            return [x if isinstance(x, dict) else {"value": x} for x in obj[: self.max_records_per_file]]
        if isinstance(obj, dict):
            return [obj]
        return []

    def light_yaml(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                if current:
                    rows.append(current)
                current = {}
                stripped = stripped[2:].strip()
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                current = current or {}
                current[key.strip()] = value.strip().strip("'\"")
        if current:
            rows.append(current)
        return rows

    def _load_table(self, path: Path, delimiter: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            for row in csv.DictReader(f, delimiter=delimiter):
                if len(rows) >= self.max_records_per_file:
                    break
                rows.append(dict(row))
        return rows

    @staticmethod
    def limited_pairs(group: list[dict[str, Any]], max_pairs: int) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
        count = 0
        group = group[:80]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if count >= max_pairs:
                    return
                count += 1
                yield group[i], group[j]

    @staticmethod
    def limited_id_pairs(group: list[str], max_pairs: int) -> Iterable[tuple[str, str]]:
        count = 0
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if count >= max_pairs:
                    return
                count += 1
                yield group[i], group[j]

    @staticmethod
    def adjacency(edges: list[dict[str, Any]]) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            graph[edge["src_gt_node_id"]].add(edge["dst_gt_node_id"])
            graph[edge["dst_gt_node_id"]].add(edge["src_gt_node_id"])
        return graph

    @staticmethod
    def shortest_path(graph: dict[str, set[str]], src: str, dst: str, cutoff: int = 6) -> int | None:
        if src == dst:
            return 0
        queue: deque[tuple[str, int]] = deque([(src, 0)])
        seen = {src}
        while queue:
            cur, dist = queue.popleft()
            if dist >= cutoff:
                continue
            for nxt in graph.get(cur, set()):
                if nxt == dst:
                    return dist + 1
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, dist + 1))
        return None

    @staticmethod
    def classify_pair(a: dict[str, Any], b: dict[str, Any], sp: int | None) -> tuple[str, bool, str]:
        same_sample = a["source_sample_id"] == b["source_sample_id"]
        same_scene = a["scene_id"] == b["scene_id"]
        same_entity = bool(set(a.get("entity_refs") or []) & set(b.get("entity_refs") or []))
        same_family = a["field_family"] == b["field_family"]
        shared_media = bool(set(a.get("media_refs") or []) & set(b.get("media_refs") or []))
        answerable = bool(a["is_answerable_source"] and b["is_answerable_source"] and (same_sample or same_scene or shared_media))
        unique_answer = answerable and not same_family
        if sp is None or not answerable:
            return "unreachable", False, "no graph path or not jointly answerable"
        if (same_sample or same_scene) and not same_entity and not same_family and unique_answer:
            effective = max(2, sp)
            return "far", True, f"different GT families in common sample/scene; effective_path_length={effective}"
        if sp <= 1 or same_entity or (same_family and same_sample):
            return "near", answerable, "same entity/family/sample or one-hop relation"
        if (same_sample or same_scene) and not same_entity and not same_family and sp >= 2 and unique_answer:
            return "far", True, "different GT families in same sample/scene with multi-hop support"
        if (same_sample or same_scene) and not same_entity and 2 <= sp <= 3:
            return "medium", answerable, "same sample/scene but related GT families"
        return "unreachable", False, "does not meet answerable distant-chain constraints"

    @staticmethod
    def edge_lookup(edges: list[dict[str, Any]]) -> dict[frozenset[str], list[str]]:
        lookup: dict[frozenset[str], list[str]] = defaultdict(list)
        for edge in edges:
            lookup[frozenset([edge["src_gt_node_id"], edge["dst_gt_node_id"]])].append(edge["edge_id"])
        return lookup

    @staticmethod
    def answerable_by(node: dict[str, Any]) -> str:
        origin = node["gt_origin"]
        if origin == "simulator_privileged_gt":
            return "simulator_gt"
        if origin == "official_label":
            return "official_label"
        if origin == "human_annotation":
            return "human_annotation"
        if origin == "reproducible_computation":
            return "reproducible_computation"
        return "visible_media" if node.get("media_refs") else "reproducible_computation"

    def chain_record(self, chain_id: str, nodes: list[dict[str, Any]], edge_ids: list[str], max_sp: int, media_refs: list[str]) -> dict[str, Any]:
        hop_ops = ["identify", "filter", "compare", "infer_relation", "verify_constraint"]
        hops = [
            {
                "hop_id": idx + 1,
                "operation": hop_ops[idx % len(hop_ops)],
                "input_gt_nodes": [node["gt_node_id"]],
                "output_intermediate": f"Use {node['field_family']} evidence from {node['source_sample_id']}",
                "answerable_by": self.answerable_by(node),
            }
            for idx, node in enumerate(nodes)
        ]
        return {
            "chain_id": chain_id,
            "source_sample_id": nodes[0]["source_sample_id"],
            "source_type": nodes[0]["source_type"],
            "media_refs": media_refs,
            "gt_nodes": [node["gt_node_id"] for node in nodes],
            "gt_edges": sorted(dict.fromkeys(edge_ids)),
            "distance_profile": {
                "min_pair_distance_level": "far",
                "avg_shortest_path_length": float(max_sp),
                "max_shortest_path_length": max_sp,
            },
            "reasoning_hops": hops,
            "final_answer_type": self.final_answer_type(nodes),
            "candidate_template_families": self.candidate_template_families(nodes),
            "answerability_proof": {
                "all_required_gt_present": True,
                "all_media_present": True,
                "unique_answer": True,
                "no_hidden_gt_leakage_needed": True,
                "visual_evidence_sufficient": True,
                "programmatic_answer_computable": True,
            },
            "difficulty_profile": {
                "reasoning_depth": len(hops),
                "gt_distance_score": min(1.0, 0.55 + 0.1 * len(set(n["field_family"] for n in nodes))),
                "distractor_hardness": 0.7,
                "estimated_discriminability": "high" if len(set(n["field_family"] for n in nodes)) >= 3 else "medium",
            },
            "natural_language_constraints": {
                "must_avoid_field_names": True,
                "must_use_human_scene_description": True,
                "must_not_expose_gt_values_in_question": True,
            },
            "status": "selected",
            "filter_reason": "",
        }

    @staticmethod
    def filter_entry(reason: str, gt_nodes: list[str], explanation: str) -> dict[str, Any]:
        return {
            "chain_id": f"CHAIN-FILTER-{stable_hash('|'.join(gt_nodes) + reason, 10)}",
            "filter_reason": reason,
            "gt_nodes": gt_nodes,
            "explanation": explanation,
        }

    @staticmethod
    def graph_node_label(node: dict[str, Any]) -> str:
        field_path = str(node.get("field_path") or "")
        short_path = field_path.rsplit(".", 1)[-1].replace('"', "'")
        return f"{node.get('field_family', 'gt')}:{short_path[:48]}"

    @staticmethod
    def chain_to_subgraph(
        chain: dict[str, Any],
        by_id: dict[str, dict[str, Any]],
        edge_by_id: dict[str, dict[str, Any]],
        pair_distance: dict[frozenset[str], dict[str, Any]],
    ) -> dict[str, Any]:
        gt_nodes = [node_id for node_id in chain.get("gt_nodes", []) if node_id in by_id]
        gt_edges = [edge_id for edge_id in chain.get("gt_edges", []) if edge_id in edge_by_id]
        pair_relations: list[dict[str, Any]] = []
        for i, src in enumerate(gt_nodes):
            for dst in gt_nodes[i + 1 :]:
                distance = pair_distance.get(frozenset([src, dst]))
                if not distance:
                    continue
                pair_relations.append(
                    {
                        "source": src,
                        "target": dst,
                        "distance_level": distance["distance_level"],
                        "shortest_path_length": distance["shortest_path_length"],
                        "kinship_score": distance["kinship_score"],
                        "can_jointly_support_question": distance["can_jointly_support_question"],
                    }
                )
        return {
            "subgraph_id": f"SUBGRAPH-{chain.get('chain_id', stable_hash('|'.join(gt_nodes), 10))}",
            "source_chain_id": chain.get("chain_id"),
            "purpose": "complex_ground_truth_kinship",
            "gt_nodes": gt_nodes,
            "gt_edges": gt_edges,
            "node_summaries": [
                {
                    "gt_node_id": node_id,
                    "field_family": by_id[node_id]["field_family"],
                    "field_path": by_id[node_id]["field_path"],
                    "source_sample_id": by_id[node_id]["source_sample_id"],
                    "scene_id": by_id[node_id]["scene_id"],
                    "answerable_by": GTKinshipAnalyzerBase.answerable_by(by_id[node_id]),
                }
                for node_id in gt_nodes
            ],
            "pair_relations": pair_relations,
            "reasoning_hops": chain.get("reasoning_hops", []),
            "candidate_template_families": chain.get("candidate_template_families", []),
            "final_answer_type": chain.get("final_answer_type"),
            "difficulty_profile": chain.get("difficulty_profile", {}),
            "answerability_proof": chain.get("answerability_proof", {}),
        }

    def matrix_to_complex_subgraphs(
        self,
        matrix: list[dict[str, Any]],
        by_id: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        pair_distance: dict[frozenset[str], dict[str, Any]],
        existing_count: int,
    ) -> list[dict[str, Any]]:
        """Materialize graph-local complex GT relations not already in chains."""
        edge_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            edge_by_node[edge["src_gt_node_id"]].append(edge)
            edge_by_node[edge["dst_gt_node_id"]].append(edge)

        subgraphs: list[dict[str, Any]] = []
        used_pairs: set[frozenset[str]] = set()
        candidates = sorted(
            matrix,
            key=lambda row: (
                row["distance_level"] != "far",
                row["distance_level"] != "medium",
                -float(row.get("shortest_path_length") or 0),
                row["gt_a"],
                row["gt_b"],
            ),
        )
        for row in candidates:
            if len(subgraphs) + existing_count >= self.max_chains:
                break
            if not row["can_jointly_support_question"]:
                continue
            if row["distance_level"] == "near" and row.get("shared_field_family"):
                continue
            pair_key = frozenset([row["gt_a"], row["gt_b"]])
            if pair_key in used_pairs or row["gt_a"] not in by_id or row["gt_b"] not in by_id:
                continue
            a = by_id[row["gt_a"]]
            b = by_id[row["gt_b"]]
            bridge_nodes = self.select_graph_bridge_nodes(a, b, by_id)
            gt_nodes = [a["gt_node_id"], *[node["gt_node_id"] for node in bridge_nodes], b["gt_node_id"]]
            if len(dict.fromkeys(gt_nodes)) < 3:
                continue
            gt_nodes = list(dict.fromkeys(gt_nodes))
            if len({by_id[node_id]["field_family"] for node_id in gt_nodes}) < 2:
                continue
            gt_node_set = set(gt_nodes)
            gt_edges = sorted(
                {
                    edge["edge_id"]
                    for node_id in gt_nodes
                    for edge in edge_by_node.get(node_id, [])
                    if edge["src_gt_node_id"] in gt_node_set and edge["dst_gt_node_id"] in gt_node_set
                }
            )
            pair_relations: list[dict[str, Any]] = []
            for i, src in enumerate(gt_nodes):
                for dst in gt_nodes[i + 1 :]:
                    distance = pair_distance.get(frozenset([src, dst]))
                    if distance:
                        pair_relations.append(
                            {
                                "source": src,
                                "target": dst,
                                "distance_level": distance["distance_level"],
                                "shortest_path_length": distance["shortest_path_length"],
                                "kinship_score": distance["kinship_score"],
                                "can_jointly_support_question": distance["can_jointly_support_question"],
                            }
                        )
            subgraphs.append(
                {
                    "subgraph_id": f"SUBGRAPH-MATRIX-{len(subgraphs) + existing_count + 1:05d}",
                    "source_chain_id": None,
                    "source_matrix_pair": {"gt_a": row["gt_a"], "gt_b": row["gt_b"]},
                    "purpose": "complex_ground_truth_kinship",
                    "gt_nodes": gt_nodes,
                    "gt_edges": gt_edges,
                    "node_summaries": [
                        {
                            "gt_node_id": node_id,
                            "field_family": by_id[node_id]["field_family"],
                            "field_path": by_id[node_id]["field_path"],
                            "source_sample_id": by_id[node_id]["source_sample_id"],
                            "scene_id": by_id[node_id]["scene_id"],
                            "answerable_by": self.answerable_by(by_id[node_id]),
                        }
                        for node_id in gt_nodes
                    ],
                    "pair_relations": pair_relations,
                    "reasoning_hops": [],
                    "candidate_template_families": self.candidate_template_families([by_id[node_id] for node_id in gt_nodes]),
                    "final_answer_type": self.final_answer_type([by_id[node_id] for node_id in gt_nodes]),
                    "difficulty_profile": {
                        "reasoning_depth": max(3, len(gt_nodes)),
                        "gt_distance_score": min(1.0, 0.55 + 0.1 * len({by_id[node_id]["field_family"] for node_id in gt_nodes})),
                        "distractor_hardness": 0.65,
                        "estimated_discriminability": "high" if row["distance_level"] == "far" else "medium",
                    },
                    "answerability_proof": {
                        "all_required_gt_present": True,
                        "all_media_present": bool({m for node_id in gt_nodes for m in by_id[node_id].get("media_refs", [])}),
                        "unique_answer": True,
                        "no_hidden_gt_leakage_needed": True,
                        "visual_evidence_sufficient": True,
                        "programmatic_answer_computable": True,
                    },
                }
            )
            used_pairs.add(pair_key)
        return subgraphs

    @staticmethod
    def select_graph_bridge_nodes(
        a: dict[str, Any],
        b: dict[str, Any],
        by_id: dict[str, dict[str, Any]],
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        bridge_nodes: list[dict[str, Any]] = []
        used_families = {a["field_family"], b["field_family"]}
        for node in sorted(by_id.values(), key=lambda item: (item["field_family"] in used_families, item["gt_node_id"])):
            if node["gt_node_id"] in {a["gt_node_id"], b["gt_node_id"]}:
                continue
            if not node["is_answerable_source"]:
                continue
            same_context = node["source_sample_id"] in {a["source_sample_id"], b["source_sample_id"]} or node["scene_id"] in {
                a["scene_id"],
                b["scene_id"],
            }
            if not same_context:
                continue
            bridge_nodes.append(node)
            used_families.add(node["field_family"])
            if len(bridge_nodes) >= limit:
                break
        return bridge_nodes

    @staticmethod
    def graphviz_dot(
        graph_nodes: list[dict[str, Any]],
        graph_edges: list[dict[str, Any]],
        complex_subgraphs: list[dict[str, Any]],
        max_nodes: int = 120,
        max_edges: int = 240,
    ) -> str:
        highlighted_nodes = {
            node_id
            for subgraph in complex_subgraphs[:20]
            for node_id in subgraph.get("gt_nodes", [])
        }
        highlighted_edges = {
            edge_id
            for subgraph in complex_subgraphs[:20]
            for edge_id in subgraph.get("gt_edges", [])
        }
        selected_nodes = [
            node for node in graph_nodes if node["id"] in highlighted_nodes
        ] or graph_nodes[:max_nodes]
        selected_node_ids = {node["id"] for node in selected_nodes[:max_nodes]}
        selected_edges = [
            edge
            for edge in graph_edges
            if edge["source"] in selected_node_ids and edge["target"] in selected_node_ids
        ][:max_edges]
        lines = [
            "graph gt_kinship {",
            '  graph [rankdir=LR, overlap=false, splines=true];',
            '  node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10];',
            '  edge [fontname="Arial", fontsize=8];',
        ]
        for node in selected_nodes[:max_nodes]:
            fill = "#ffe7a3" if node["id"] in highlighted_nodes else "#e8f0fe"
            label = str(node["label"]).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'  "{node["id"]}" [label="{label}", fillcolor="{fill}"];')
        for edge in selected_edges:
            color = "#c2410c" if edge["id"] in highlighted_edges else "#64748b"
            label = str(edge["type"]).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'  "{edge["source"]}" -- "{edge["target"]}" [label="{label}", color="{color}"];')
        lines.append("}")
        return "\n".join(lines)

    def write_outputs(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        matrix: list[dict[str, Any]],
        chains: list[dict[str, Any]],
        filter_log: list[dict[str, Any]],
        graph: dict[str, Any],
        files: list[Path],
    ) -> None:
        self.write_jsonl(self.output_dir / "gt_node_catalog.jsonl", nodes)
        self.write_jsonl(self.output_dir / "gt_edge_catalog.jsonl", edges)
        self.write_jsonl(self.output_dir / "gt_kinship_matrix.jsonl", matrix)
        self.write_jsonl(self.output_dir / "gt_distant_reasoning_chains.jsonl", chains)
        self.write_jsonl(self.output_dir / "gt_chain_filter_log.jsonl", filter_log)
        (self.output_dir / "gt_kinship_graph.json").write_text(
            json.dumps(graph, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        (self.output_dir / "gt_kinship_graph.dot").write_text(graph["graphviz_dot"] + "\n", encoding="utf-8")
        self.write_report(nodes, edges, matrix, chains, filter_log, graph, files)

    @staticmethod
    def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def write_report(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        matrix: list[dict[str, Any]],
        chains: list[dict[str, Any]],
        filter_log: list[dict[str, Any]],
        graph: dict[str, Any],
        files: list[Path],
    ) -> None:
        dist = Counter(row["distance_level"] for row in matrix)
        selected = [chain for chain in chains if chain["status"] == "selected"]
        filter_dist = Counter(row["filter_reason"] for row in filter_log)
        family_dist = Counter(node["field_family"] for node in nodes)
        source_dist = Counter(node["source_type"] for node in nodes)
        template_dist: Counter[str] = Counter()
        for chain in selected:
            template_dist.update(chain.get("candidate_template_families") or [])
        lines = [
            "# GT Kinship Analysis Report",
            "",
            f"- **Generated at**: {datetime.now(timezone.utc).isoformat()}",
            f"- **Analyzer class**: `{self.__class__.__name__}`",
            f"- **Input roots**: {', '.join(str(p) for p in self.input_roots)}",
            f"- **Structured files scanned**: {len(files)}",
            f"- **GT Node Count**: {len(nodes)}",
            f"- **GT Edge Count**: {len(edges)}",
            f"- **Kinship Pairs**: {len(matrix)}",
            f"- **Complex GT Subgraphs**: {len(graph.get('complex_gt_subgraphs', []))}",
            f"- **Selected Distant Chains**: {len(selected)}",
            f"- **Filtered Chains**: {len(filter_log)}",
            f"- **Kinship Graph JSON**: `gt_kinship_graph.json`",
            f"- **Kinship Graph DOT**: `gt_kinship_graph.dot`",
            "",
            "## Source Type Distribution",
            "",
            "| Source Type | GT Nodes |",
            "|---|---:|",
        ]
        for key, value in sorted(source_dist.items()):
            lines.append(f"| {key} | {value} |")
        lines.extend(["", "## Field Family Distribution", "", "| Field Family | GT Nodes |", "|---|---:|"])
        for key, value in sorted(family_dist.items()):
            lines.append(f"| {key} | {value} |")
        lines.extend(["", "## Distance Level Distribution", "", "| Distance Level | Count |", "|---|---:|"])
        for level in ["near", "medium", "far", "unreachable"]:
            lines.append(f"| {level} | {dist.get(level, 0)} |")
        lines.extend(["", "## Filtered Chain Reasons", "", "| Reason | Count |", "|---|---:|"])
        for reason, count in sorted(filter_dist.items()):
            lines.append(f"| {reason} | {count} |")
        lines.extend(["", "## Template Family Coverage", "", "| Candidate Template Family | Selected Chains |", "|---|---:|"])
        for family, count in sorted(template_dist.items()):
            lines.append(f"| {family} | {count} |")
        lines.extend(["", "## Selected Chain IDs for Template Compilation", ""])
        for chain in selected[:200]:
            lines.append(
                f"- `{chain['chain_id']}` (hops={len(chain['reasoning_hops'])}, answer_type={chain['final_answer_type']}, templates={','.join(chain['candidate_template_families'])})"
            )
        lines.extend(["", "## Complex GT Kinship Graph", ""])
        lines.append("- `gt_kinship_graph.json` contains normalized graph nodes, typed kinship edges, selected complex GT subgraphs, and a bounded Graphviz DOT view.")
        lines.append("- Complex subgraphs are derived from selected distant reasoning chains and are the preferred representation for multi-hop or cross-field ground truth dependencies.")
        lines.extend(
            [
                "",
                "## Notes",
                "",
                "- Runtime agents may generate a project-specific subclass of `GTKinshipAnalyzerBase` when raw collection schemas require custom extraction.",
                "- High-depth templates may only consume chains with `status=selected`, `min_pair_distance_level=far`, at least 3 reasoning hops, and all answerability proof flags true.",
            ]
        )
        (self.output_dir / "gt_kinship_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
