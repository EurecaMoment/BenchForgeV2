"""Evidence-oriented scene quality audit.

The auditor records observations and evidence levels instead of inventing a
numeric quality score. It never changes labels, simulator state, or GT.
"""
from __future__ import annotations

from typing import Any

DIMENSIONS = ("geometry", "render", "physics", "interaction", "semantic", "coverage")
EVIDENCE_LEVELS = {"measured", "observed", "declared", "missing"}


def _objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    value = scene.get("objects", [])
    return value if isinstance(value, list) else []


def _item(level: str, observations: list[str] | None = None, gaps: list[str] | None = None, suggestions: list[str] | None = None, *, truth_scope: str = "") -> dict[str, Any]:
    if level not in EVIDENCE_LEVELS:
        raise ValueError(f"unsupported evidence level: {level}")
    result = {"evidence_level": level, "observations": list(observations or []), "capability_gaps": list(gaps or []), "repair_suggestions": list(suggestions or [])}
    if truth_scope:
        result["truth_scope"] = truth_scope
    return result


def _geometry(scene: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    """Assess simulator geometry only; proposal overlap is deliberately ignored."""
    objects = _objects(scene)
    observations = [f"proposal contains {len(objects)} object instances"]
    report = capture.get("geometry") if isinstance(capture.get("geometry"), dict) else {}
    if report.get("valid") is True or report.get("collision_free") is True:
        observations.append("capture reports simulator geometry/collision validation")
        return _item("measured", observations, truth_scope="simulator_geometry_and_collision_report")
    if capture.get("renderable") is True:
        observations.append("capture is renderable")
        return _item("observed", observations, ["native mesh bounds/collider checks are absent", "renderability does not establish collision correctness"], ["record Isaac mesh bounds, collider cooking and contact checks"], truth_scope="renderability_only")
    if objects:
        return _item("declared", observations, ["no simulator geometry receipt"], ["run desktop Isaac geometry and collider validation"], truth_scope="proposal_geometry_only")
    return _item("missing", observations, ["scene has no object geometry"], ["provide scene geometry or explicitly declare an empty-scene task"], truth_scope="none")


def _render(scene: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    cameras = scene.get("cameras", []) if isinstance(scene.get("cameras", []), list) else []
    views = capture.get("views", capture.get("view_count", 0))
    view_count = len(views) if isinstance(views, list) else int(views or 0) if str(views or "0").isdigit() else 0
    observations = [f"proposal cameras: {len(cameras)}", f"captured views: {view_count}"]
    gaps: list[str] = []
    suggestions: list[str] = []
    if capture.get("renderable") is True and view_count:
        observations.append("multi-view render receipt exists")
        if capture.get("lighting") in {"measured", "validated"}:
            observations.append("lighting receipt present")
        else:
            gaps.append("lighting/material response is not independently measured")
            suggestions.append("record renderer, light rig and material diagnostics")
        if isinstance(capture.get("depth"), (dict, list)) or isinstance(capture.get("segmentation"), (dict, list)):
            observations.append("structured auxiliary render modality recorded")
        elif capture.get("depth") or capture.get("segmentation"):
            gaps.append("auxiliary modality is only a boolean declaration")
        else:
            gaps.append("depth/segmentation modality absent from receipt")
        return _item("observed", observations, gaps, suggestions, truth_scope="rendered_pixels_and_declared_modalities")
    return _item("declared" if cameras else "missing", observations, ["no completed multi-view render receipt"], ["render overview, oblique and task-facing views in desktop Isaac"], truth_scope="camera_proposal_only" if cameras else "none")


def _physics(scene: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    physics = capture.get("physics") if isinstance(capture.get("physics"), dict) else {}
    observations: list[str] = []
    gaps = ["stability does not establish real-world mass, friction, damping or restitution"]
    suggestions = ["calibrate material and inertial parameters against measured or asset-authoritative references"]
    if physics.get("stable") is True:
        observations.append("Isaac/PhysX reports a stable rollout")
        level, scope = "observed", "rollout_stability_only"
    elif physics:
        observations.append("physics receipt exists but stability is not confirmed")
        level, scope = "observed", "partial_physics_receipt"
    else:
        level, scope = "declared", "synthetic_priors_only"
        gaps.insert(0, "no simulator physics receipt")
        suggestions.insert(0, "run a short settling and interaction rollout before release")
    if physics.get("steps") is not None:
        observations.append(f"rollout steps: {physics['steps']}")
    if physics.get("contact_pairs") is None:
        gaps.append("contact/manifold evidence is unavailable")
        suggestions.append("record contact pairs, settling displacement and joint-limit violations")
    else:
        observations.append("contact pair receipt exists")
    return _item(level, observations, gaps, suggestions, truth_scope=scope)


def _interaction(scene: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    affordances = scene.get("affordances", scene.get("interactions", []))
    affordances = affordances if isinstance(affordances, list) else []
    navigation = scene.get("navigation") if isinstance(scene.get("navigation"), dict) else {}
    observations: list[str] = []
    if affordances:
        observations.append(f"{len(affordances)} interaction affordances declared")
    if navigation:
        observations.append("navigation graph metadata declared")
    result = capture.get("interaction") if isinstance(capture.get("interaction"), dict) else {}
    action_trace = result.get("action_results", result.get("actions"))
    if result.get("validated") is True and isinstance(action_trace, list) and action_trace:
        return _item("measured", observations + ["simulator action trace and validation recorded"], truth_scope="simulator_action_trace")
    if isinstance(action_trace, list) and action_trace:
        recorded=[a for a in action_trace if isinstance(a,dict) and isinstance(a.get('before'),dict) and isinstance(a.get('after'),dict) and a.get('sample_count',0)>1 and a.get('trajectory_file')]
        if recorded:
            failures=sum(a.get('success') is False for a in recorded)
            return _item("observed", observations + [f"{len(recorded)} simulator action traces recorded; {failures} failed; success not validated"], ["recorded actions did not establish successful interaction"], ["inspect the action trace and repair task parameters using actual failure checks"], truth_scope="simulator_action_trace_without_validated_success")
    if result.get("validated") is True:
        return _item("observed", observations + ["simulator interaction validation recorded"], ["validation has no action-level trace or final-state evidence"], ["record each action, contacts, success condition and final state"], truth_scope="interaction_validation_flag")
    if affordances or navigation:
        return _item("declared", observations, ["declared affordances/navigation have no simulator execution evidence"], ["execute at least one action per affordance and record success, contacts and final state"], truth_scope="interaction_proposal_only")
    return _item("missing", observations, ["scene has no interaction or navigation contract"], ["declare task-relevant affordances without restricting free-form scene composition"], truth_scope="none")


def _semantic(scene: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    layers = scene.get("semantic_layers", [])
    layers = layers if isinstance(layers, list) else []
    observations = [f"{len(layers)} semantic layers declared"] if layers else []
    # Prefer the structured native modality over a legacy boolean convenience
    # flag; booleans prove only that a writer claimed to emit a modality.
    labels = capture.get("semantic_labels")
    if not isinstance(labels, (dict, list)):
        labels = capture.get("segmentation")
    if isinstance(labels, (dict, list)) and bool(labels):
        authority = labels.get("authority") if isinstance(labels, dict) else None
        level = "measured" if authority in {"simulator", "official"} else "observed"
        scope = "native_geometry_and_instance_identity_only" if authority in {"simulator", "official"} else "structured_label_receipt"
        return _item(level, observations + ["structured semantic/instance label receipt is present"], ["instance IDs and geometry labels do not prove visual class correctness"], ["keep reviewer semantic judgments separate from native GT"], truth_scope=scope)
    if labels:
        return _item("declared" if layers else "missing", observations, ["semantic receipt is only a boolean declaration"], ["attach native Isaac instance/geometry IDs and authority"], truth_scope="proposal_semantics_only")
    if layers:
        return _item("declared", observations, ["proposal semantics are not backed by native simulator or official annotations"], ["retain proposal labels as hypotheses; do not replace simulator or official GT"], truth_scope="proposal_semantics_only")
    return _item("missing", observations, ["no authoritative semantic layer or capture labels"], ["export native Isaac semantic/instance IDs as GT"], truth_scope="none")


def _coverage(scene: dict[str, Any], capture: dict[str, Any], intent: dict[str, Any] | None) -> dict[str, Any]:
    intent = intent if isinstance(intent, dict) else {}
    cameras = scene.get("cameras", []) if isinstance(scene.get("cameras", []), list) else []
    observations = [f"{len(cameras)} proposal cameras"] if cameras else []
    captured = capture.get("views", capture.get("view_count", 0))
    count = len(captured) if isinstance(captured, list) else int(captured or 0) if str(captured or "0").isdigit() else 0
    if count:
        observations.append(f"{count} captured views")
    gaps: list[str] = []
    requested = intent.get("required_views", intent.get("views"))
    if requested is not None and str(requested).isdigit() and count < int(requested):
        gaps.append(f"captured views {count} below requested {int(requested)}")
    if not count:
        return _item("declared" if cameras else "missing", observations, gaps + ["coverage is proposal-only"], ["capture task-facing, overview and occlusion-revealing views before release"], truth_scope="camera_proposal_only" if cameras else "none")
    return _item("observed", observations, gaps, ["add missing views or mark the scene as an exploration candidate"] if gaps else [], truth_scope="captured_view_count")


def audit_scene(scene: dict[str, Any], capture: dict[str, Any] | None = None, intent: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a six-dimension evidence report without numeric quality claims."""
    if not isinstance(scene, dict):
        raise TypeError("scene must be a mapping")
    capture = capture if isinstance(capture, dict) else {}
    dimensions = {"geometry": _geometry(scene, capture), "render": _render(scene, capture), "physics": _physics(scene, capture), "interaction": _interaction(scene, capture), "semantic": _semantic(scene, capture), "coverage": _coverage(scene, capture, intent)}
    observed = sum(item["evidence_level"] in {"measured", "observed"} for item in dimensions.values())
    publication_ready = all(dimensions[key]["evidence_level"] in {"measured", "observed"} for key in DIMENSIONS)
    # Evidence of a failed action is still evidence, but cannot improve release eligibility.
    if dimensions['interaction'].get('truth_scope')=='simulator_action_trace_without_validated_success':publication_ready=False
    tier = "publishable_candidate" if publication_ready else "pilot_candidate" if observed else "exploration_candidate"
    gaps = [gap for item in dimensions.values() for gap in item["capability_gaps"]]
    suggestions = [suggestion for item in dimensions.values() for suggestion in item["repair_suggestions"]]
    return {"schema": "spatialforge.scene-quality/v2", "scene_id": scene.get("scene_id"), "tier": tier, "evidence_summary": {"observed_or_measured_dimensions": observed, "dimensions": len(dimensions), "publication_gate": "all six dimensions require simulator/official evidence"}, "dimensions": dimensions, "capability_gaps": list(dict.fromkeys(gaps)), "repair_suggestions": list(dict.fromkeys(suggestions)), "gt_authority": "native_simulator_or_official_source_only", "gt_written": False}


def audit_scene_quality(scene: dict[str, Any], capture: dict[str, Any] | None = None, intent: dict[str, Any] | None = None) -> dict[str, Any]:
    return audit_scene(scene, capture, intent)
