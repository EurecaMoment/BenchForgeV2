"""Declarative deterministic templates for dataset-specific and temporal evidence.

Recipes read structured fields and never call a model. Each binding specifies a
visible anchor and a deterministic program. Missing evidence disables that item.
"""
import argparse
import json
import math
from pathlib import Path


def pointer(value,path):
    if path and not path.startswith('/'):raise ValueError('Recipe inputs use RFC 6901 JSON pointers')
    for part in path.strip('/').split('/') if path else []:
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


def compute(program,record):
    op=program['op']
    values=[pointer(record,p) for p in program.get('inputs',[])]
    if op=='field':return values[0]
    if op=='count':return len(values[0])
    if op=='count_where':return sum(pointer(v,program['field'])==program['value'] for v in values[0])
    if op=='compare':
        a,b=values
        if isinstance(a,(int,float)) and isinstance(b,(int,float)):
            if not math.isfinite(a) or not math.isfinite(b) or (program.get('relation','lt')!='eq' and abs(a-b)<=program.get('margin',0)):raise ValueError('ambiguous/nonfinite comparison')
        relation=program.get('relation','lt')
        if relation not in ('lt','gt','eq'):raise ValueError('Unsupported relation')
        truth={'lt':lambda:a<b,'gt':lambda:a>b,'eq':lambda:a==b}[relation]()
        return program.get('true','A') if truth else program.get('false','B')
    if op=='difference':return values[1]-values[0]
    if op=='distance':
        if len(values[0])!=len(values[1]):raise ValueError('Coordinate dimension mismatch')
        return math.sqrt(sum((a-b)**2 for a,b in zip(*values)))
    if op=='order':
        labels=program['labels']
        if len(labels)!=len(values):raise ValueError('Order label count mismatch')
        ordered=sorted(zip(labels,values),key=lambda v:v[1],reverse=program.get('descending',False))
        if any(abs(a[1]-b[1])<=program.get('margin',0) for a,b in zip(ordered,ordered[1:])):raise ValueError('Ordering tie')
        return [p[0] for p in ordered]
    if op=='argmax' or op=='argmin':
        best=(max if op=='argmax' else min)(values)
        if values.count(best)!=1:raise ValueError('Extremum tie')
        return program['labels'][values.index(best)]
    if op=='lookup':return program['mapping'][str(values[0])]
    if op=='interval':
        for interval in program['intervals']:
            if interval['min']<=values[0]<interval['max']:return interval['label']
        raise ValueError('No matching interval')
    raise ValueError(f'Unknown answer program op: {op}')


def generate(bundle,evidence,templates,limit=0):
    out=[];rejected=[]
    for record in evidence:
        origin=record.get('provenance',{}).get('kind',record.get('source_type'))
        if origin not in ('official','human','simulation','program'):raise ValueError('Recipe evidence is not authoritative')
        for template in templates:
            if template.get('status','enabled')!='enabled':continue
            try:
                if template.get('sequence_semantics') and record.get('sequence_semantics')!=template['sequence_semantics']:
                    raise ValueError('Sequence semantics mismatch')
                anchor=template['visible_anchor']
                media=pointer(record,anchor.get('media_pointer','/media'))
                if isinstance(media,str):media=[media]
                if not media:raise ValueError('Missing visible evidence')
                resolved=[]
                for path in media:
                    path=Path(path);path=path if path.is_absolute() else Path(bundle)/path
                    if not path.is_file():raise ValueError('Missing visible media')
                    resolved.append(str(path))
                if not anchor.get('description'):raise ValueError('Visible anchor explanation required')
                program=template['answer_program']
                answer=compute(program,record)
                if isinstance(answer,float) and not math.isfinite(answer):raise ValueError('Nonfinite answer')
                iid=str(record.get('id',record.get('sample_id')))+'_'+template['template_id']
                out.append({'id':iid,'item_id':iid,'question':template['question'],
                    'options':template.get('options',{}),'media':resolved,'answer':answer,
                    'answer_type':template['answer_type'],'metric_id':template['metric_id'],
                    'template_id':template['template_id'],'capability_tags':template['capability_tags'],
                    'difficulty_level':template['difficulty_level'],'tolerance':template.get('tolerance',0),
                    'source':record.get('source_name',record.get('scene','unspecified')),
                    'evidence_refs':[record.get('id')],
                    'answerability_proof':{'visible_media':resolved,'visible_anchor_type':anchor['type'],
                        'question_references_visible_anchor':True,'why_visible_anchor_is_sufficient':anchor['description'],
                        'private_gt_fields_used_for_answer':program.get('inputs',[])},
                    'metadata':{'answer_program':program,'sequence_semantics':record.get('sequence_semantics')}})
            except (KeyError,IndexError,ValueError,TypeError) as exc:
                rejected.append({'sample_id':record.get('id'),'template_id':template['template_id'],'reason':str(exc)})
            if limit and len(out)>=limit:return out,rejected
    return out,rejected


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--evidence-index',required=True)
    p.add_argument('--out',required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--template-id',default='');p.add_argument('--filtered-output',default='')
    a=p.parse_args()
    def load(path):return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]
    templates=load(Path(a.bundle)/'template_manifest.jsonl')
    if a.template_id:templates=[t for t in templates if t['template_id']==a.template_id]
    out,rejected=generate(a.bundle,load(a.evidence_index),templates,a.limit)
    Path(a.out).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in out),encoding='utf-8')
    if a.filtered_output:Path(a.filtered_output).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rejected),encoding='utf-8')
    print(json.dumps({'items':len(out),'rejected':len(rejected)}))
    raise SystemExit(0 if out else 1)
