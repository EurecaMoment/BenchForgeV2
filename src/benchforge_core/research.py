"""Traceable literature retrieval and capability design contracts."""
from __future__ import annotations
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from .artifacts import read, rows, write, jsonl, unique


def literature(args,directory,config):
    candidates=list(args.get('sources',[]))
    if args.get('query'):
        url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode({'search_query':args['query'],'max_results':args.get('limit',5)})
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'BenchForge/0.2'}),timeout=60) as response:
            document=response.read()
        (directory/'search.xml').write_bytes(document)
        ns={'a':'http://www.w3.org/2005/Atom'}
        for entry in ET.fromstring(document).findall('a:entry',ns):
            candidates.append({'id':entry.findtext('a:id',namespaces=ns).rsplit('/',1)[-1],
                'title':' '.join(entry.findtext('a:title',namespaces=ns).split()),
                'url':entry.findtext('a:id',namespaces=ns).replace('/abs/','/pdf/'),
                'authors':[a.findtext('a:name',namespaces=ns) for a in entry.findall('a:author',ns)],
                'published':entry.findtext('a:published',namespaces=ns)})
    if not candidates:raise ValueError('Supply sources [{id,title,url}] or an arXiv query')
    index=[]
    for i,source in enumerate(candidates):
        record={**source,'reading_status':'unread'}
        try:
            request=urllib.request.Request(source['url'],headers={'User-Agent':'BenchForge/0.2'})
            with urllib.request.urlopen(request,timeout=90) as response:
                payload=response.read();record['http_status']=response.status
            is_pdf=payload.startswith(b'%PDF')
            path=directory/f'papers/paper_{i:03d}{".pdf" if is_pdf else ".html"}'
            path.parent.mkdir(exist_ok=True);path.write_bytes(payload)
            if is_pdf:
                try:from pypdf import PdfReader
                except ImportError:raise ValueError('Install benchforge[research] to extract PDFs')
                text='\n'.join(f'\n[Page {j+1}]\n'+(page.extract_text() or '') for j,page in enumerate(PdfReader(path).pages))
            else:
                text=payload.decode('utf-8',errors='replace')
                text=re.sub(r'(?is)<(script|style).*?</\1>','',text)
                text=html.unescape(re.sub(r'<[^>]+>',' ',text))
                text=re.sub(r'[ \t]+',' ',text)
            if len(text.strip())<200:raise ValueError('Insufficient extracted full text')
            extracted=directory/f'text/paper_{i:03d}.txt';extracted.parent.mkdir(exist_ok=True)
            extracted.write_text(text,encoding='utf-8')
            record.update(access_status='downloaded',file=str(path),text=str(extracted),bytes=len(payload))
        except (OSError,ValueError) as exc:record.update(access_status='failed',error=str(exc))
        index.append(record)
    jsonl(directory/'literature_index.jsonl',index)
    return {'index':str(directory/'literature_index.jsonl'),'downloaded':sum(r['access_status']=='downloaded' for r in index),
            'failed':sum(r['access_status']=='failed' for r in index),
            'next':'Read extracted full text through host file tools; submit claims and exact supporting passages to research_review. Downloading does not establish reading.'}


def review(args,directory,config):
    papers=unique([{**r,'id':str(r['id'])} for r in rows(args['index'])])
    claims=args['claims'] if isinstance(args['claims'],list) else rows(args['claims'])
    audited=[];failures=[]
    for claim in claims:
        source=papers.get(str(claim.get('paper_id')))
        if not source or source.get('access_status')!='downloaded':
            failures.append({'claim':claim,'reason':'source_not_downloaded'});continue
        text=Path(source['text']).read_text(encoding='utf-8')
        quote=claim.get('quote','').strip()
        if len(quote)<30 or ' '.join(quote.split()) not in ' '.join(text.split()):
            failures.append({'claim':claim,'reason':'quote_not_found_in_source'});continue
        audited.append({**claim,'source_text':source['text'],'citation_status':'passage_present',
                        'semantic_entailment':'human_or_host_reasoning_required'})
    jsonl(directory/'citation_audit.jsonl',audited);jsonl(directory/'invalid_citations.jsonl',failures)
    text='# Literature review\n\n'+ '\n\n'.join(f"{c['claim']} [{c['paper_id']}]\n\n> {c['quote']}" for c in audited)
    (directory/'review.md').write_text(text,encoding='utf-8')
    return {'review':str(directory/'review.md'),'claims':len(audited),'rejected':len(failures),
            'status':'incomplete' if failures or not audited else 'source_passages_verified'}


