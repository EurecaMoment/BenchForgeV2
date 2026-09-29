"""Normalize source text once while preserving source records and filter decisions."""
import copy
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .domain import HarnessError


def clean_bundle(ctx,bundle):
    mode=ctx.spec.cleaning
    if mode=='none':return bundle
    locations=[];texts=[]
    for ri,record in enumerate(bundle.records):
        if record.format=='template_entities':
            for oi,obj in enumerate(record.data['entities']['objects']):
                locations.append((ri,oi));texts.append(obj['category'])
        elif record.format=='official_qa':
            if not 1<=len(record.data['prompt'])<=20000:
                raise HarnessError('OFFICIAL_TEXT_LENGTH',record.record_id)
    cleaned=[re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>','',x))).strip() for x in texts]
    if mode=='data_juicer' and texts:
        request=ctx.output_dir/'cleaning_input.json';result=ctx.output_dir/'cleaning_output.json'
        request.write_text(json.dumps(texts))
        python=os.environ.get('BENCHFORGE_DATA_JUICER_PYTHON',sys.executable)
        with (ctx.output_dir/'cleaning.log').open('w') as log:
            process=subprocess.run([python,str(Path(__file__).with_name('cleaning_worker.py')),str(request),str(result)],stdout=log,stderr=log,timeout=min(600,ctx.spec.retry.timeout_seconds-10))
        if process.returncode:raise HarnessError('CLEANING_EXIT',(ctx.output_dir/'cleaning.log').read_text()[-1200:])
        if (ctx.output_dir/'cleaning.log').stat().st_size==0:(ctx.output_dir/'cleaning.log').unlink()
        output=json.loads(result.read_text());cleaned=output['texts']
        if len(cleaned)!=len(texts) or not all(output['keep']):raise HarnessError('CLEANING_FILTER','Declared evidence text was rejected; review the source instead of silently dropping it')
    if any(not 1<=len(x)<=20000 for x in cleaned):raise HarnessError('CLEANING_TEXT','Empty or overlong source text')
    records=[r.model_copy(update={'data':copy.deepcopy(r.data)}) for r in bundle.records]
    for (ri,oi),original,text in zip(locations,texts,cleaned):
        if text!=original:
            records[ri].data['entities']['objects'][oi]['category']=text
            records[ri].data.setdefault('cleaning_changes',[]).append({'object_index':oi,'original':original,'cleaned':text,'method':mode})
    (ctx.output_dir/'cleaning_report.json').write_text(json.dumps({'mode':mode,'examined_texts':len(texts),'changed':sum(a!=b for a,b in zip(texts,cleaned)),'official_prompts_preserved':True}))
    return bundle.model_copy(update={'records':records})
