"""Deterministic repair routing for failed pipeline artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_graph import ArtifactGraph


OPERATORS = {
    "local_field_repair": "Change only the invalid request or artifact field.",
    "template_rebinding": "Bind the candidate to a compatible evidence/template pair.",
    "candidate_resynthesis": "Regenerate the candidate while retaining valid upstream evidence.",
    "skill_reexecution": "Re-run the failed backend with the same declared inputs.",
    "upstream_rollback": "Return to the earliest invalid evidence or state artifact.",
    "final_rejection": "Quarantine the lineage; do not relax its contract.",
}


def choose_operator(failure_code: str | None, artifact_type: str | None = None) -> str:
    code = (failure_code or "").casefold()
    if code in {"missing_binding", "missing_field", "invalid_request"}:
        return "local_field_repair"
    if code in {"template_binding", "evidence_mismatch", "protocol_mismatch"}:
        return "template_rebinding"
    if code in {"contract_failure", "invalid_item", "scoring_mismatch"}:
        return "candidate_resynthesis"
    if code in {"execution_error", "timeout", "service_unavailable", "terminal_failure"}:
        return "skill_reexecution"
    if code in {"invalid_evidence", "state_drift", "source_missing", "needs_evidence"}:
        return "upstream_rollback"
    if artifact_type in {"benchmark.package", "benchmark.dataset"} and code == "":
        return "candidate_resynthesis"
    return "final_rejection"


def create_plan(*, run: str | Path, artifact: dict[str, Any] | None = None,
                failure_code: str | None = None, reason: str | None = None) -> dict[str, Any]:
    row = artifact or {}
    operator = choose_operator(failure_code, row.get("artifact_type"))
    code = failure_code or "unclassified_failure"
    return {
        "schema": "benchforge.repair-plan/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run": str(Path(run).resolve()),
        "artifact_id": row.get("artifact_id"),
        "artifact_type": row.get("artifact_type"),
        "failure_code": code,
        "operator": operator,
        "scope": "artifact_and_downstream_dependents" if operator == "upstream_rollback" else "artifact",
        "reason": reason or OPERATORS[operator],
        "requires_new_run": True,
        "status": "proposed",
        "guard": "Re-run the same contracts and quality gates after repair; never modify GT to satisfy them.",
    }


def repair_plan(args, directory=None, config=None):
    graph = ArtifactGraph(args["run"])
    rows = graph.find(args.get("artifact_id"))
    artifact = rows[-1] if rows else None
    if args.get("artifact_id") and artifact is None:
        raise ValueError(f"Unknown artifact: {args['artifact_id']}")
    if artifact is None:
        rejected = [row for row in graph.records if row.get("status") == "rejected"]
        artifact = rejected[-1] if rejected else {}
    plan = create_plan(run=args["run"], artifact=artifact,
                       failure_code=args.get("failure_code"), reason=args.get("reason"))
    graph.append_repair(plan)
    return plan
