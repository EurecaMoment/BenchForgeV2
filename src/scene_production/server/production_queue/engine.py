"""Coordinate queued scene authoring, asset generation, review and delivery."""
from scene_production.server.scene_program.planning import plan_scene
from scene_production.server.capture_evidence.review import review_scene
from scene_production.server.production_queue.scene_scheduler import capture_handoff as _scheduler_capture_handoff
from scene_production.server.production_queue.scene_scheduler import coordinate as _coordinate
from scene_production.server.asset_generation.generation import GenerationTools
from scene_production.server.asset_generation.generation import ResourceWait
from scene_production.server.asset_generation.asset_review import review_generated_asset
from scene_production.server.scene_program.validation.policy import policy_for

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
