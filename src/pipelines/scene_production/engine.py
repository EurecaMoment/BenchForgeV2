"""Coordinate queued scene authoring, asset generation, review and delivery."""
from pipelines.scene_production.planning import plan_scene
from pipelines.scene_production.review import review_scene
from pipelines.scene_production.scheduler import capture_handoff as _scheduler_capture_handoff
from pipelines.scene_production.scheduler import coordinate as _coordinate
from capabilities.asset_generation.generation import GenerationTools
from capabilities.asset_generation.generation import ResourceWait
from capabilities.asset_generation.asset_review import review_generated_asset
from capabilities.scene_authoring.validation.policy import policy_for

def _capture_handoff(unit):
    return _scheduler_capture_handoff(unit)

def coordinate(store,stop):
    return _coordinate(
        store,
        stop,
        plan_scene=plan_scene,
        review_scene=review_scene,
        policy_for=policy_for,
        capture_only_review=review_scene,
        capture_handoff=_capture_handoff,
        generation_tools=GenerationTools,
        generated_asset_reviewer=review_generated_asset,
        resource_wait=ResourceWait,
    )
