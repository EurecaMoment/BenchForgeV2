"""Executable task definitions: public wording and private arithmetic together.

Legacy templates remain replayable. This contract uses visible box centers for
2D tasks, and calibrated range measurements for depth tasks. Unsupported tasks
return no candidates instead of guessing or quietly changing the capability.
"""
import io
import itertools
import json
import math
import random
from collections import Counter
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

IDS={'T021','T022','T023','T024','T025','T034','T035','T036','T037'}
COLORS=['#e53935','#007fd4','#158238','#ad5700']


def render(image_path,objects,path):
    image=Image.open(image_path).convert('RGB');draw=ImageDraw.Draw(image)
    size=max(10,min(24,round(min(image.size)*.035)))
    try:font=ImageFont.truetype('DejaVuSans-Bold.ttf',size)
    except OSError:font=ImageFont.load_default()
    occupied=[]
    for i,obj in enumerate(objects):
        x1,y1,x2,y2=obj['bbox'];color=COLORS[i];letter=chr(65+i)
        draw.rectangle((x1,y1,x2-1,y2-1),outline=color,width=max(1,round(size/8)))
        cx,cy=obj['center'];radius=max(2,round(size/7))
        draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=color,outline='white',width=1)
        box=draw.textbbox((0,0),letter,font=font);w=box[2]-box[0]+6;h=box[3]-box[1]+6
        proposals=[(x1,y1-h-2),(x1,y2+2),(x2-w,y1-h-2),(x1,y1+2)]
        candidates=[]
        for x,y in proposals:
            x=int(max(0,min(image.width-w,x)));y=int(max(0,min(image.height-h,y)))
            overlap=sum(max(0,min(x+w,b[2])-max(x,b[0]))*max(0,min(y+h,b[3])-max(y,b[1])) for b in occupied)
            candidates.append((overlap,x,y))
        _,x,y=min(candidates,key=lambda c:c[0]);occupied.append((x,y,x+w,y+h))
        draw.rectangle(occupied[-1],fill=color)
        draw.text((x+3-box[0],y+3-box[1]),letter,font=font,fill='white')
    path.parent.mkdir(parents=True,exist_ok=True);image.save(path)


