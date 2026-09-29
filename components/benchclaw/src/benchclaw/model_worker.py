"""Standalone stdlib-only model worker. Authority data must never be mounted here."""
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
try:
    from .chat_transport import generation_payload,complete
except ImportError:
    from chat_transport import generation_payload,complete


def main():
    root=Path('/model').resolve()
    if Path('/authority').exists() or os.environ.get('BENCHCLAW_DATABASE_URL'):
        raise RuntimeError('Authority isolation violated')
    roster=json.loads(Path('/out/roster.json').read_text())
    items=[]
    for file in sorted((root/'data').glob('*.jsonl')):
        items.extend(json.loads(line) for line in file.read_text().splitlines() if line)
    with Path('/out/predictions.jsonl').open('x') as output:
        for model in roster['models']:
            for item in items:
                request_time=datetime.now(timezone.utc).isoformat()
                row={'item_id':item['item_id'],'model_id':model['model_id'],'endpoint':model['endpoint'],
                     'requested_at':request_time,'status':'failed','prediction':None,'error_code':None}
                try:
                    allowed={'contract_version','producer','producer_version','created_at','item_id','prompt','media_refs','answer_type','choices','public_metadata'}
                    if set(item)-allowed:
                        raise ValueError('Unexpected visible fields')
                    choices=item['choices']
                    options='\n'.join(f'{k}: {v}' for k,v in choices.items()) if isinstance(choices,dict) else json.dumps(choices,ensure_ascii=False)
                    format_hint={'single_choice':'Reply with one choice letter.','interval':'Reply with one choice letter.',
                        'multi_choice':'Reply with a JSON array of selected choice letters.','ordering':'Reply with the ordered JSON array requested by the question.',
                        'numeric':'Reply with only the number.','json':'Reply with the requested JSON value.','text':'Reply with only the short answer requested by the question.'}[item['answer_type']]
                    content=[{'type':'text','text':item['prompt']+'\n'+options+'\n'+format_hint}]
                    for uri in item['media_refs']:
                        path=(root/uri).resolve()
                        if not path.is_relative_to(root/'media'):
                            raise ValueError('Media path escape')
                        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()}})
                    payload={**generation_payload(model),'messages':[{'role':'user','content':content}]}
                    # Request trace contains precisely what the model saw, without credential headers.
                    trace={'item_id':item['item_id'],'model_id':model['model_id'],'endpoint':model['endpoint'],'requested_at':request_time,'request':payload}
                    with Path('/out/requests.jsonl').open('a') as traces:
                        traces.write(json.dumps(trace,ensure_ascii=False)+'\n')
                    raw=complete(model,payload)
                    text=raw['choices'][0]['message']['content']
                    if not isinstance(text,str) or not text.strip():
                        raise ValueError('Empty response')
                    row.update(status='succeeded',prediction=text,raw_response=raw)
                except Exception as exc:
                    row.update(error_code=type(exc).__name__,raw_response={'error':str(exc)})
                output.write(json.dumps(row,ensure_ascii=False)+'\n')
                output.flush()


if __name__=='__main__':
    main()
