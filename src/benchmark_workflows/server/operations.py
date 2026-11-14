"""Harness-facing production capabilities."""
from benchmark_workflows.server.source_acquisition import preparation as data
from benchmark_workflows.server.assessment_planning import research
from benchmark_workflows.server.scoring import reports as evaluation
from benchmark_workflows.server.source_acquisition.capture_adapter import adapt_capture
from benchmark_workflows.server.assessment_planning.catalog import catalog as pipeline_catalog
from benchmark_workflows.server.assessment_planning.planner import plan as pipeline_plan
from benchmark_workflows.server.pipelines.runner import pipeline_run
from benchmark_workflows.server.pipelines.runner import status as pipeline_status
from benchmark_workflows.server.pipelines.artifact_graph import inspect as pipeline_artifacts
from benchmark_workflows.server.pipelines.repair import repair_plan as pipeline_repair_plan
from benchmark_workflows.server.scoring.protocol_scores import evaluate as pipeline_evaluate
from benchmark_workflows.server.pipelines.stage_review import call as stage_review

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