def generate_spatial(record,image_path,spec,output=None):
    requested=set(spec.template_ids) or {'T021','T023','T025','T034'}
    if requested-IDS:
        from .domain import HarnessError
        raise HarnessError('TASK_CONTRACT_UNSUPPORTED','spatial-v2 definitions: '+','.join(sorted(IDS)))
    entities=record.data['entities'];width=entities['image_size']['width'];height=entities['image_size']['height']
    objects=[]
    for raw in entities['objects']:
        box=raw.get('bbox_2d',{}).get('xyxy');conf=raw.get('confidence',{}).get('value',0)
        if not box or conf<.5 or not raw.get('valid_for_question_generation',True):continue
        x1,y1,x2,y2=box
        if min(x2-x1,y2-y1)<3 or x1<0 or y1<0 or x2>width or y2>height:continue
        # Near-identical regions are not independent objects for a comparison.
        if any(_iou(box,o['bbox'])>.85 for o in objects):continue
        objects.append({'id':raw['object_id'],'bbox':box,'center':[(x1+x2)/2,(y1+y2)/2],
                        'range':raw.get('range_median_m'),'area':raw.get('mask',{}).get('area_px',0)})
    objects=sorted(objects,key=lambda o:(-o['area'],o['id']))[:32]
    rng=random.Random(str(spec.seed)+record.record_id);rng.shuffle(objects)
    pairs=list(itertools.combinations(objects,2));rng.shuffle(pairs)
    rows=[];counts=Counter();limit=max(8,min(spec.target_items*2,32))
    def add(tid,chosen,question,answer,kind='single_choice',values=None):
        if tid not in requested or counts[tid]>=limit:return
        counts[tid]+=1;iid=f'{record.record_id}_{tid}_v2_{counts[tid]:04d}'
        path=(Path(output) if output else Path('/replay'))/record.record_id/f'{iid}.png'
        if output is not None:render(image_path,chosen,path)
        choices={'A':'是','B':'否'} if len(chosen)==2 else {chr(65+i):'标记 '+chr(65+i) for i in range(len(chosen))}
        contract={'version':'spatial-v2','measure':'visible_bbox_center_px' if tid not in {'T036','T037'} else 'median_euclidean_range_m',
                  'objects':[o['id'] for o in chosen],'source_record':record.record_id}
        rows.append({'item_id':iid,'template_id':tid,'question':question,'options':choices,'answer':answer,'answer_type':kind,
            'image':str(path),'auxiliary_images':['original_rgb'],'derivation':'spatial-task/v2','task_contract':contract,
            'scoring':{'metric':'ordered_list_pairwise_accuracy' if kind=='ordering' else 'choice_exact/v1'},
            'capability_ids':['relative_position_2d' if tid not in {'T036','T037'} else 'relative_depth'],
            'provenance':{'objects':chosen,'gt_values':values or {}}})
    words={'T021':(0,'左侧',-1),'T022':(0,'右侧',1),'T023':(1,'上方',-1),'T024':(1,'下方',1)}
    for a,b in pairs:
        chosen=[a,b]
        for tid,(axis,word,direction) in words.items():
            delta=a['center'][axis]-b['center'][axis]
            if abs(delta)>=.06*(width if axis==0 else height):
                add(tid,chosen,f'比较图中 A、B 标注框中心的彩色圆点：A 点是否在 B 点的{word}？',
                    'A' if delta*direction>0 else 'B',values={'delta_px':delta})
        if record.data.get('range_verified') and a['range'] and b['range'] and abs(a['range']-b['range'])>.15*min(a['range'],b['range']):
            add('T036',chosen,'标记 A 对应的可见表面是否比 B 更靠近相机？距离按可见表面到相机光心的直线距离中位数比较。',
                'A' if a['range']<b['range'] else 'B',values={'A_range_m':a['range'],'B_range_m':b['range']})
    if len(objects)>=4:
        seen=set()
        for _ in range(limit*20):
            chosen=rng.sample(objects,4);key=tuple(sorted(o['id'] for o in chosen))
            if key in seen:continue
            seen.add(key)
            distance=[math.hypot(o['center'][0]-width/2,o['center'][1]-height/2) for o in chosen]
            order=sorted(range(4),key=lambda i:distance[i])
            if distance[order[1]]-distance[order[0]]>.04*min(width,height):
                add('T025',chosen,'图中哪个标注框中心的彩色圆点最靠近整幅图像的中心？按图像平面内的直线距离比较。',chr(65+order[0]),values={'distance_px':distance})
            for tid,axis,word in [('T034',0,'左到右'),('T035',1,'上到下')]:
                order=sorted(range(4),key=lambda i:chosen[i]['center'][axis]);values=[chosen[i]['center'][axis] for i in order]
                if min(b-a for a,b in zip(values,values[1:]))>.06*(width if axis==0 else height):
                    add(tid,chosen,f'按标注框中心的彩色圆点从{word}排列，输出对应字母的 JSON 列表。',[chr(65+i) for i in order],'ordering')
            if record.data.get('range_verified') and all(o['range'] for o in chosen):
                order=sorted(range(4),key=lambda i:chosen[i]['range'])
                if chosen[order[1]]['range']>chosen[order[0]]['range']*1.15:
                    add('T037',chosen,'哪个标记对应的可见表面离相机最近？距离按可见表面到相机光心的直线距离中位数比较。',chr(65+order[0]))
    return rows


def _iou(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def select_diverse(candidates,target):
    """Greedy coverage across template, source and answer; never changes GT."""
    remaining=list(candidates);chosen=[];templates=Counter();sources=Counter();answers=Counter();used=set()
    while remaining and len(chosen)<target:
        remaining=[pair for pair in remaining if _signature(*pair) not in used]
        if not remaining:break
        def priority(pair):
            row,record=pair;tid=row['template_id'];gold=json.dumps(row['answer'],sort_keys=True)
            return templates[tid],sources[record.record_id],answers[(tid,gold)],row['item_id']
        best=min(remaining,key=priority);remaining.remove(best);chosen.append(best)
        row,record=best;templates[row['template_id']]+=1;sources[record.record_id]+=1
        answers[(row['template_id'],json.dumps(row['answer'],sort_keys=True))]+=1;used.add(_signature(row,record))
    return chosen


def _signature(row,record):
    # Reversing A/B or asking left and right of the same pair is not new evidence.
    tid=row['template_id'];family='horizontal' if tid in {'T021','T022'} else 'vertical' if tid in {'T023','T024'} else tid
    return record.record_id,family,tuple(sorted(row['task_contract']['objects']))
