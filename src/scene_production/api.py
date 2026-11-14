"""Public scene policy, evidence and catalog queries for other features."""
from .server.scene_library.source_policy import (
    CLASSIFIER_VERSION, check_evidence, check_source, classify, classify_planned, load_policy,
    planned_geometry, scene_design_parser,
)
from .server.scene_program.validation.policy import resolve_execution_mode
from .server.scene_library.observations import saved_scene_identity, stage_artifacts

def require_accepted(*args, **kwargs):
    from .server.scene_program.validation.acceptance import require_accepted
    return require_accepted(*args, **kwargs)

def native_identity(*args, **kwargs):
    from .server.scene_library.scene_library import native_identity
    return native_identity(*args, **kwargs)

def registration_metadata(*args, **kwargs):
    from .server.scene_library.scene_library import registration_metadata
    return registration_metadata(*args, **kwargs)
