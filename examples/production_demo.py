"""Downloadable visual production example; deterministic drawing, no model or GPU.

Install .[production], then: python examples/production_demo.py --workspace runs/production
This exercises real compiler/recipe/scorer/package code with synthetic inputs.
"""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw
from benchforge_core.runtime import Runtime
from benchforge_core.artifacts import jsonl, write


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',default='runs/production-demo');a=p.parse_args()
    root=Path(a.workspace).resolve();root.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for i,count in enumerate((2,4,3,5)):
        image=Image.new('RGB',(480,240),'#f4f1eb');draw=ImageDraw.Draw(image)
        for j in range(count):
            x=45+80*j;draw.rectangle((x,85,x+38,130),fill='#236c96',outline='black',width=2)
        path=root/f'scene_{i}.png';image.save(path)
        evidence.append({'id':f'scene_{i}','sample_id':f'scene_{i}','media':[str(path)],'image_path':str(path),
            'provenance':{'kind':'program'},'source_type':'program','objects_visible':list(range(count)),
            'sequence_semantics':'single_image'})
    source=root/'evidence.jsonl';jsonl(source,evidence)
    recipes=[{'template_id':'visible_count','question':'How many blue squares are visible?',
        'answer_type':'number','metric_id':'numeric_tolerance','difficulty_level':'easy','capability_tags':['count'],
        'answer_program':{'op':'count','inputs':['/objects_visible']},
        'visible_anchor':{'type':'whole_image','description':'All blue squares are visible with no occlusion.'}}]
    spec={'objective':'Count visibly rendered shapes using renderer state as ground truth.',
        'capabilities':[{'id':'count','description':'Count visible objects'}],'sources':[{'id':'renderer'}],
        'metrics':[{'id':'numeric_tolerance'}],'templates':[{'id':'visible_count','capabilities':['count'],
        'metric':'numeric_tolerance','sources':['renderer'],'answer_rule':'Count renderer objects',
        'visible_anchor':'Whole image, fully visible blue squares'}]}
    runtime=Runtime(root/'runs')
    try:
        design=runtime.call('design',{'spec':spec})
        compiled=runtime.call('compile',{'input':str(source),'recipes':recipes,'spec':design['spec']})
        produced=runtime.call('synthesize',{'bundle':compiled['bundle'],'limit':4,'mode':'full'})
        result={'design':design,'compile':compiled,'synthesis':produced,'test_kind':'synthetic visual production; no model or simulator acceptance'}
        write(root/'result.json',result)
        print(json.dumps({'items':produced['count'],'complete_package':produced['complete_package'],'result':str(root/'result.json')},indent=2))
    finally:runtime.close()


if __name__=='__main__':main()
