"""Application use cases for starting and revising scene workflows."""
from scene_production.server.capture_evidence.capture_scope import capture_scope
from scene_production.server.asset_generation.layout import default_layout
from scene_production.server.asset_generation.layout import validate_layout
from scene_production.server.scene_program.program_submission import read_program_submission
from benchmark_workflows.contracts.quantity import validate_quantity_contract
from service_access.request_context import RunContext
from scene_production.server.scene_program.validation.policy import policy_for
from scene_production.server.scene_program.validation.policy import resolve_execution_mode


def scene_intent(intent):
    required = {"name", "description", "split"}
    allowed = required | {
        "target_items",
        "quantity_contract",
        "execution_mode",
        "layout",
        "scene_program_path",
    }
    if not isinstance(intent, dict) or not required <= set(intent):
        raise ValueError("scene requires name, description, split")
    if set(intent) - allowed:
        raise ValueError("unknown scene intent fields")
    if "scene_program_path" in intent and (
        not isinstance(intent["scene_program_path"], str)
        or not intent["scene_program_path"]
    ):
        raise ValueError("scene_program_path must be a task JSON source_path")
    if "layout" in intent:
        validate_layout(intent["layout"])
    if (
        intent["split"] not in {"train", "dev"}
        or not isinstance(intent["description"], str)
        or not 1 <= len(intent["description"]) <= 12000
    ):
        raise ValueError("invalid scene intent")
    if not isinstance(intent["name"], str) or not 1 <= len(intent["name"]) <= 200:
        raise ValueError("invalid name")
    target = intent.get("target_items", 24)
    if type(target) is not int or not 1 <= target <= 1000:
        raise ValueError("invalid target item budget")
    validate_quantity_contract(intent.get("quantity_contract", "best_effort"))
    resolve_execution_mode(intent.get("execution_mode"))
    return intent


def _scene_intent(value, request):
    intent = dict(value)
    if "execution_mode" not in intent:
        intent["execution_mode"] = request.get("execution_mode")
    intent["execution_mode"] = resolve_execution_mode(intent["execution_mode"])
    if "quantity_contract" not in intent and "quantity_contract" in request:
        intent["quantity_contract"] = request["quantity_contract"]
    intent.setdefault("quantity_contract", "best_effort")
    scene_intent(intent)
    policy_for(request["root"], intent["execution_mode"])
    return intent


def context_from_request(request, parent_run_id=None):
    value = request.get("context")
    context = RunContext.from_request(value)
    if context is None and parent_run_id:
        context = RunContext(parent_run_id=parent_run_id)
    elif context is not None and parent_run_id and not context.parent_run_id:
        context = RunContext(
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            parent_run_id=parent_run_id,
        )
    return context


def start_scene_request(
    store,
    value,
    max_scenes=1000,
    *,
    submission_reader=read_program_submission,
    prior_reference_checker=None,
):
    intents = value["intents"]
    if not isinstance(intents, list) or not 1 <= len(intents) <= max_scenes:
        raise ValueError("scene count exceeds registered run budget")
    normalized = [_scene_intent(item, {**value, "root": store.root}) for item in intents]
    submissions = [
        submission_reader(store.root, intent["scene_program_path"])
        if "scene_program_path" in intent
        else None
        for intent in normalized
    ]
    if prior_reference_checker is None:
        from scene_production.server.asset_generation.layout import require_prior_reference

        prior_reference_checker = require_prior_reference
    for intent in normalized:
        prior_reference_checker(store, intent)
    normalized = [
        {**intent, "layout": intent.get("layout") or default_layout(intent)}
        for intent in normalized
    ]
    kwargs = {}
    context = context_from_request(value)
    if context is not None:
        kwargs["context"] = context
    return {
        "run_id": store.submit(
            value["request_key"],
            normalized,
            submitted_programs=submissions if any(submissions) else None,
            **kwargs,
        ),
        "state": "accepted",
        "program_handoff": [
            "validated_frozen_snapshot" if item else "planner"
            for item in submissions
        ],
    }


def start_capture_request(
    store,
    value,
    *,
    submission_reader=read_program_submission,
):
    submission = submission_reader(store.root, value["scene_program_path"])
    mode = resolve_execution_mode(value.get("execution_mode"))
    policy_for(store.root, mode)
    intent = {
        "name": value.get("name", submission["program"]["title"]),
        "description": "Capture the supplied SceneProgram.",
        "split": "dev",
        "capture_only": True,
        "scene_program_path": value["scene_program_path"],
        "execution_mode": mode,
    }
    if "layout" in value:
        intent["layout"] = validate_layout(value["layout"])
    if "capture_options" in value:
        capture_scope(submission["program"], value["capture_options"])
        intent["capture_options"] = value["capture_options"]
    kwargs = {}
    context = context_from_request(value)
    if context is not None:
        kwargs["context"] = context
    run_id = store.submit(
        value["request_key"], [intent], submitted_programs=[submission], **kwargs
    )
    return {
        "run_id": run_id,
        "task_id": run_id + ".scene0",
        "state": "accepted",
        "operation": "capture_only",
    }


