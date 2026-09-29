#!/usr/bin/env python3
"""Deterministic pair curator for the Habitat spatial benchmark.

Input : native evidence rows produced by benchforge_adapt_capture (one row per
        Habitat frame, each carrying geometrically sampled visible surface
        regions with native bbox and calibrated Euclidean camera range).
Output: one evidence row per curated region PAIR, holding exactly the two
        regions in answer order (objects[0] -> visual marker A,
        objects[1] -> visual marker B).

No value is invented here. Bboxes, depth medians, camera intrinsics, raw depth
paths and provenance pointers are copied verbatim from the native evidence, so
the library oracle and the native depth replay still decide every answer.

The only decisions are selection and presentation:
  * a pair is eligible only when it clears the margin_from_decision_boundary
    thresholds on all three relations (|dx|, |dy| in pixels, |drange| in metres);
  * per scene the strongest eligible pairs are kept (fixed budget), preferring
    disjoint region sets before reusing a region inside the same frame;
  * A/B orientation is assigned deterministically to reduce answer imbalance, so no
    option position becomes a shortcut.

CLI matches the compiler adapter hook:  --input <evidence.jsonl> --out <adapted.jsonl>
Optional: --write-requests <image_requests.jsonl> to emit the neutral base-image
recipes consumed by benchforge_images / benchforge_compile.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, List

import numpy as np
from PIL import Image

# margin_from_decision_boundary thresholds (declared in the emitted records)
MIN_DX_PX = 40.0          # left/right separation of marker centroids
MIN_DY_PX = 40.0          # up/down separation of marker centroids
MIN_DRANGE_M = 0.60       # near/far separation of camera-range medians
PAIRS_PER_SCENE = 4       # scene diversity cap
MAX_PAIRS_PER_FRAME = 2   # only used when a scene has few eligible frames
TOTAL_RECORDS = 8         # 8 records x 3 templates = 24 items
MIN_FRAME_BRIGHT = 0.60   # share of pixels above the black-render threshold
MIN_MARKER_LUMA = 16.0    # a marker must sit on visible geometry, not void


def rows(path: Path) -> List[Dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


_GRAIN: Dict[str, Any] = {}


def luma_array(image_path: str):
    key = str(image_path)
    if key not in _GRAIN:
        if Image is None:
            _GRAIN[key] = None
        else:
            with Image.open(key) as handle:
                _GRAIN[key] = np.asarray(handle.convert("L"), dtype=np.float32)
    return _GRAIN[key]


def frame_information_ok(record: Dict[str, Any]) -> bool:
    """Reject frames whose render is mostly black void (Habitat occlusion gaps)."""
    array = luma_array(record["media"][0])
    if array is None:
        return True
    return float((array > 16.0).mean()) >= MIN_FRAME_BRIGHT


def marker_on_visible_geometry(record: Dict[str, Any], obj: Dict[str, Any]) -> bool:
    array = luma_array(record["media"][0])
    if array is None:
        return True
    x1, y1, x2, y2 = obj["bbox_xyxy"]
    patch = array[y1:y2, x1:x2]
    return patch.size > 0 and float(patch.mean()) >= MIN_MARKER_LUMA


def centroid(obj: Dict[str, Any]) -> tuple:
    x1, y1, x2, y2 = obj["bbox_xyxy"]
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def depth(obj: Dict[str, Any]) -> float:
    return float(obj["depth_median"])


def score_pair(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, float]:
    ax, ay = centroid(a)
    bx, by = centroid(b)
    return {
        "dx": abs(ax - bx),
        "dy": abs(ay - by),
        "drange": abs(depth(a) - depth(b)),
    }


def eligible(margins: Dict[str, float]) -> bool:
    return (
        margins["dx"] >= MIN_DX_PX
        and margins["dy"] >= MIN_DY_PX
        and margins["drange"] >= MIN_DRANGE_M
    )


def pair_strength(margins: Dict[str, float]) -> float:
    """Normalised worst-case margin; higher is a safer decision boundary."""
    return min(
        margins["dx"] / MIN_DX_PX,
        margins["dy"] / MIN_DY_PX,
        margins["drange"] / MIN_DRANGE_M,
    )


def eligible_pairs(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not frame_information_ok(record):
        return []
    objects = [
        o for o in record.get("objects", [])
        if o.get("depth_median") is not None and marker_on_visible_geometry(record, o)
    ]
    pairs = []
    for i in range(len(objects)):
        for j in range(i + 1, len(objects)):
            margins = score_pair(objects[i], objects[j])
            if not eligible(margins):
                continue
            pairs.append({
                "frame": record,
                "a": objects[i],
                "b": objects[j],
                "margins": margins,
                "strength": pair_strength(margins),
                "regions": frozenset(
                    [str(objects[i].get("object_id")), str(objects[j].get("object_id"))]
                ),
            })
    pairs.sort(key=lambda p: (-p["strength"], str(p["a"].get("object_id")), str(p["b"].get("object_id"))))
    return pairs


def collect_candidates(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Up to MAX_PAIRS_PER_FRAME eligible pairs per frame, disjoint sets first."""
    candidates: List[Dict[str, Any]] = []
    for record in evidence:
        pairs = eligible_pairs(record)
        picked: List[Dict[str, Any]] = []
        used: FrozenSet[str] = frozenset()
        for pair in pairs:
            if len(picked) >= MAX_PAIRS_PER_FRAME:
                break
            if pair["regions"] & used:
                continue
            picked.append(pair)
            used |= pair["regions"]
        for pair in pairs:                       # fill remaining budget, strongest first
            if len(picked) >= MAX_PAIRS_PER_FRAME:
                break
            if any(pair is chosen for chosen in picked):
                continue
            picked.append(pair)
        for index, pair in enumerate(picked):
            pair["pair_slot"] = index
        candidates.extend(picked)
    return candidates


