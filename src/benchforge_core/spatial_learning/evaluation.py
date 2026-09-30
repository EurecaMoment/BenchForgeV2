"""Saved-answer evaluation and interactive policy replay with program GT."""
import json
from collections import Counter,defaultdict
from pathlib import Path
from .scoring import score
from .generation import write_json
from .environments import environment


def read_rows(path):
    with Path(path).open(encoding='utf8') as handle:return [json.loads(line) for line in handle if line.strip()]


def evaluate(args,directory,config=None):
    dataset=Path(args['dataset']);partition=args.get('partition','curriculum_dev')
    questions=read_rows(dataset/partition/'questions.jsonl');authority={r['id']:r for r in read_rows(dataset/partition/'authority.jsonl')}
    predictions={r['id']:r['prediction'] for r in read_rows(args['predictions'])}
    results=[]
    for q in questions:
        truth=authority[q['id']];answer=predictions.get(q['id'])
        if q['id'] not in predictions:measured={'success':False,'score':0,'parse_ok':False,'error':'missing_prediction'}
        elif truth['scorer']=='environment':
            env=environment(truth['scene'],q['capabilities'][0],q['template_id'].split('.')[1])
            try:
                for action in answer:
                    response=env.step(action)
                    if response['done']:break
                measured={'success':env.success(),'score':float(env.success()),'parse_ok':True,'error':None if env.success() else 'environment_goal_incomplete','environment_steps':len(env.trace)}
            except (KeyError,ValueError,TypeError):measured={'success':False,'score':0,'parse_ok':False,'error':'invalid_action'}
        else:measured=score(truth,answer)
        results.append({**{k:q[k] for k in ['id','template_id','capabilities','scene_group','partition','input_mode','difficulty','condition']},**measured})
    by_cap=defaultdict(list)
    for row in results:
        for c in row['capabilities']:by_cap[c].append(row)
    summary={c:{'success_rate':sum(r['success'] for r in rows)/len(rows),'samples':len(rows),'scenes':len({r['scene_group'] for r in rows})} for c,rows in by_cap.items()}
    path=Path(directory)/'feedback.jsonl';path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in results),encoding='utf8')
    write_json(Path(directory)/'report.json',{'partition':partition,'by_capability':summary,'macro_success':sum(v['success_rate'] for v in summary.values())/len(summary),'errors':dict(Counter(r['error'] for r in results if r['error']))})
    return {'feedback':str(path),'report':str(Path(directory)/'report.json'),'partition':partition,'by_capability':summary}
