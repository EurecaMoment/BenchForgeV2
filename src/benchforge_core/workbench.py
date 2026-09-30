"""Harness-facing production capabilities. No fixed phase scheduler."""
from . import data, evaluation, production, research, annotation
from .backends import backend
from .capture_adapter import adapt_capture
from .artifacts import read
from .spatial_learning.registry import catalog as spatial_catalog
from .spatial_learning.generation import generate as spatial_generate
from .spatial_learning.evaluation import evaluate as spatial_evaluate
from .spatial_learning.curriculum import curriculum
from .spatial_learning.training import train as spatial_train
from .spatial_learning.monitor import monitor as training_monitor
from .spatial_learning.export import export as spatial_export
from .spatial_learning.experiments import experiment as spatial_experiment
from pathlib import Path
import re

OPERATIONS={
 'spatial_catalog':spatial_catalog,'spatial_generate':spatial_generate,'spatial_evaluate':spatial_evaluate,
 'curriculum':curriculum,'spatial_train':spatial_train,'training_monitor':training_monitor,
 'spatial_export':spatial_export,
 'spatial_experiment':spatial_experiment,
 'backend':backend,
 'adapt_capture':adapt_capture,
 'acquire':data.acquire,'normalize':data.normalize,'clean':data.clean,'annotate':annotation.annotate,
 'literature':research.literature,'research_review':research.review,'design':research.design,'usage':research.usage,
 'kinship':production.kinship,'images':production.images,'compile':production.compile_bundle,
 'synthesize':production.synthesize,'screen':production.screen,'diagnose':production.diagnose,
 'score':evaluation.evaluate,'model_eval':evaluation.model_eval,'baselines':evaluation.baselines,
 'package':evaluation.package,'report':evaluation.report,
}


def execute(tool,args,directory,config):
    if tool=='method':
        methods=read(Path(__file__).with_name('knowledge')/'methods.json')
        query=args.get('query','').casefold()
        tokens=re.findall(r'[\w]+',query)
        def relevance(m):
            title=(m['id']+' '+m['title']).casefold()
            body=m['body'].casefold()
            return sum(5*(t in title)+(t in body) for t in tokens)
        matches=sorted((m for m in methods if not tokens or relevance(m)),key=relevance,reverse=True)
        return {'methods':matches[:args.get('limit',3)],'total':len(matches),
                'note':'Domain methods are reference instructions. Use the listed callable capabilities; no fixed stage sequence or child-agent requirement.'}
    return OPERATIONS[tool](args,directory,config)