def refine_scene_request(
    store,
    value,
    *,
    submission_reader=read_program_submission,
    prior_reference_checker=None,
):
    parent = value["parent_task_id"]
    snapshot = store.snapshot(parent.split(".")[0])
    task = next(row for row in snapshot["tasks"] if row["id"] == parent)
    if task["unit"].get("workflow", "scene") != "scene":
        raise ValueError("refine requires a scene task")
    if (
        snapshot["state"] not in {"SUCCEEDED", "FAILED_FINAL", "CANCELED"}
        or task["state"] not in {"SUCCEEDED", "FAILED_FINAL", "CANCELED"}
    ):
        raise ValueError("source run is still active; wait for its terminal state before refining")
    source_revision = value.get("source_revision", task["unit"]["revision"])
    if type(source_revision) is not int or not 0 <= source_revision <= task["unit"]["revision"]:
        raise ValueError("source_revision must identify an existing revision")
    directory = store.root / parent / f"revision_{source_revision}"
    if not (directory / "capture" / "evidence.json").is_file():
        raise ValueError("refine requires captured scene evidence")

    parent_intent = task["unit"]["intent"]
    merged_request = {
        **value,
        "execution_mode": value.get(
            "execution_mode", parent_intent.get("execution_mode")
        ),
        "quantity_contract": value.get(
            "quantity_contract", parent_intent.get("quantity_contract", "best_effort")
        ),
        "root": store.root,
    }
    intent = scene_intent(
        {
            "name": value["name"],
            "description": value["description"],
            "split": parent_intent["split"],
            "target_items": value.get(
                "target_items", parent_intent.get("target_items", 24)
            ),
            "quantity_contract": merged_request["quantity_contract"],
            "execution_mode": resolve_execution_mode(merged_request["execution_mode"]),
        }
    )
    policy_for(store.root, intent["execution_mode"])
    if parent_intent.get("capture_only") and "target_items" not in value:
        intent.pop("target_items")
        intent["capture_only"] = True
    if "layout" in value:
        intent["layout"] = validate_layout(value["layout"])
    submission = None
    if "scene_program_path" in value:
        submission = submission_reader(store.root, value["scene_program_path"])
        intent["scene_program_path"] = value["scene_program_path"]
    if prior_reference_checker is None:
        from scene_production.server.asset_generation.layout import require_prior_reference

        prior_reference_checker = require_prior_reference
    prior_reference_checker(store, intent, directory)
    intent.update(
        refine_task_id=parent,
        refine_revision=source_revision,
        scene_family=parent_intent.get("scene_family", parent),
    )
    kwargs = {}
    context = context_from_request(value, parent.split(".")[0])
    if context is not None:
        kwargs["context"] = context
    run_id = store.submit(
        value["request_key"],
        [intent],
        submitted_programs=[submission] if submission else None,
        **kwargs,
    )
    return {
        "run_id": run_id,
        "task_id": run_id + ".scene0",
        "state": "accepted",
        "operation": "capture_only" if intent.get("capture_only") else "scene_pipeline",
        "inherited_split": intent["split"],
        "source_revision": intent["refine_revision"],
        "program_handoff": "validated_frozen_snapshot" if submission else "planner_refinement",
    }


def extend_scene_request(
    store,
    value,
    *,
    submission_reader=read_program_submission,
    prior_reference_checker=None,
):
    parent = value["parent_task_id"]
    snapshot = store.snapshot(parent.split(".")[0])
    task = next(row for row in snapshot["tasks"] if row["id"] == parent)
    if task["state"] != "SUCCEEDED" or task["unit"].get("workflow", "scene") != "scene":
        raise ValueError("extend an available captured scene task")
    revision = task["unit"]["revision"]
    directory = store.directory(parent, revision)
    mode = resolve_execution_mode(
        value.get("execution_mode", task["unit"]["intent"].get("execution_mode"))
    )
    policy = policy_for(store.root, mode)
    if policy:
        from scene_production.server.scene_program.validation.acceptance import require_accepted

        require_accepted(store.root, directory, mode)
    intent = scene_intent(
        {
            "name": value["name"],
            "description": value["description"],
            "split": task["unit"]["intent"]["split"],
            "target_items": value.get("target_items", 24),
            "quantity_contract": value.get(
                "quantity_contract",
                task["unit"]["intent"].get("quantity_contract", "best_effort"),
            ),
            "execution_mode": mode,
            **(
                {"scene_program_path": value["scene_program_path"]}
                if value.get("scene_program_path")
                else {}
            ),
        }
    )
    if "layout" in value:
        intent["layout"] = validate_layout(value["layout"])
    submission = (
        submission_reader(store.root, value["scene_program_path"])
        if value.get("scene_program_path")
        else None
    )
    if policy and not submission:
        raise ValueError("Realistic scene extension requires a complete SceneProgram")
    intent.update(
        parent_task_id=parent,
        parent_revision=revision,
        extend_task_id=parent,
        extend_revision=revision,
        scene_family=task["unit"]["intent"].get("scene_family", parent),
    )
    if prior_reference_checker is None:
        from scene_production.server.asset_generation.layout import require_prior_reference

        prior_reference_checker = require_prior_reference
    prior_reference_checker(store, intent, directory)
    kwargs = {}
    context = context_from_request(value, parent.split(".")[0])
    if context is not None:
        kwargs["context"] = context
    run_id = store.submit(
        value["request_key"],
        [intent],
        submitted_programs=[submission] if submission else None,
        **kwargs,
    )
    return {
        "run_id": run_id,
        "task_id": run_id + ".scene0",
        "state": "accepted",
        "inherited_split": intent["split"],
        "source_revision": revision,
        "program_handoff": "validated_frozen_snapshot" if submission else "planner_extension",
    }
