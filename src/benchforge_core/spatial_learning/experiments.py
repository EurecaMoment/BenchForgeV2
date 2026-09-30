"""Run A/B/C from the same initial checkpoint, dataset, seed and update budget."""
import json
from pathlib import Path
from .training import run
from .generation import write_json
from .evaluation import read_rows


def experiment(args,directory,config=None):
    settings=json.loads(Path(args['config']).read_text(encoding='utf8'));root=Path(args.get('run',Path(directory)/'comparison'))
    results=[]
    for seed in args.get('seeds',[settings.get('seed',11)]):
        for arm in ['A','B','C']:
            # Reinitialization restores the same initial checkpoint and RNG.
            import torch
            torch.manual_seed(seed)
            arm_config={**settings,'seed':seed,'condition':arm};arm_config.pop('resume',None)
            # Each arm starts from the same caller-supplied initial checkpoint;
            # a run-local copy prevents one arm from mutating the next arm.
            initial=settings.get('initial_checkpoint') or settings.get('model')
            if not initial:raise ValueError('A/B/C comparison requires initial_checkpoint or model')
            arm_config['model']=initial
            directory=root/f'seed_{seed}'/arm
            result=run(arm_config,directory)
            events=read_rows(directory/'events.jsonl');updates=[e for e in events if e['event']=='update'];dev=[e for e in events if e['event']=='development']
            results.append({'seed':seed,'condition':arm,'checkpoint':result['checkpoint'],
                'initial_selection':dev[0]['selection_score'],'final_selection':dev[-1]['selection_score'],
                'update_steps':len(updates),'update_seconds':sum(e['seconds'] for e in updates),
                'input_tokens':sum(e.get('input_tokens',0) for e in updates),
                'supervised_tokens':sum(e.get('supervised_tokens',0) for e in updates)})
            write_json(root/'comparison.json',{'runs':results,'budget':'same optimizer updates, batch size and pool; realized time/tokens reported separately','sealed_test_used':False})
    return {'comparison':str(root/'comparison.json'),'runs':results}
