"""Harness-facing production capabilities."""
from capabilities.data_acquisition import preparation as data
from capabilities.literature import research
from capabilities.evaluation.benchmark import reports as evaluation
from capabilities.data_acquisition.capture_adapter import adapt_capture
from pipelines.catalog import catalog as pipeline_catalog
from pipelines.benchmark.design.planner import plan as pipeline_plan
from pipelines.benchmark.execution.runner import pipeline_run
from pipelines.benchmark.execution.runner import status as pipeline_status
from pipelines.benchmark.execution.artifact_graph import inspect as pipeline_artifacts
from pipelines.benchmark.execution.repair import repair_plan as pipeline_repair_plan
from capabilities.evaluation.benchmark.protocol_scores import evaluate as pipeline_evaluate
from pipelines.benchmark.execution.stage_review import call as stage_review

OPERATIONS={
 'stage_review':stage_review,
 'pipeline_catalog':pipeline_catalog,'pipeline_plan':pipeline_plan,
 'pipeline_run':pipeline_run,'pipeline_status':pipeline_status,
 'pipeline_artifacts':pipeline_artifacts,'pipeline_repair_plan':pipeline_repair_plan,
 'pipeline_evaluate':pipeline_evaluate,
 'adapt_capture':adapt_capture,
 'acquire':data.acquire,'normalize':data.normalize,'clean':data.clean,
 'literature':research.literature,'research_review':research.review,'design':research.design,'usage':research.usage,
 'score':evaluation.evaluate,'model_eval':evaluation.model_eval,'baselines':evaluation.baselines,
 'package':evaluation.package,'report':evaluation.report,
}
