"""Execution mode and operator policy resolution for scene requests."""
import json
from pathlib import Path
from .runtime_config import environment_value


EXECUTION_MODES = {"production", "exploration"}


def resolve_execution_mode(value=None):
    configured = environment_value("BENCHFORGE_EXECUTION_MODE")
    if value is not None and configured is not None and value != configured:
        raise ValueError(
            f"request execution_mode {value!r} conflicts with configured mode {configured!r}"
        )
    if value is None:
        value = configured
    if value is None:
        # Preserve legacy local callers while making the resulting mode explicit
        # in the stored run and delivery receipt.
        return "exploration"
    if value not in EXECUTION_MODES:
        raise ValueError("execution_mode must be production or exploration")
    return value


def policy_for(root, execution_mode=None):
    configured = environment_value("BENCHFORGE_EXECUTION_MODE")
    if execution_mode is not None or configured is not None:
        mode = resolve_execution_mode(execution_mode)
    else:
        # Direct legacy callers used the presence of an operator policy as the
        # opt-in gate before execution_mode was stored on each scene.
        mode = None
    explicit = environment_value("BENCHFORGE_SCENE_POLICY")
    local = Path(root) / "scene_policy.json"
    path = (
        Path(explicit)
        if explicit
        else local
        if local.is_file()
        else Path(root).absolute().parent / "scene-library/policy.json"
    )
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    enabled = value.get("enabled") is True and value.get("enforce_realism") is True
    if mode == "production" and not enabled:
        raise ValueError(
            "production execution requires an enabled scene policy with enforce_realism=true"
        )
    if mode == "exploration":
        return {}
    if enabled:
        value["require_scene_brief"] = True
        return value
    return {}


def _inside_exclusion(value, policy):
    if value in (
        set(policy.get("excluded_tasks", []))
        | set(policy.get("excluded_runs", []))
        | set(policy.get("excluded_scene_groups", []))
    ):
        return True
    if Path(value).is_absolute():
        path = Path(value).resolve()
        return any(
            path == Path(item).resolve()
            or path.is_relative_to(Path(item).resolve())
            for item in policy.get("excluded_paths", [])
        )
    return False


def check_references(value, policy):
    if isinstance(value, dict):
        for child in value.values():
            check_references(child, policy)
    elif isinstance(value, list):
        for child in value:
            check_references(child, policy)
    elif isinstance(value, str) and _inside_exclusion(value, policy):
        raise ValueError(
            "Scene was removed by the user; its source and derived artifacts cannot be reused"
        )


def check_request(root, route, arguments):
    intents = arguments.get("intents", []) if route == "/start" else [arguments]
    if route == "/start" and not intents:
        return
    if route not in {"/start", "/capture", "/refine", "/extend", "/retry"}:
        return

    from . import scene_acceptance

    def admission_policy(execution_mode):
        try:
            return scene_acceptance.policy_for(root, execution_mode)
        except TypeError:
            # Retain small test adapters written against the earlier one-arg API.
            return scene_acceptance.policy_for(root)

    route_policies = []
    for intent in intents:
        requested_mode = intent.get("execution_mode", arguments.get("execution_mode"))
        mode = resolve_execution_mode(requested_mode)
        route_policies.append((intent, mode, admission_policy(requested_mode)))
    if not any(policy for _, _, policy in route_policies):
        return
    for _, _, policy in route_policies:
        if policy:
            check_references(arguments, policy)
    if route == "/retry":
        from .scene_design import capture_retry_directory
        from .scene_acceptance import admit_program

        if arguments.get("feedback") is not None:
            raise ValueError("Scene design changes require capture/refine, not review retries")
        directory = capture_retry_directory(root, arguments.get("task_id"))
        admit_program(
            root,
            json.loads((directory / "program.json").read_text()),
            execution_mode=mode,
        )
        return
    if route in {"/start", "/capture", "/refine", "/extend"}:
        from .program_submission import read_program_submission
        from .scene_acceptance import admit_program

        for intent, mode, policy in route_policies:
            path = intent.get("scene_program_path")
            must_submit_program = mode == "production" or (
                intent.get("execution_mode") is None
                and arguments.get("execution_mode") is None
                and bool(policy)
            )
            if must_submit_program and not path:
                raise ValueError("The unchecked default planner is disabled; provide scene_program_path")
            if path and policy:
                check_references(path, policy)
                submission = read_program_submission(root, path)
                if mode == "production" or must_submit_program:
                    admit_program(root, submission["program"], allow_generated=True, execution_mode=mode)