def design(args,directory,config):
    spec=args['spec'] if isinstance(args['spec'],dict) else read(args['spec'])
    spec=dict(spec)
    for key in ('capabilities','sources','templates','metrics'):
        if isinstance(spec.get(key),dict):
            spec[key]=[{**value,'id':name} for name,value in spec[key].items()]
    required=('objective','capabilities','sources','templates','metrics')
    missing=[k for k in required if not spec.get(k)]
    if missing:raise ValueError(f'Design missing {missing}')
    caps=unique(spec['capabilities']);templates=unique(spec['templates']);metrics=unique(spec['metrics'])
    source_ids=set(unique(spec['sources']))
    trace=[]
    for tid,t in templates.items():
        if not t.get('capabilities') or not set(t['capabilities'])<=set(caps):raise ValueError(f'Unknown/missing capabilities for {tid}')
        if t.get('metric') not in metrics:raise ValueError(f'Metric binding missing for {tid}')
        if not t.get('sources') or not set(t['sources'])<=source_ids:raise ValueError(f'Source binding missing for {tid}')
        if not t.get('answer_rule') or not t.get('visible_anchor'):raise ValueError(f'Answer rule / model-visible evidence missing for {tid}')
        trace.append({'template':tid,'capabilities':t['capabilities'],'metric':t['metric'],'sources':t['sources']})
    write(directory/'benchmark_spec.json',spec);jsonl(directory/'traceability.jsonl',trace)
    import csv
    with (directory/'q_matrix_seed.csv').open('w',encoding='utf-8',newline='') as out:
        writer=csv.writer(out);writer.writerow(['template_id',*caps])
        for tid,t in templates.items():writer.writerow([tid,*[int(c in t['capabilities']) for c in caps]])
    (directory/'benchmark_draft.md').write_text('# Benchmark design\n\n'+spec['objective']+'\n\n'+
        '\n'.join(f"- {c['id']}: {c.get('description','')}" for c in caps.values())+
        '\n\nSource/metric/template bindings are in benchmark_spec.json. Capability claims still require empirical evaluation.\n',encoding='utf-8')
    return {'spec':str(directory/'benchmark_spec.json'),'q_matrix':str(directory/'q_matrix_seed.csv'),
            'traceability':str(directory/'traceability.jsonl'),'templates':len(templates),'status':'design_validated'}


def usage(args,directory,config):
    paths=args['events'] if isinstance(args['events'],list) else [args['events']]
    records=[]
    for path in paths:
        source=read(path)
        records.extend(source.get('records',source.get('events',[])) if isinstance(source,dict) else source)
    requests={};sessions=set()
    for record in records:
        event=record.get('event',record);data=event.get('data',{})
        if event.get('sessionId'):sessions.add(event['sessionId'])
        # Preserve exact provider counters. Do not add reasoning/cache twice to total tokens.
        value=data.get('usage') or data.get('message',{}).get('usage')
        if isinstance(value,dict):
            key=(event.get('sessionId',record.get('sessionId','')),data.get('requestId') or data.get('message',{}).get('id') or str(event.get('seq')))
            requests[key]=value
    totals={}
    for value in requests.values():
        for k,v in value.items():
            if isinstance(v,(int,float)):totals[k]=totals.get(k,0)+v
    result={'sessions':sorted(sessions),'requests_with_usage':len(requests),'provider_counters':totals,
            'status':'available' if requests else 'usage_not_present','cost':'not estimated without model pricing',
            'coverage':'Only the supplied DSH event export; include descendant session events for subtree coverage.'}
    write(directory/'usage.json',result)
    return result