def order_candidate(candidate: Dict[str, Any]) -> tuple:
    """Deterministic global order: scene, frame id, pair slot, region ids."""
    frame = candidate["frame"]
    return (
        str(frame.get("scene", "")),
        str(frame.get("sample_id") or frame.get("id", "")),
        int(candidate.get("pair_slot", 0)),
        str(candidate["a"].get("object_id", "")),
        str(candidate["b"].get("object_id", "")),
    )


def orient(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, str]:
    """Answers when A is the first object: left-of, above, closer."""
    ax, ay = centroid(a)
    bx, by = centroid(b)
    return {
        "lr": "A" if ax < bx else "B",
        "ud": "A" if ay < by else "B",
        "nf": "A" if depth(a) < depth(b) else "B",
    }


def assign_orientations(pool: List[Dict[str, Any]]) -> List[bool]:
    """Deterministic A/B orientation for the whole set.

    Exhaustive over the 2**N orientations (N is small by design) and chosen to
    keep the answer key balanced per relation, so no option position is a
    shortcut. Answers themselves always come from the library rule applied to
    the native measurements; this only decides which region is called A.
    """
    n = len(pool)
    forward = [orient(c["a"], c["b"]) for c in pool]
    reverse = [orient(c["b"], c["a"]) for c in pool]
    best = None
    for mask in range(1 << n):
        picks = [reverse[i] if (mask >> i) & 1 else forward[i] for i in range(n)]
        counts = {name: sum(1 for p in picks if p[name] == "A") for name in ("lr", "ud", "nf")}
        imbalance = sum(abs(2 * counts[name] - n) for name in counts)
        triples = len({tuple(p[name] for name in ("lr", "ud", "nf")) for p in picks})
        key = (imbalance, -triples, tuple(sorted(((mask >> i) & 1) for i in range(n))))
        if best is None or key < best[0]:
            best = (key, [bool((mask >> i) & 1) for i in range(n)])
    return best[1]


