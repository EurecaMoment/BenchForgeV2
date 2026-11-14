import base64
import json
from pathlib import Path
import time
import urllib.request
from service_access.runtime_config import environment_value
from service_access.request_context import RunContext
from service_access.request_context import check_cancelled
def _json_text(value):
    value = value.strip()
    if value.startswith('```'):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines = lines[:-1]
        value = '\n'.join(lines).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find('{')
        if start < 0:
            raise
        depth = 0
        quoted = False
        escape = False
        for index in range(start, len(value)):
            char = value[index]
            if quoted:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(value[start:index + 1])
        raise


def _parse_saved(saved, path):
    try:
        return _json_text(saved['content'])
    except json.JSONDecodeError as error:
        path.parent.joinpath('parse_error.json').write_text(
            json.dumps(
                {
                    'error': 'JSONDecodeError',
                    'detail': str(error),
                    'response_file': path.name,
                },
                indent=2,
            ),
            encoding='utf8',
        )
        raise


def model_request_headers():
    headers = {'Content-Type': 'application/json'}
    name = environment_value('BENCHFORGE_MODEL_API_KEY_ENV')
    token = environment_value(name) if name else None
    if name and not token:
        raise ValueError(f'The scene model token_env references unset variable {name}')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def completion(
    prompt,
    trace_dir,
    images=(),
    max_tokens=10000,
    *,
    bounded_review=False,
    stop=None,
    context=None,
):
    """Retry malformed JSON without replaying a poisoned completed-response cache."""
    for attempt in range(3):
        check_cancelled(stop, 'model request')
        try:
            return _completion_once(
                prompt,
                trace_dir,
                images,
                max_tokens,
                bounded_review=bounded_review,
                stop=stop,
                context=context,
            )
        except json.JSONDecodeError:
            if attempt == 2:
                raise


def _completion_once(
    prompt,
    trace_dir,
    images,
    max_tokens,
    *,
    bounded_review=False,
    stop=None,
    context=None,
):
    check_cancelled(stop, 'model request')
    trace_dir=Path(trace_dir); trace_dir.mkdir(parents=True,exist_ok=True)
    previous=list(trace_dir.rglob('response.json'))
    invalid_json=False
    for path in sorted(previous,key=lambda p:p.stat().st_mtime,reverse=True):
        check_cancelled(stop, 'model response recovery')
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
        check_cancelled(stop, 'model image preparation')
        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()}})
    thinking_budget=min(8192,max(1024,max_tokens//2))
    model_id=environment_value('BENCHFORGE_MODEL_ID')
    if not model_id:
        raise ValueError('BENCHFORGE_MODEL_ID is required for model-assisted scene review or planning')
    model_url=environment_value('BENCHFORGE_MODEL_URL')
    if not model_url:
        raise ValueError('BENCHFORGE_MODEL_URL is required for model-assisted scene review or planning')
    body={'model':model_id,'messages':[{'role':'user','content':content}],
          'reasoning_effort':'xhigh','max_tokens':max(4096,max_tokens+thinking_budget),'thinking_token_budget':thinking_budget,'temperature':.7,'top_p':.9,
          'chat_template_kwargs':{'enable_thinking':True,'preserve_thinking':True},'stream':True,'stream_options':{'include_usage':True}}
    if bounded_review:
        # Structured observation already has an explicit checklist. Bound latency
        # without changing its acceptance criteria or the running model service.
        body.update(reasoning_effort='none', max_tokens=max_tokens, temperature=.2,
                    chat_template_kwargs={'enable_thinking':False})
        body.pop('thinking_token_budget',None)
    run_context = RunContext.from_record(context)
    request_record = {
        **body,
        'messages':[{'role':'user','content':prompt}],
        'image_files':[str(p) for p in images],
    }
    if run_context:
        request_record['run_context'] = run_context.to_dict()
    (trace_dir/'request.json').write_text(json.dumps(request_record,ensure_ascii=False,indent=2),encoding='utf8')
    base=model_url.rstrip('/')
    url=base if base.endswith('/chat/completions') else base+'/chat/completions'
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers=model_request_headers())
    pieces=[];thinking=[];usage={};finish=None;done=False;start=time.time()
    last_progress=0;characters=0;error=None
    scene_review=bounded_review and (trace_dir.name=='scene_review' or any(p.name=='scene_review' for p in trace_dir.parents))
    try:
        with (trace_dir/'stream.jsonl').open('w',encoding='utf8') as trace, urllib.request.urlopen(request,timeout=90 if bounded_review else 600) as response:
            for raw in response:
                check_cancelled(stop, 'model response stream')
                now=time.time()
                if now-start>(420 if bounded_review else 900): raise TimeoutError('model wall-time budget exceeded')
                line=raw.decode().strip()
                if not line.startswith('data:'): continue
                data=line[5:].strip()
                if data=='[DONE]': done=True; break
                event=json.loads(data)
                trace.write(json.dumps(event,ensure_ascii=False)+'\n');trace.flush()
                if event.get('usage'): usage=event['usage']
                for choice in event.get('choices',[]):
                    delta=choice.get('delta',{})
                    part=delta.get('content') or '';pieces.append(part);characters+=len(part)
                    thinking.append(delta.get('reasoning_content') or delta.get('reasoning') or '')
                    if choice.get('finish_reason'): finish=choice['finish_reason']
                if scene_review:
                    if now-last_progress>=2:
                        from service_access.progress import record_progress
                        record_progress(trace_dir,'scene_review',generated_characters=characters,elapsed_seconds=round(now-start),message='正在逐图审阅')
                        last_progress=now
    except Exception as exc:
        error=exc
    finally:
        (trace_dir/'response.json').write_text(json.dumps({'model':body['model'],'content':''.join(pieces),'reasoning':''.join(thinking),'usage':usage,'finish_reason':finish,'done':done,'seconds':time.time()-start,'error':type(error).__name__ if error else None},ensure_ascii=False,indent=2),encoding='utf8')
    if error:raise error
    text=''.join(pieces)
    if not done or finish!='stop' or not text:
        raise ValueError(f'model response incomplete: done={done}, finish_reason={finish}, completion_tokens={usage.get("completion_tokens")}, max_tokens={body["max_tokens"]}. If length-limited, return compact JSON or field edits when the task accepts them.')
    return _parse_saved({'content':text},trace_dir/'response.json')
