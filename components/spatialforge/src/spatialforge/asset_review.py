"""Flash semantic review for generated asset candidates.

This module reviews visible semantics only. It never changes registered asset
records and never creates simulator ground truth. Candidates are retained so a
later human or scene-level review can inspect the tradeoff.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchclaw.store import write_json

from .model import completion
from .generation import ResourceWait


_REVIEW_PROMPT = """You are a careful human asset editor reviewing one generated reference image.
Judge only what is visibly supported by the image and the user's requested
object/function. Do not infer hidden 3D geometry, mass, material coefficients,
or simulator ground truth. Check object identity, requested visible state
(including words such as closed/open, folded/unfolded, empty/full), completeness,
single-object presentation, and obvious generation artifacts.
Return only JSON:
{"acceptable":boolean,"identity_match":boolean,"state_match":boolean,
"completeness":1,"issues":[string],"repair_prompt":string}
Use an empty repair_prompt when acceptable. A proposed repair must preserve the
requested object and explicitly state the required visible state; it is guidance
for an image-generation retry, not an assertion that the 3D result is correct.

REQUEST:
"""


def _asset_image(asset: dict[str, Any]) -> Path:
    files = asset.get("files") or {}
    source_work = Path(asset.get("source_work", ""))
    if "reference.png" in files and source_work.joinpath("reference.png").is_file():
        return source_work / "reference.png"
    # Published assets normally have the registry directory as the parent of
    # asset.json. The caller may also pass an explicit reference_image.
    explicit = asset.get("reference_image")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    registry = asset.get("registry_dir")
    if registry and Path(registry, "reference.png").is_file():
        return Path(registry) / "reference.png"
    raise FileNotFoundError("generated asset has no readable reference.png")


def _review(prompt: dict[str, Any], image: Path, trace: Path) -> dict[str, Any]:
    text = json.dumps(prompt, ensure_ascii=False, indent=2)
    result = completion(_REVIEW_PROMPT + text, trace, [image], max_tokens=3000)
    if not isinstance(result, dict):
        raise ValueError("asset review must be a JSON object")
    required = {"acceptable", "identity_match", "state_match", "completeness", "issues", "repair_prompt"}
    if not required <= set(result):
        raise ValueError("asset review omitted required semantic fields")
    if not isinstance(result["acceptable"], bool) or not isinstance(result["identity_match"], bool) or not isinstance(result["state_match"], bool):
        raise ValueError("asset review boolean fields are invalid")
    if type(result["completeness"]) not in (int, float) or not 1 <= result["completeness"] <= 5:
        raise ValueError("asset review completeness must be between 1 and 5")
    if not isinstance(result["issues"], list) or not all(isinstance(item, str) for item in result["issues"]):
        raise ValueError("asset review issues must be strings")
    if not isinstance(result["repair_prompt"], str):
        raise ValueError("asset review repair_prompt must be a string")
    return result


def _candidate_with_image(asset: dict[str, Any], image: Path) -> dict[str, Any]:
    result = dict(asset)
    result["reference_image"] = str(image)
    # registry_dir allows review of records returned by old generation code,
    # where files were summarized but not explicitly linked.
    if asset.get("asset_id"):
        result.setdefault("registry_dir", str(Path(image).parent))
    return result


def review_generated_asset(tools, spec: dict[str, Any], asset: dict[str, Any], work, stop, *, repair=True):
    """Review an asset and, at most once, create a semantically repaired candidate.

    ``tools`` is a :class:`GenerationTools` instance. The selected candidate is
    returned with ``quality`` flags and the immutable ``selection.json`` path.
    Operator asset calls return feedback without replacing their candidate.
    Automatic scene planning can repair generated images once. A supplied image
    can change only when its caller requested reference editing.
    """
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    selection_path = work / "selection.json"
    if selection_path.is_file():
        return json.loads(selection_path.read_text(encoding="utf-8"))["selected"]
    image = _asset_image(asset)
    try:
        initial = _review(spec, image, work / "review_0")
    except Exception as exc:
        selected = dict(asset)
        selected["quality"] = {"semantic_review": "unreviewed", "reason": f"{type(exc).__name__}: {exc}", "3d_validated": False}
        payload = {"selected": selected, "candidates": [{"asset_id": asset.get("asset_id"), "review": None}], "selection_reason": "review_unavailable"}
        write_json(selection_path, payload)
        return selected
    candidates = [{"asset": asset, "review": initial}]
    selected = asset
    if not initial["acceptable"] and repair and (not spec.get("source_image") or spec.get("edit_reference")):
        if stop.is_set():
            raise RuntimeError("asset review canceled; original candidate retained")
        repair_prompt = initial["repair_prompt"].strip() or (
            "Preserve the requested object identity and create the requested visible state exactly. "
            + "; ".join(initial["issues"])
        )
        revised = dict(spec)
        revised["prompt"] = (str(spec.get("prompt", spec.get("label", "object"))) + ". Correct the previous candidate: " + repair_prompt).strip()
        revised.pop("asset_id", None)
        revised_work = work / "revision_1"
        try:
            revised_asset = tools.generate_asset(revised, revised_work, stop)
            revised_image = _asset_image(revised_asset)
            try:
                revised_review = _review(revised, revised_image, work / "review_1")
            except Exception as exc:
                revised_review = {"acceptable": False, "identity_match": False, "state_match": False, "completeness": 0, "issues": [f"review unavailable: {type(exc).__name__}: {exc}"], "repair_prompt": ""}
            candidates.append({"asset": revised_asset, "review": revised_review})
            if revised_review["acceptable"] and not initial["acceptable"]:
                selected = revised_asset
                initial = revised_review
        except ResourceWait:
            # Let the coordinator reschedule when no generation GPU is free.
            # The immutable initial candidate is still untouched on disk.
            raise
        except Exception as exc:
            # Preserve the original candidate and an explicit failed-repair
            # record. ResourceWait is intentionally retained as a quality flag
            # here because this function must leave a reviewable selection file.
            candidates.append({"asset": {"asset_id": None}, "review": {"acceptable": False, "issues": [f"repair generation failed: {type(exc).__name__}: {exc}"]}})
    selected = dict(selected)
    selected["quality"] = {"semantic_review": "passed" if initial["acceptable"] else "needs_improvement", "identity_match": initial["identity_match"], "state_match": initial["state_match"], "completeness": initial["completeness"], "issues": initial["issues"], "repair_prompt": initial["repair_prompt"], "3d_validated": False}
    payload = {"selected": selected, "candidates": [{"asset_id": c["asset"].get("asset_id"), "review": c["review"]} for c in candidates], "selection_reason": "semantic_review"}
    write_json(selection_path, payload)
    return selected
