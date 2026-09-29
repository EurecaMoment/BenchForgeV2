import base64
import json
import os
from pathlib import Path
import time
import urllib.request


def _json_text(value):
    value=value.strip()
    if value.startswith('```'):
        lines=value.splitlines()[1:]
        if lines and lines[-1].strip().startswith('```'):lines=lines[:-1]
        value='\n'.join(lines).strip()
    try:return json.loads(value)
    except json.JSONDecodeError:
        start=value.find('{')
        if start<0:raise
        depth=0;quoted=False;escape=False
        for index in range(start,len(value)):
            char=value[index]
            if quoted:
                if escape:escape=False
                elif char=='\\':escape=True
                elif char=='"':quoted=False
            elif char=='"':quoted=True
            elif char=='{':depth+=1
            elif char=='}':
                depth-=1
                if depth==0:return json.loads(value[start:index+1])
        raise


def completion(prompt, trace_dir, images=(), max_tokens=10000):
    """Retry malformed JSON without replaying a poisoned completed-response cache."""
    for attempt in range(3):
        try:return _completion_once(prompt,trace_dir,images,max_tokens)
        except json.JSONDecodeError:
            if attempt==2:raise


def _parse_saved(saved, path):
    try:return _json_text(saved['content'])
    except json.JSONDecodeError as error:
        (path.parent/'parse_error.json').write_text(json.dumps({'error':'JSONDecodeError','detail':str(error),'response_file':path.name},indent=2),encoding='utf8')
        raise


def _completion_once(prompt, trace_dir, images, max_tokens):
    trace_dir=Path(trace_dir); trace_dir.mkdir(parents=True,exist_ok=True)
    previous=list(trace_dir.rglob('response.json'))
    invalid_json=False
    for path in sorted(previous,key=lambda p:p.stat().st_mtime,reverse=True):
        saved=json.loads(path.read_text(encoding='utf8'))
        if saved.get('done') and saved.get('finish_reason')=='stop':
            try:return _parse_saved(saved,path)
            except json.JSONDecodeError:invalid_json=True
    if previous or (trace_dir/'request.json').exists():
        attempt=1
        while (trace_dir/f'retry_{attempt}').exists():attempt+=1
        trace_dir=trace_dir/f'retry_{attempt}';trace_dir.mkdir()
    if invalid_json:
        prompt+='\nYour previous response was not valid JSON. Return strict JSON only: double-quoted strings and keys, no single-quoted strings or trailing commas. Keep the original task criteria unchanged.'
    content=[{'type':'text','text':prompt}]
    for path in images:
        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()}})
    thinking_budget=min(8192,max(1024,max_tokens//2))
    body={'model':os.environ['SPATIALFORGE_MODEL_ID'],'messages':[{'role':'user','content':content}],
          'reasoning_effort':'xhigh','max_tokens':max(4096,max_tokens+thinking_budget),'thinking_token_budget':thinking_budget,'temperature':.7,'top_p':.9,
          'chat_template_kwargs':{'enable_thinking':True,'preserve_thinking':True},'stream':True,'stream_options':{'include_usage':True}}
    (trace_dir/'request.json').write_text(json.dumps({**body,'messages':[{'role':'user','content':prompt}], 'image_files':[str(p) for p in images]},ensure_ascii=False,indent=2),encoding='utf8')
    url=os.environ['SPATIALFORGE_MODEL_URL'].rstrip('/')+'/chat/completions'
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ.get(os.environ.get('SPATIALFORGE_MODEL_API_KEY_ENV','QWEN_RELAY_API_KEY'),'local')})
    pieces=[];thinking=[];usage={};finish=None;done=False;start=time.time()
    with (trace_dir/'stream.jsonl').open('w',encoding='utf8') as trace, urllib.request.urlopen(request,timeout=600) as response:
        for raw in response:
            if time.time()-start>900: raise TimeoutError('model wall-time budget exceeded')
            line=raw.decode().strip()
            if not line.startswith('data:'): continue
            data=line[5:].strip()
            if data=='[DONE]': done=True; break
            event=json.loads(data)
            trace.write(json.dumps(event,ensure_ascii=False)+'\n');trace.flush()
            if event.get('usage'): usage=event['usage']
            for choice in event.get('choices',[]):
                delta=choice.get('delta',{})
                pieces.append(delta.get('content') or '')
                thinking.append(delta.get('reasoning_content') or delta.get('reasoning') or '')
                if choice.get('finish_reason'): finish=choice['finish_reason']
    text=''.join(pieces)
    (trace_dir/'response.json').write_text(json.dumps({'model':body['model'],'content':text,'reasoning':''.join(thinking),'usage':usage,'finish_reason':finish,'done':done,'seconds':time.time()-start},ensure_ascii=False,indent=2),encoding='utf8')
    if not done or finish!='stop' or not text:
        raise ValueError(f'model response incomplete: done={done}, finish_reason={finish}, completion_tokens={usage.get("completion_tokens")}, max_tokens={body["max_tokens"]}. If length-limited, return compact JSON or field edits when the task accepts them.')
    return _parse_saved({'content':text},trace_dir/'response.json')
