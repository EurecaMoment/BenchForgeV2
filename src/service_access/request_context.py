"""Optional, service-owned identifiers that follow a BenchForge run."""
from dataclasses import dataclass
from dataclasses import replace
from typing import Mapping


_EXTERNAL_FIELDS = {"workspace_id", "session_id", "parent_run_id"}
_SERVICE_FIELDS = {"run_id", "stage_id", "attempt_id"}


@dataclass(frozen=True)
class RunContext:
    workspace_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    stage_id: str | None = None
    attempt_id: str | None = None

    @classmethod
    def from_request(cls, value):
        """Validate caller identity without accepting service-owned IDs."""
        if value is None:
            return None
        if isinstance(value, cls):
            raw = value.to_dict()
        elif isinstance(value, Mapping):
            raw = dict(value)
        else:
            raise ValueError("context must be an object")

        forbidden = set(raw) & _SERVICE_FIELDS
        if forbidden:
            raise ValueError(
                "context fields are service-owned and cannot be supplied: "
                + ", ".join(sorted(forbidden))
            )
        unknown = set(raw) - _EXTERNAL_FIELDS
        if unknown:
            raise ValueError("unknown context fields: " + ", ".join(sorted(unknown)))

        fields = {}
        for name, item in raw.items():
            if item is None:
                continue
            if not isinstance(item, str) or not item.strip() or len(item) > 200:
                raise ValueError(f"context.{name} must be a non-empty string of at most 200 characters")
            fields[name] = item
        return cls(**fields)

    @classmethod
    def from_record(cls, value):
        """Load a context already stored by the service."""
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("stored run context must be an object")
        unknown = set(value) - (_EXTERNAL_FIELDS | _SERVICE_FIELDS)
        if unknown:
            raise ValueError("unknown stored context fields: " + ", ".join(sorted(unknown)))
        for name, item in value.items():
            if item is not None and (not isinstance(item, str) or not item.strip() or len(item) > 200):
                raise ValueError(f"context.{name} must be a non-empty string of at most 200 characters")
        return cls(**{name: item for name, item in value.items() if item is not None})

    def for_run(self, run_id):
        return replace(self, run_id=run_id, stage_id=None, attempt_id=None)

    def for_stage(self, stage_id, attempt_id):
        if not self.run_id:
            raise ValueError("run context must be bound to a run before a stage")
        return replace(self, stage_id=stage_id, attempt_id=attempt_id)

    def to_dict(self):
        return {key: value for key, value in vars(self).items() if value is not None}


class RunCancelled(RuntimeError):
    """Raised when a running scene stage observes its cancellation signal."""


def check_cancelled(stop, stage):
    if stop is not None and stop.is_set():
        raise RunCancelled(f"BenchForge run canceled during {stage}")
