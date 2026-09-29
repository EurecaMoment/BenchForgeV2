"""Shared stdlib Chat Completions transport; never records credential headers."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener


def generation_payload(model):
    payload={'model':model['model_id'],'max_tokens':model['max_tokens'],
             'temperature':model.get('temperature',0)}
    for name in ('reasoning_effort','thinking_token_budget','top_p','top_k','min_p',
                 'presence_penalty','repetition_penalty'):
        if model.get(name) is not None:payload[name]=model[name]
    template={name:model[name] for name in ('enable_thinking','preserve_thinking') if model.get(name) is not None}
    if template:payload['chat_template_kwargs']=template
    if model.get('stream'):
        payload.update(stream=True,stream_options={'include_usage':True})
    return payload


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('Chat endpoint redirect refused')


def read_completion(response,stream=False):
    if not stream:
        raw=json.load(response)
    else:
        text=[];reasoning=[];finish=None;usage=None;metadata={};done=False
        for line in response:
            line=line.decode('utf-8').strip()
            if not line or line.startswith(':'):continue
            if not line.startswith('data:'):raise ValueError('Expected a Chat Completions SSE stream')
            data=line[5:].strip()
            if data=='[DONE]':done=True;break
            chunk=json.loads(data)
            if 'error' in chunk:raise ValueError('Chat stream returned an API error')
            for name in ('id','model','created'):
                if name in chunk:metadata[name]=chunk[name]
            if chunk.get('usage') is not None:usage=chunk['usage']
            for choice in chunk.get('choices',[]):
                if choice.get('index',0)!=0:raise ValueError('Only one completion is supported')
                delta=choice.get('delta',{})
                if delta.get('content'):text.append(delta['content'])
                thought=delta.get('reasoning_content') or delta.get('reasoning')
                if thought:reasoning.append(thought)
                if choice.get('finish_reason') is not None:finish=choice['finish_reason']
        if not done or finish is None:raise ValueError('Incomplete Chat Completions stream')
        raw={**metadata,'choices':[{'index':0,'finish_reason':finish,
              'message':{'role':'assistant','content':''.join(text),'reasoning_content':''.join(reasoning)}}],
              'usage':usage}
    choice=raw['choices'][0]
    if choice.get('finish_reason')=='length':raise ValueError('Model response was truncated')
    if choice.get('finish_reason') not in (None,'stop'):raise ValueError('Model did not finish a text answer')
    content=choice['message'].get('content')
    if not isinstance(content,str) or not content.strip():raise ValueError('Empty model response')
    return raw


def complete(model,payload):
    key=None
    try:
        headers={'Content-Type':'application/json'}
        if model.get('api_key_env'):
            key=os.environ.get(model['api_key_env'])
            if not key:raise ValueError('Missing credential environment variable: '+model['api_key_env'])
            headers['Authorization']='Bearer '+key
        request=Request(model['endpoint'],data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers,method='POST')
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=model['timeout_seconds']) as response:
            return read_completion(response,bool(payload.get('stream')))
    except Exception as exc:
        detail=exc.read(2000).decode(errors='replace') if isinstance(exc,HTTPError) else str(exc)
        if key:detail=detail.replace(key,'[REDACTED]')
        raise RuntimeError(f'{type(exc).__name__}: {detail[:2000]}') from None
