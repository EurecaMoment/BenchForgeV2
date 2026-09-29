"""Real local program-evidence -> package -> score flow; no simulated GPU claims."""
import argparse
from pathlib import Path
from benchforge_core.runtime import Runtime, write, jsonl


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    args=parser.parse_args()
    workspace=Path(args.workspace).resolve()
    workspace.mkdir(parents=True,exist_ok=True)
    # Deliberately tiny arithmetic fixture, not a production spatial benchmark.
    write(workspace/'source.json',{'answers':[2+3,8-2]})
    jsonl(workspace/'records.jsonl',[
        {'id':f'e{i}','provenance':{'kind':'program','path':'source.json'},
         'selectors':{'answer':f'/answers/{i}'},'media':[]} for i in range(2)])
    jsonl(workspace/'items.jsonl',[
        {'id':'q0','question':'What is 2 + 3?','evidence_id':'e0','answer_field':'answer','template':'addition'},
        {'id':'q1','question':'What is 8 - 2?','evidence_id':'e1','answer_field':'answer','template':'subtraction'}])
    runtime=Runtime(workspace)
    try:
        runtime.call('plan',{'objective':'Exercise program-evidence packaging and offline scoring'})
        evidence=runtime.call('evidence',{'input':str(workspace/'records.jsonl')})
        package=runtime.call('build',{'evidence':evidence['evidence'],'items':str(workspace/'items.jsonl')})
        jsonl(workspace/'predictions.jsonl',[{'id':'q0','answer':5},{'id':'q1','answer':0}])
        score=runtime.call('evaluate',{'authority':package['authority'],'predictions':str(workspace/'predictions.jsonl')})
        result={'package':package,'score':score}
        write(workspace/'demo-result.json',result)
        print(workspace/'demo-result.json')
    finally:
        runtime.close()


if __name__=='__main__':
    main()