def scene_ranked(candidates: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Per-scene queue: each frame's strongest pair first, scene cap applied."""
    by_scene: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        scene = str(candidate["frame"].get("scene") or "scene")
        by_scene.setdefault(scene, []).append(candidate)
    ranked: Dict[str, List[Dict[str, Any]]] = {}
    for scene in sorted(by_scene):
        # pair_slot 0 = the strongest pair of a frame; taking all slot 0 entries
        # before any slot 1 entry maximises distinct views per scene.
        queue = sorted(
            by_scene[scene],
            key=lambda c: (int(c.get("pair_slot", 0)), -c["strength"]) + order_candidate(c),
        )
        ranked[scene] = queue[:PAIRS_PER_SCENE]
    return ranked


def select(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = scene_ranked(collect_candidates(evidence))
    scenes = sorted(ranked)
    pool: List[Dict[str, Any]] = []
    cursor = {scene: 0 for scene in scenes}
    while len(pool) < TOTAL_RECORDS and any(cursor[s] < len(ranked[s]) for s in scenes):
        for scene in scenes:                     # round-robin keeps scenes balanced
            if len(pool) >= TOTAL_RECORDS:
                break
            if cursor[scene] < len(ranked[scene]):
                pool.append(ranked[scene][cursor[scene]])
                cursor[scene] += 1
    pool.sort(key=order_candidate)

    orientations = assign_orientations(pool)
    counts = {"lr": {"A": 0, "B": 0}, "ud": {"A": 0, "B": 0}, "nf": {"A": 0, "B": 0}}
    selected: List[Dict[str, Any]] = []
    for candidate, swap in zip(pool, orientations):
        first, second = candidate["a"], candidate["b"]
        obj_a, obj_b = (second, first) if swap else (first, second)
        answers = orient(obj_a, obj_b)
        for name in counts:
            counts[name][answers[name]] += 1

        frame = candidate["frame"]
        frame_id = str(frame.get("sample_id") or frame.get("id"))
        sample_id = f"{frame_id}_pair{candidate.get('pair_slot', 0) + 1}"
        selected.append({
            "id": sample_id,
            "sample_id": sample_id,
            "scene": frame.get("scene"),
            "source_name": frame.get("source_name") or frame.get("scene"),
            "frame_sample_id": frame_id,
            "provenance": {
                "kind": "simulation",
                "path": frame["provenance"]["path"],
                "note": "Native Habitat capture record; this row selects two surface regions from it.",
            },
            "source_type": "simulation",
            "image_path": frame["image_path"],
            "media": list(frame["media"]),
            "raw_depth_path": frame["raw_depth_path"],
            "camera": frame["camera"],
            "depth_semantics": frame.get("depth_semantics", "euclidean_range"),
            "sequence_semantics": "independent_capture",
            "objects": [obj_a, obj_b],
            "selection": {
                "adapter": Path(__file__).name,
                "thresholds": {
                    "min_dx_px": MIN_DX_PX,
                    "min_dy_px": MIN_DY_PX,
                    "min_drange_m": MIN_DRANGE_M,
                    "pairs_per_scene": PAIRS_PER_SCENE,
                    "max_pairs_per_frame": MAX_PAIRS_PER_FRAME,
                },
                "margins": candidate["margins"],
                "strength": candidate["strength"],
                "declared_answers": answers,
                "balance_counts": {k: dict(v) for k, v in counts.items()},
            },
        })
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--write-requests", default="")
    args = parser.parse_args()

    evidence_path=Path(args.input).resolve()
    evidence = rows(evidence_path)
    for record in evidence:
        for key in ('image_path','raw_depth_path'):
            if record.get(key) and not Path(record[key]).is_absolute():record[key]=str(evidence_path.parent/record[key])
        record['media']=[str(Path(p) if Path(p).is_absolute() else evidence_path.parent/p) for p in record.get('media',[])]
    selected = select(evidence)
    if not selected:
        raise SystemExit(
            f"no eligible surface pair found in {len(evidence)} evidence rows; "
            "check that media paths resolve from the current directory and that "
            "the declared margins are reachable"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected), encoding="utf-8")

    if args.write_requests:
        requests_path = Path(args.write_requests)
        requests_path.parent.mkdir(parents=True, exist_ok=True)
        requests_path.write_text(
            "".join(
                json.dumps({
                    "request_id": f"base_{r['sample_id']}",
                    "sample_id": r["sample_id"],
                    "composer": "safe_copy",
                    "source_images": [r["media"][0]],
                    "purpose": "clean_rgb_base_for_neutral_pair_overlay",
                }, ensure_ascii=False) + "\n"
                for r in selected
            ),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "records_in": len(evidence),
                "pair_records_out": len(selected),
                "expected_items": len(selected) * 3,
                "frames_used": sorted({r["frame_sample_id"] for r in selected}),
                "scenes": sorted({r["scene"] for r in selected}),
                "answer_counts": selected[-1]["selection"]["balance_counts"] if selected else {},
                "min_margins": {
                    "dx": min(r["selection"]["margins"]["dx"] for r in selected),
                    "dy": min(r["selection"]["margins"]["dy"] for r in selected),
                    "drange": min(r["selection"]["margins"]["drange"] for r in selected),
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
