from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Nonempty = Annotated[str, Field(min_length=1)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    contract_version: Literal["benchclaw/v1"] = "benchclaw/v1"
    producer: str = "benchclaw"
    producer_version: str = "0.1.0"
    created_at: str = Field(default_factory=now)


class Issue(Contract):
    code: str
    severity: Literal["info", "warning", "error", "fatal"] = "error"
    entity_type: str = "work_item"
    entity_id: str = ""
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    repair_hint: str | None = None


class Failure(Contract):
    code: str
    message: str
    retryable: bool = False
    component: str = "harness"
    attempt: int = 0
    stderr_tail: str = ""


class HarnessError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.failure = Failure(code=code, message=message, retryable=retryable)


class State(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    QUARANTINED = "QUARANTINED"
    SUCCEEDED = "SUCCEEDED"
    CANCELED = "CANCELED"


TERMINAL = {State.FAILED_FINAL, State.QUARANTINED, State.SUCCEEDED, State.CANCELED}


class Resources(Contract):
    cpu: int = Field(default=1, ge=1)
    gpu: int = Field(default=0, ge=0)
    memory_gb: float = Field(default=2, gt=0)


class RetryPolicy(Contract):
    max_attempts: int = Field(default=3, ge=1, le=20)
    backoff_seconds: float = Field(default=2, ge=0, le=3600)
    timeout_seconds: float = Field(default=300, gt=0, le=86400)


class SourceSpec(Contract):
    source_id: Identifier
    plugin: str = "source.entities"
    parameters: dict[str, JsonValue]


class CollectionPolicy(Contract):
    """Administrator-defined acceptance intent; models cannot weaken it."""
    min_items: int = Field(default=1,ge=1)
    min_source_records: int = Field(default=1,ge=1)
    max_majority_baseline: Probability = 0.75
    baseline_min_items: int = Field(default=4,ge=2)
    required_templates: list[Identifier] = Field(default_factory=list)


class DatasetSpec(Contract):
    contract_version: Literal["benchclaw.dataset-spec/v1"] = "benchclaw.dataset-spec/v1"
    name: Identifier
    objective: Nonempty
    revision: Identifier = "v1"
    sources: list[SourceSpec] = Field(min_length=1)
    target_items: int = Field(default=15, ge=1, le=10000000)
    modalities: list[Literal['rgb','depth','mask','pose','action','state','pointcloud']] = Field(default_factory=lambda: ['rgb'], min_length=1)
    capabilities: list[Literal['relative_position_2d','template_static','official_qa','habitat_rgbd','libero_multiview','carla_multicam','data_cleaning','grey_validation','analysis_cdm_irt','metric_program']] = Field(default_factory=lambda: ['relative_position_2d'], min_length=1,max_length=20)
    relation_axes: list[Literal['x','y']] = Field(default_factory=lambda: ['x','y'], min_length=1,max_length=2)
    relation_options: Literal['four_directions','axis_pair'] = 'four_directions'
    template_set: Literal['bbox_center_2d','strict_core','strict_depth','strict_all_supported'] = 'bbox_center_2d'
    template_ids: list[Identifier] = Field(default_factory=list,max_length=100)
    task_contract: Literal['legacy-v1','spatial-v2'] = 'legacy-v1'
    collection_policy: CollectionPolicy | None = None
    cleaning: Literal['none','standard','data_juicer'] = 'standard'
    research: dict[str,JsonValue] = Field(default_factory=dict)
    semantic_review: dict[str,JsonValue] = Field(default_factory=dict)
    purpose: Literal['evaluation','training'] = 'evaluation'
    language: Literal["zh-CN", "en"] = "zh-CN"
    quality_policy: Literal["development-v1", "production-v1"] = "development-v1"
    split_policy: Literal["scene_disjoint"] = "scene_disjoint"
    seed: int = 42
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    capacity: Resources = Field(default_factory=Resources)

    @model_validator(mode="after")
    def unique_sources(self):
        if self.task_contract=='spatial-v2' and self.template_set=='bbox_center_2d':
            raise ValueError('spatial-v2 uses the explicit template catalogue')
        if len(set(self.template_ids))!=len(self.template_ids) or len(self.template_ids)>self.target_items:
            raise ValueError('Requested template IDs must be unique and fit the item budget')
        if len(set(self.relation_axes))!=len(self.relation_axes):
            raise ValueError('duplicate relation axis')
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source_id")
        return self


class WorkUnit(Contract):
    task_id: Identifier
    stage: int = Field(ge=1, le=5)
    plugin_id: str
    plugin_version: str = "0.1.0"
    operation: str = "execute"
    depends_on: list[str] = Field(default_factory=list)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    resources: Resources = Field(default_factory=Resources)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)


class Plan(Contract):
    spec: DatasetSpec
    tasks: list[WorkUnit]


class ArtifactRef(Contract):
    artifact_id: Identifier
    run_id: Identifier
    work_item_id: Identifier
    uri: str
    byte_size: int = Field(ge=1)
    files: dict[str, int]
    revision: str


class SpatialContext(Contract):
    context_id: Identifier
    scene_id: Identifier
    sensor_frame_id: str = "image"
    world_frame_id: str | None = None
    coordinate_convention: Literal["image_x_right_y_down", "camera_x_right_y_down_z_forward"]
    length_unit: Literal["px", "m", "cm", "mm"]
    bbox_format: Literal["xyxy"] = "xyxy"
    pixel_boundary: Literal["half_open"] = "half_open"
    transform_direction: Literal["sensor_to_world"] = "sensor_to_world"
    depth_representation: Literal["metric_depth", "normalized_depth", "inverse_depth", "disparity"] | None = None
    depth_axis: Literal["camera_z", "euclidean_range"] | None = None
    camera_intrinsics: list[list[float]] | None = None
    camera_extrinsics: list[list[float]] | None = None

    @model_validator(mode="after")
    def matrices(self):
        k, t = self.camera_intrinsics, self.camera_extrinsics
        if k is not None:
            if len(k) != 3 or any(len(row) != 3 for row in k):
                raise ValueError("intrinsics must be 3x3")
            if k[0][0] <= 0 or k[1][1] <= 0 or k[2] != [0, 0, 1]:
                raise ValueError("invalid camera intrinsics")
        if t is not None:
            if len(t) != 4 or any(len(row) != 4 for row in t) or t[3] != [0, 0, 0, 1]:
                raise ValueError("extrinsics must be a homogeneous 4x4 transform")
            r = [row[:3] for row in t[:3]]
            for i in range(3):
                for j in range(3):
                    if abs(sum(r[i][a]*r[j][a] for a in range(3)) - (i == j)) > 1e-4:
                        raise ValueError("rotation must be orthogonal")
            det = sum(r[0][i]*(r[1][(i+1)%3]*r[2][(i+2)%3]-r[1][(i+2)%3]*r[2][(i+1)%3]) for i in range(3))
            if abs(det - 1) > 1e-4:
                raise ValueError("rotation must have determinant +1")
        if self.depth_representation is not None and self.depth_axis is None:
            raise ValueError("depth_axis required for depth")
        return self


class MediaAsset(Contract):
    asset_id: Identifier
    uri: Nonempty
    media_type: Literal["rgb"] = "rgb"
    byte_size: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    channels: Literal[3] = 3
    encoding: Literal["PNG", "JPEG"]
    scene_id: Identifier
    episode_id: str | None = None
    frame_id: str | None = None
    timestamp_ns: int | None = Field(default=None, ge=0)
    spatial_context_id: Identifier
    source_uri: Nonempty
    license_id: Nonempty
    split: Literal["train", "validation", "test"] = "test"


class Annotation(Contract):
    annotation_id: Identifier
    asset_id: Identifier
    object_id: Nonempty
    annotation_type: Literal["bbox_2d"] = "bbox_2d"
    label: Nonempty
    bbox_xyxy: tuple[float, float, float, float]
    coordinate_frame_id: str = "image"
    confidence: Probability
    producer_type: Literal["simulator", "model", "human", "fixture"]
    review_status: Literal["accepted", "needs_human_review", "fixture"]
    input_annotation_ids: list[str] = Field(default_factory=list)

    @field_validator("bbox_xyxy")
    @classmethod
    def box(cls, v):
        if not all(math.isfinite(x) for x in v) or not (0 <= v[0] < v[2] and 0 <= v[1] < v[3]):
            raise ValueError("bbox must have positive area and nonnegative finite coordinates")
        return v


class Evidence(Contract):
    evidence_id: Identifier
    claim_type: Literal["relative_position_2d"] = "relative_position_2d"
    asset_refs: list[str] = Field(min_length=1, max_length=1)
    annotation_refs: list[str] = Field(min_length=2, max_length=2)
    axis: Literal["x", "y"]
    measurement: float
    margin_px: float = Field(gt=0)
    relation: Literal["left", "right", "above", "below"]
    derivation: Literal["bbox_center_delta/v1"] = "bbox_center_delta/v1"
    confidence: Probability
    visible_asset_ref: str | None = None


class TemplateEvidence(Contract):
    """Evidence for an executable legacy template, kept separate from geometric claims."""
    evidence_id: Identifier
    claim_type: Literal['template'] = 'template'
    asset_refs: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    template_id: Identifier
    derivation: Nonempty
    fields: dict[str, JsonValue] = Field(default_factory=dict)
    confidence: Probability = 1.0


class SourceRecord(Contract):
    record_id: Identifier
    format: Literal['template_entities','official_qa','capture']
    asset_refs: list[str] = Field(min_length=1)
    source_uri: Nonempty
    review_status: Literal['accepted','needs_human_review','fixture']
    data: dict[str,JsonValue]


class ModelEvidence(Contract):
    """Read historical rejected experiments only; current gates reject this as GT."""
    evidence_id: Identifier
    claim_type: Literal['model_review'] = 'model_review'
    asset_refs: list[str] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    original_item_id: Identifier
    review_file_id: Identifier
    review_status: Literal['model_reviewed'] = 'model_reviewed'


class PublicMetadata(Contract):
    language: Literal["zh-CN", "en"] = "zh-CN"


class VisibleEvalItem(Contract):
    contract_version: Literal["benchclaw.visible-eval-item/v1"] = "benchclaw.visible-eval-item/v1"
    item_id: Identifier
    prompt: Nonempty
    media_refs: list[str] = Field(min_length=1)
    answer_type: Literal['single_choice','multi_choice','interval','ordering','numeric','json','text'] = "single_choice"
    choices: JsonValue = {}
    public_metadata: PublicMetadata = Field(default_factory=PublicMetadata)

    @field_validator("choices")
    @classmethod
    def options(cls, v):
        if not isinstance(v,(dict,list,str,int,float,bool)) or v is None:
            raise ValueError("choices must be JSON data")
        return v

    @model_validator(mode='after')
    def choice_contract(self):
        if self.answer_type in {'single_choice','multi_choice','interval'}:
            if not isinstance(self.choices,dict) or len(self.choices)<2 or len({str(x).strip().casefold() for x in self.choices.values()})!=len(self.choices):
                raise ValueError('Choice answers require at least two distinct options')
            if any(not re.fullmatch('[A-Z]',str(k)) or self.choices[k] is None for k in self.choices):
                raise ValueError('Choice keys must be uppercase letters with nonnull values')
        return self


class AnswerRecord(Contract):
    contract_version: Literal["benchclaw.answer-record/v1"] = "benchclaw.answer-record/v1"
    item_id: Identifier
    gold: JsonValue
    rubric_id: Nonempty = "choice_exact/v1"
    template_id: Identifier = 'bbox_center_2d'
    capability_ids: list[str] = Field(default_factory=list)
    metric_parameters: dict[str,JsonValue] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(min_length=1)
    choice_semantics: dict[str, str] = Field(default_factory=dict)


class DataFile(Contract):
    file_id: Identifier
    uri: Nonempty
    kind: Literal['depth','mask','pose','action','state','pointcloud','metadata','usage']
    byte_size: int = Field(gt=0)
    source_uri: Nonempty
    original_uri: str | None = None


class Bundle(Contract):
    assets: list[MediaAsset] = Field(default_factory=list)
    contexts: list[SpatialContext] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    evidence: list[Evidence | TemplateEvidence | ModelEvidence] = Field(default_factory=list)
    visible: list[VisibleEvalItem] = Field(default_factory=list)
    answers: list[AnswerRecord] = Field(default_factory=list)
    records: list[SourceRecord] = Field(default_factory=list)
    files: list[DataFile] = Field(default_factory=list)


class WorkResult(Contract):
    status: Literal["succeeded", "failed_retryable", "failed_final", "quarantined"]
    bundle: Bundle | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)
    failure: Failure | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "succeeded" and (self.failure or self.bundle is None or any(i.severity in {"error", "fatal"} for i in self.issues)):
            raise ValueError("success requires validated data and no errors")
        if self.status.startswith("failed") and self.failure is None:
            raise ValueError("failure details required")
        return self


class PluginDescriptor(Contract):
    plugin_id: str
    version: str = "0.1.0"
    kind: Literal["source", "annotator", "evidence", "synthesizer", "validator", "evaluator"]
    resources: Resources = Field(default_factory=Resources)
    description: str


class HealthResult(Contract):
    ready: bool
    code: str = "READY"
    message: str = ""


class Prediction(Contract):
    item_id: Identifier
    prediction: str | None
    status: Literal["succeeded", "failed"] = "succeeded"
    error_code: str | None = None
    model_id: str
    endpoint: str
    requested_at: str
    raw_response: JsonValue = None

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "succeeded" and not self.prediction:
            raise ValueError("successful prediction cannot be empty")
        if self.status == "failed" and not self.error_code:
            raise ValueError("failed prediction needs error_code")
        return self
