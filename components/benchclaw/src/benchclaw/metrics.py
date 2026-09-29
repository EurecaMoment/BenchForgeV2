"""Small, explicit metric registry shared by online evaluation and exported scoring."""
import json
import math
import re


def normalized(value):
    return re.sub(r'\s+',' ',str(value).strip()).casefold()


def parsed(value):
    if not isinstance(value,str):
        return value
    text=value.strip()
    if text.startswith('```') and text.endswith('```'):
        text=re.sub(r'^```(?:json)?\s*','',text)[:-3].strip()
    try:
        return json.loads(text)
    except (ValueError,TypeError):
        return text


def sequence(value):
    value=parsed(value)
    return [normalized(x) for x in value] if isinstance(value,list) else [normalized(x) for x in re.split(r'[,，;；>\s]+',str(value)) if x]


def score_answer(gold,pred,rubric,parameters=None):
    if rubric in {'choice_exact/v1','exact_match','accuracy','normalized_exact'}:
        return float(normalized(gold)==normalized(pred))
    if rubric in {'set_exact_match','macro_f1','set_exact_match + macro_f1'}:
        g,p=set(sequence(gold)),set(sequence(pred))
        if rubric!='macro_f1':
            return float(g==p)
        return 2*len(g&p)/(len(g)+len(p)) if g or p else 1.0
    if rubric=='ordered_list_pairwise_accuracy':
        g,p=sequence(gold),sequence(pred)
        if len(set(p))!=len(p):
            return 0.0
        if len(g)<2:
            return float(g==p)
        position={v:i for i,v in enumerate(p)}
        pairs=[(a,b) for i,a in enumerate(g) for b in g[i+1:]]
        return sum(a in position and b in position and position[a]<position[b] for a,b in pairs)/len(pairs)
    if rubric in {'numeric_exact','tolerance_accuracy'}:
        try:
            g,p=float(gold),float(parsed(pred))
            tolerance=(parameters or {}).get('tolerance') or 0
            if not isinstance(tolerance,(int,float)) or not math.isfinite(tolerance) or tolerance<0:
                raise ValueError('Invalid numeric tolerance')
            return float(math.isfinite(g) and math.isfinite(p) and abs(g-p)<=tolerance)
        except (TypeError,ValueError):
            return 0.0
    if rubric=='json_field_accuracy':
        g,p=parsed(gold),parsed(pred)
        def flatten(v,prefix=''):
            if isinstance(v,dict):
                return {a:b for k,x in v.items() for a,b in flatten(x,prefix+'/'+str(k)).items()}
            if isinstance(v,list):
                return {a:b for i,x in enumerate(v) for a,b in flatten(x,prefix+'/'+str(i)).items()}
            return {prefix:normalized(v)}
        if type(g)!=type(p):
            return 0.0
        gf,pf=flatten(g),flatten(p)
        return sum(pf.get(k)==v for k,v in gf.items())/len(gf) if gf else float(not pf)
    raise ValueError('Unsupported rubric: '+rubric)


def metric_details(gold,pred,rubric,parameters=None):
    values={'score':score_answer(gold,pred,rubric,parameters)}
    if rubric in {'set_exact_match','macro_f1','set_exact_match + macro_f1'}:
        values.update(set_exact_match=score_answer(gold,pred,'set_exact_match'),f1=score_answer(gold,pred,'macro_f1'))
    if rubric in {'numeric_exact','tolerance_accuracy'}:
        try:
            error=abs(float(gold)-float(parsed(pred)))
            if math.isfinite(error):values['absolute_error']=error
        except (TypeError,ValueError):pass
    return values
