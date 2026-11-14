"""Harness-facing production capabilities."""
from . import data, evaluation, research
from .capture_adapter import adapt_capture
from .spatial_learning.registry import catalog as spatial_catalog
from .spatial_learning.generation import generate as spatial_generate
from .spatial_learning.evaluation import evaluate as spatial_evaluate
from .spatial_learning.curriculum import curriculum
from .spatial_learning.training import train as spatial_train
from .spatial_learning.monitor import monitor as training_monitor
from .spatial_learning.export import export as spatial_export
from .spatial_learning.experiments import experiment as spatial_experiment
from .pipelines.catalog import catalog as pipeline_catalog
from .pipelines.planner import plan as pipeline_plan
from .pipelines.runner import pipeline_run, status as pipeline_status
from .pipelines.artifact_graph import inspect as pipeline_artifacts
from .pipelines.repair import repair_plan as pipeline_repair_plan
from .pipelines.evaluation import evaluate as pipeline_evaluate
from .stage_review import call as stage_review

OPERATIONS={
 'stage_review':stage_review,
 'pipeline_catalog':pipeline_catalog,'pipeline_plan':pipeline_plan,
 'pipeline_run':pipeline_run,'pipeline_status':pipeline_status,
 'pipeline_artifacts':pipeline_artifacts,'pipeline_repair_plan':pipeline_repair_plan,
 'pipeline_evaluate':pipeline_evaluate,
 'spatial_catalog':spatial_catalog,'spatial_generate':spatial_generate,'spatial_evaluate':spatial_evaluate,
 'curriculum':curriculum,'spatial_train':spatial_train,'training_monitor':training_monitor,
 'spatial_export':spatial_export,
 'spatial_experiment':spatial_experiment,
 'adapt_capture':adapt_capture,
 'acquire':data.acquire,'normalize':data.normalize,'clean':data.clean,
 'literature':research.literature,'research_review':research.review,'design':research.design,'usage':research.usage,
 'score':evaluation.evaluate,'model_eval':evaluation.model_eval,'baselines':evaluation.baselines,
 'package':evaluation.package,'report':evaluation.report,
}
