"""Batch access to the original VLM→YOLOE→SAM3→DA3 annotation chain."""
from __future__ import annotations
import os
import subprocess
import urllib.parse
from pathlib import Path
from .artifacts import VENDOR, read, rows, write, jsonl, run


def annotate(args,directory,config):
    services=config.get('services',{})
    required=('llm_local','yoloe','sam3','depthanything3')
    missing=[name for name in required if not services.get(name,{}).get('url')]
    if missing:raise ValueError(f'Configure services for the annotation chain: {missing}')
    env={'BENCHCLAW_ROOT':str(VENDOR),'LLM_BASE_URL':services['llm_local']['url'],
         'LLM_LOCAL_BASE_URL':services['llm_local']['url'],
         'LLM_MODEL_ID':services['llm_local'].get('model',''),'LLM_LOCAL_MODEL':services['llm_local'].get('model','')}
    if not env['LLM_MODEL_ID']:raise ValueError('Configure services.llm_local.model for visual category proposals')
    # URLs are configured on every original client, including non-default schemes/ports.
    for name,prefix in [('sam3','SAM3'),('yoloe','YOLOE'),('depthanything3','DEPTHANYTHING3')]:
        env[prefix+'_BASE_URL']=services[name]['url']
    if services['llm_local'].get('token_env'):
        env['BENCHFORGE_ANNOTATION_TOKEN']=os.environ[services['llm_local']['token_env']]
    records=rows(args['input']);output=[];review=[]
    script=VENDOR/'annotation-tool/default-annotation/run_image_to_semantic_depth.py'
    for i,row in enumerate(records):
        if row.get('provenance',{}).get('kind')=='simulation' and not args.get('annotate_simulation',False):
            output.append(row);continue
        media=row.get('media',[])
        if not media:review.append({'id':row['id'],'reason':'no_media'});continue
        for j,image in enumerate(media):
            out=directory/f'annotations/{i:06d}_{j}'
            argv=['--image',image,'--out-dir',out,'--max-vlm-terms',args.get('max_terms',20)]
            if args.get('hint'):argv+=['--user-hint',args['hint']]
            try:
                run(script,argv,directory/f'logs/{i:06d}_{j}',config=config.get('annotation',{}),env=env,
                    timeout=args.get('timeout_seconds',1800))
                result=read(out/'result.json')
                candidate={'id':f"{row['id']}_{j}",'source_id':row['id'],'media':[image],
                    'provenance':{'kind':'prediction','path':str(out/'result.json')},
                    'candidate_annotation':result,'official_record':row,'review_required':True}
                output.append(candidate)
                review.append({'id':candidate['id'],'reason':'model_predictions_require_independent_authority','candidate':str(out/'result.json')})
            except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
                review.append({'id':row['id'],'image':image,'reason':'annotation_failed','error':str(exc)})
    jsonl(directory/'annotations.jsonl',output);jsonl(directory/'review_queue.jsonl',review)
    return {'annotations':str(directory/'annotations.jsonl'),'review_queue':str(directory/'review_queue.jsonl'),
            'records':len(output),'review':len(review),'gt_written':False,
            'status':'incomplete' if any(r['reason']=='annotation_failed' for r in review) else 'completed_candidates'}
