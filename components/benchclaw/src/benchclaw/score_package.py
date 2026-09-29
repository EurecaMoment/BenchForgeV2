"""Standalone private scorer: python score_package.py predictions.jsonl."""
import json
import sys
from pathlib import Path
from metrics import score_answer,metric_details


def main():
    answers={r['item_id']:r for r in map(json.loads,(Path(__file__).parent/'answers.jsonl').read_text().splitlines())}
    predictions=[json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line]
    seen=set();scores={};details={}
    for row in predictions:
        key=(row['model_id'],row['item_id'])
        if key in seen or key[1] not in answers:raise ValueError('Duplicate or unknown prediction')
        seen.add(key);a=answers[key[1]]
        scores.setdefault(key[0],{})[key[1]]=score_answer(a['gold'],row.get('prediction'),a['rubric_id'],a.get('metric_parameters')) if row.get('status','succeeded')=='succeeded' else 0
        details.setdefault(key[0],{})[key[1]]=metric_details(a['gold'],row.get('prediction'),a['rubric_id'],a.get('metric_parameters')) if row.get('status','succeeded')=='succeeded' else {'score':0}
    print(json.dumps({model:{'expected':len(answers),'processed':len(items),'mean_score':sum(items.values())/len(answers),'per_item':items,'metric_details':details[model]} for model,items in scores.items()},indent=2))


if __name__=='__main__':main()
