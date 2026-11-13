"""Revise an existing C24/C26/C28/C63 evidence set without resampling its truth.

Run beside the existing task oracle and Isaac receipts. New public material is
explicit supplied information: center markers, masks, sample observations and
geometry. Old datasets and delivery files remain in the revision archive.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import sys


def natural(text):
    text = re.sub(r'OBJ(\d+)', r'\1号物体', str(text))
    return re.sub(r'[（(]世界[+-][XY][）)]', '', text).strip()


def query(text):
    return natural(text.split('候选：')[0]).rstrip('？?。；;') + '？'


def outline(points):
    """The same monotone convex hull as the retained oracle, without SciPy."""
    points=sorted(set(map(tuple,points)))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    halves=[]
    for ordered in (points,list(reversed(points))):
        half=[]
        for p in ordered:
            while len(half)>=2 and cross(half[-2],half[-1],p)<=0:half.pop()
            half.append(p)
        halves.append(half[:-1])
    return halves[0]+halves[1]


def make_spec(row, source, media_labels):
    from benchforge_core.pipelines.question_writing import SCHEMA
    tid, p = row['template_id'], row['parameters']
    trace = source['private']['oracle_trace']
    context, conditions, options = [], [], []
    identity = '图中编号对应题目中的物体编号；同一编号在不同图中代表同一物体。'
    response = ''
    if tid == 'C24-T01':
        stem = f"看图1，{natural(p['A'])}在{natural(p['B'])}的哪一侧？"
        context = [identity]
        conditions = ['以画面为参照，比较图中圆点标出的物体中心位置；方向按画面左右、上下判断。']
        options = ['左侧', '右侧', '上方(画面上)', '下方(画面下)']
        response = '提交 {"label":"所选方向的原文"}。'
    elif tid == 'C24-T02':
        stem = f"看平面图，{natural(p['A'])}是否位于{natural(p['B'])}和{natural(p['C'])}之间？"
        context = [identity]
        conditions = ['以物体中心为准。把后两个物体的中心连成线段：第一个物体的中心沿这条线投影后，必须落在线段内部，且离线段不超过0.25米。',
                      '图中坐标使用米；只比较水平面位置，不比较物体高度。']
        options = ['是', '否']
        response = '提交 {"value":true} 或 {"value":false}。'
    elif tid == 'C24-T03':
        axis, sign, anchor = trace['axis'], trace['sign'], trace['anchor']
        direction = {('x','>'):'东',('x','<'):'西',('y','>'):'北',('y','<'):'南'}[(axis,sign)]
        stem = f'平面图中，哪些物体比{natural(anchor)}向{direction}超过0.25米？'
        context = [identity]
        conditions = ['按物体中心判断。图中横轴向东、纵轴向北，坐标单位为米。',
                      '从图中全部编号物体中选出所有满足条件的物体；不包括参照物本身。']
        response = '提交 {"ids":["所选物体的OBJ编号"]}；没有则填空数组，多个编号顺序不限。'
    elif tid == 'C26-T01':
        stem = query(p['query'])
        context = [natural(value) + '。' for value in p['facts'].split('；')]
        conditions = ['所有方向使用同一参照系：东为横轴正方向，北为纵轴正方向；比较物体中心。',
                      '已知条件中的相邻物体沿所述方向至少相隔0.3米。根据这些已知条件推理。']
        options = [value.strip() for value in p['query'].split('候选：')[1].split('|')]
        response = '提交 {"label":"所选选项的原文"}。'
    elif tid == 'C26-T02':
        stem = query(p['query'].replace('像面',''))
        context = [identity, *[natural(value) + '。' for value in p['transforms'].split('；')]]
        conditions = ['图1与图2拍摄同一场景；方向分别以各自画面为参照。',
                      '比较中心圆点的位置；跨图编号对应已给出。需要转换参照系时使用附带的标定。']
        target = re.search(r'OBJ\d+',p['query']).group()
        options = [target+' 在左',target+' 在右','两者横向重合']
        response = '提交 {"label":"所选选项的原文"}。'
    elif tid == 'C26-T03':
        target, anchor = re.findall(r'OBJ\d+', p['query'])
        stem = f"根据已知条件，{natural(target)}在{natural(anchor)}的北侧还是南侧，还是无法确定？"
        context = [natural(value) + '。' for value in p['facts'].split('；')]
        conditions = ['所有方向采用同一参照系：东为横轴正方向，北为纵轴正方向；比较物体中心。',
                      '如果已知条件允许不同的南北位置关系，应回答信息不足。']
        options = ['北侧(世界+Y)','南侧(世界-Y)','unknown（信息不足）']
        response = '提交 {"label":"北侧(世界+Y)"}、{"label":"南侧(世界-Y)"} 或 {"label":"unknown"}。'
    elif tid == 'C28-T01':
        stem = f"比较图A和图B，哪张图中的{natural(p['object'])}露出的比例更大？"
        context = [identity, '附带两张对照图：左边是实际可见区域，右边是同一机位下物体完整投影的轮廓。']
        conditions = ['露出的比例＝实际可见区域面积÷完整投影面积；不能只比较物体在画面中的大小。',
                      f"两图比例相差不超过{p['epsilon']}，视为差异不显著。"]
        options = ['图A更完整','图B更完整',f"差异不显著(≤{p['epsilon']})"]
        response = '提交 {"label":"所选选项的原文"}。'
    elif tid == 'C28-T02':
        stem = f"比较图A和图B，{natural(p['object'])}在哪张图中可见的表面采样点更多？"
        context = [identity, f"附带表面点记录图：两图使用相同编号的{trace['n']}个点；绿色表示该点可见，白色表示不可见。"]
        conditions = ['物体用几何盒表示；每个盒的六个面各取4×4个固定点。物体含多个部件时，每个部件分别取点，点编号在两图中保持一致。',
                      '根据点记录比较可见点数量，不用物体的像素面积代替点数。']
        options = ['图A可见点多','图B可见点多','相同']
        response = '提交 {"choice_id":"所选选项的原文"}。'
    elif tid == 'C28-T03':
        stem = f"看图A和图B，哪张图中能看到{natural(p['object'])}的有效编号框？"
        context = [identity]
        conditions = ['本题把出现有效绿色身份框的区域记为可见；不比较露出的比例。']
        options = ['图A','图B','两张都','两张都不']
        response = '提交 {"label":"所选选项的原文"}。'
    elif tid == 'C63-T01':
        stem = f"站在图中蓝色观察点，能看见{natural(p['target'])}吗？"
        context = [identity, f"观察点的眼高为{trace['eye'][2]:.2f}米；位置见平面图。", '附图列出每个几何盒的中心、半尺寸和局部轴方向；长度单位为米。']
        conditions = ['本题可向水平面四周观察，水平视域为360°；不限制垂直视场。',
                      '目标固定表面点中，没有被障碍挡住的比例超过30%，记为能看见；不要仅检查一条中心视线。']
        options = ['能','不能']
        response = '提交 {"value":true} 或 {"value":false}。'
    elif tid == 'C63-T02':
        stem = f"站在图中蓝色观察点，朝箭头方向看，能看见{natural(p['target'])}吗？"
        context = [identity, f"观察点的眼高为{trace['eye'][2]:.2f}米；位置和朝向见平面图。", '附图列出每个几何盒的中心、半尺寸和局部轴方向；长度单位为米。']
        conditions = [f"水平视场角为{p['hfov']}，不限制垂直视场。",
                      '只统计水平视场内的目标表面点；其中未被遮挡的比例超过30%，记为能看见。水平视场内没有目标点则记为不能。']
        options = ['能','不能']
        response = '提交 {"value":true} 或 {"value":false}。'
    elif tid == 'C63-T03':
        stem = f"图中哪些观察点能看见{natural(p['target'])}？"
        context = [identity, '候选观察点：'+p['viewpoints']+'。', '附图列出每个几何盒的中心、半尺寸和局部轴方向；长度单位为米。']
        conditions = ['各点均可向水平面四周观察，水平视域为360°，不限制垂直视场；目标保持不动。',
                      '目标固定表面点中未被障碍挡住的比例达到30%，记为能看见；选出所有符合条件的观察点。']
        options = list(trace['fracs'])
        response = '提交 {"ids":["所选观察点编号"]}；没有则填空数组，顺序不限。'
    else:
        raise ValueError('This revision adapter supports only the reviewed C24/C26/C28/C63 variants')
    if tid.startswith('C63-'):
        conditions += ['按附图中的每个目标几何盒取点：六个面各取6×6点；每面两条边方向在盒半尺寸的90%范围内均匀取网格中心，垂直该面的坐标取半尺寸的99%。多个部件分别取点并一起统计。',
                       '遮挡按附图中的几何盒计算，目标自身不作障碍；地板和地毯不作障碍。这里的几何盒是已给的测量模型。']
    return {'schema':SCHEMA,'stem':stem,'context':context,'conditions':conditions,'options':options,
            'response':response,'media_labels':media_labels,'parameter_bindings':deepcopy(p)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--operation',required=True)
    parser.add_argument('--revision',default='readable-20261104')
    parser.add_argument('--delivery',required=True)
    args=parser.parse_args()
    ws,op,delivery=map(Path,[args.workspace,args.operation,args.delivery])
    state_path=op/'run_state/state.json'
    state=json.loads(state_path.read_text())
    context=state.get('context',{})
    if not (context.get('session_id') or context.get('session_ids')):raise ValueError('The source run must be associated with a conversation')
    original=Path(state['steps']['questions']['result']['dataset'])
    revision=op/'question-revisions'/args.revision
    revision.mkdir(parents=True,exist_ok=False)
    (revision/'request.json').write_text(json.dumps({'context':state['context'],'question_revision':args.revision,'source_run':str(state_path.parent)},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.path.insert(0,str(op/'oracle'))
    from prod_lib import SceneCtx
    from spatial_oracle import surface_samples
    from benchforge_core.pipelines.production import produce,package
    from benchforge_core.pipelines.question_writing import validate_spec, question_text
    import numpy as np
    from PIL import Image,ImageDraw,ImageFont
    old_public=[json.loads(line) for line in (original/'questions.jsonl').read_text().splitlines()]
    old_truth=[json.loads(line) for line in (original/'authority.jsonl').read_text().splitlines()]
    evidence=[json.loads(line) for line in (delivery/'scene_evidence.jsonl').read_text().splitlines()]
    if len(evidence)!=len(old_public) or len(old_truth)!=len(old_public) or len(evidence)!=100: raise ValueError('Expected the existing 100-item evidence set')
    (revision/'state-before.json').write_bytes(state_path.read_bytes())
    contexts={}
    media_dir=revision/'public-inputs';media_dir.mkdir()
    source_dir=revision/'sources';source_dir.mkdir()
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)

    def center_image(cx,path):
        view=next(v for v in cx.views if v['annot']==str(path))
        target=media_dir/(cx.name+'_'+view['frame_id']+'_centers.png')
        if target.exists(): return target
        image=Image.open(path).convert('RGB');draw=ImageDraw.Draw(image)
        for token in view['shown_tokens']:
            oid=cx.inv[token];x,y,z=cx.centroid_px(view,oid)
            if z<=0 or not(0<=x<image.width and 0<=y<image.height): continue
            draw.ellipse((x-5,y-5,x+5,y+5),fill=(255,40,180),outline='white',width=2)
            draw.text((x+7,y-8),token[3:],font=font,fill='white',stroke_width=2,stroke_fill='black')
        image.save(target);return target

    def mask_reference(cx,path,oid,token):
        view=next(v for v in cx.views if v['annot']==str(path))
        target=media_dir/(cx.name+'_'+view['frame_id']+'_'+token+'_mask_reference.png')
        if target.exists(): return target
        grid=np.load(view['sem_npy']);mask=np.isin(grid,[key for key,value in view['sem_map'].items() if value==oid])
        original_mask=Image.fromarray(np.uint8(mask)*255).convert('RGB')
        corners=[]
        for box in cx.obbs[oid]:
            corners.extend(box.corners())
        projected=view['cam'].project(np.asarray(corners));points=projected[projected[:,2]>.02,:2]
        hull=outline(points)
        lo=np.floor(np.minimum(points.min(axis=0),[0,0])).astype(int)
        hi=np.ceil(np.maximum(points.max(axis=0),original_mask.size)).astype(int)
        size=tuple(hi-lo)
        actual=Image.new('RGB',size,'black');actual.paste(original_mask,tuple(-lo))
        complete=Image.new('RGB',size,'black');draw=ImageDraw.Draw(complete)
        draw.polygon([tuple(np.asarray(p)-lo) for p in hull],fill='white')
        W,H=actual.size
        panel=Image.new('RGB',(2*W,H+32),(245,246,248));panel.paste(actual,(0,32));panel.paste(complete,(W,32))
        draw=ImageDraw.Draw(panel);draw.text((12,8),'Visible region',font=font,fill='black');draw.text((W+12,8),'Complete projected outline',font=font,fill='black')
        panel.save(target);return target

    def point_record(cx,path,oid,token):
        view=next(v for v in cx.views if v['annot']==str(path))
        target=media_dir/(cx.name+'_'+view['frame_id']+'_'+token+'_surface_points.png')
        if target.exists(): return target
        flags=cx.mask_points_visible(view,oid,surface_samples(cx.obbs[oid],grid=4))
        image=Image.new('RGB',(820,55+((len(flags)+15)//16)*55),(245,246,248));draw=ImageDraw.Draw(image)
        draw.text((16,10),token+' fixed surface points: green = visible; white = hidden',font=font,fill='black')
        for i,flag in enumerate(flags):
            x,y=16+(i%16)*50,45+(i//16)*55
            draw.rectangle((x,y,x+42,y+42),fill=(100,210,145) if flag else 'white',outline=(100,110,120))
            draw.text((x+9,y+13),str(i+1),font=font,fill='black')
        image.save(target);return target

    def geometry_image(cx):
        target=media_dir/(cx.name+'_public_geometry.png')
        if target.exists(): return target
        # Publish the actual oracle leaf boxes, including rotated compound parts.
        values=[(oid,i,box) for oid,boxes in cx.obbs.items() for i,box in enumerate(boxes)]
        image=Image.new('RGB',(1160,65+len(values)*66),(248,249,250));draw=ImageDraw.Draw(image)
        columns=[15,205,465,700]
        for x,label in zip(columns,['Object / part','Center x,y,z (m)','Half sizes (m)','Local axes in world coordinates']):draw.text((x,15),label,font=font,fill='black')
        for i,(oid,part,box) in enumerate(values):
            y=45+i*66
            fields=[cx.toks.get(oid,oid)+f' / {part+1}',', '.join(f'{v:.5f}' for v in box.c),', '.join(f'{v:.5f}' for v in box.h)]
            for x,value in zip(columns,fields):draw.text((x,y),value,font=font,fill=(35,45,55))
            for axis in range(3):draw.text((columns[3],y+axis*19),f'{"XYZ"[axis]}: '+', '.join(f'{v:.5f}' for v in box.R[:,axis]),font=font,fill=(35,45,55))
        image.save(target);return target

    def plan_centers(cx,path):
        target=media_dir/(cx.name+'_'+path.stem+'_centers.png')
        if target.exists():return target
        values=list(cx.pl.values())
        lo=[min(p['center'][i]-p['size'][i]/2 for p in values)-.5 for i in range(2)]
        hi=[max(p['center'][i]+p['size'][i]/2 for p in values)+.5 for i in range(2)]
        image=Image.open(path).convert('RGB');draw=ImageDraw.Draw(image)
        for oid,token in cx.toks.items():
            c=cx.center[oid];x=(c[0]-lo[0])/(hi[0]-lo[0])*image.width;y=image.height-(c[1]-lo[1])/(hi[1]-lo[1])*image.height
            draw.ellipse((x-4,y-4,x+4,y+4),fill=(255,40,180),outline='white',width=1)
            draw.text((x+6,y+6),token[3:],font=font,fill=(20,20,60))
        # Original rendering included a machine scene name in its title.
        draw.rectangle((0,0,image.width,23),fill=(248,248,244))
        draw.text((8,4),'Floor plan: pink dots = object centers; x = East, y = North; units = meters',font=font,fill=(45,50,60))
        image.save(target);return target

    corrected_schema=0
    for row in evidence:
        source=json.loads(Path(row['provenance']['path']).read_text())
        scene=row['scene_group_id'].split(':',1)[1]
        if scene not in contexts: contexts[scene]=SceneCtx(str(op/'annotations'/f'{scene}.json'))
        cx=contexts[scene];tid=row['template_id'];old_media=[Path(p) for p in row['media']]
        images=[p for p in old_media if p.suffix.lower()!='.json'];metadata=[p for p in old_media if p.suffix.lower()=='.json']
        labels=[]
        if tid in ('C24-T01','C26-T02'):
            images=[center_image(cx,p) for p in images]
            labels=[f'图{i+1}：物体编号与中心位置' for i in range(len(images))]
        elif tid.startswith('C28-'):
            labels=['图A：场景与物体编号','图B：场景与物体编号']
            if tid in ('C28-T01','C28-T02'):
                token=row['parameters']['object'];oid=cx.inv[token]
                if tid=='C28-T01':
                    images += [mask_reference(cx,p,oid,token) for p in images[:2]]
                    labels += ['图A对照：实际可见区域与完整投影轮廓','图B对照：实际可见区域与完整投影轮廓']
                else:
                    flags=[cx.mask_points_visible(next(v for v in cx.views if v['annot']==str(p)),oid,surface_samples(cx.obbs[oid],grid=4)) for p in images[:2]]
                    trace=source['private']['oracle_trace']
                    if any(len(f)!=trace['n'] for f in flags) or [int(np.count_nonzero(f)) for f in flags]!=[trace['vis_A'],trace['vis_B']]:
                        raise ValueError('Public sample records must match the retained oracle observations')
                    images += [point_record(cx,p,oid,token) for p in images[:2]]
                    labels += ['图A：固定表面点可见记录','图B：固定表面点可见记录']
                    # The original source used label despite the template's choice_id contract.
                    source['answer']={'choice_id':source['answer']['label']};corrected_schema+=1
                    source['private']['answer']=deepcopy(source['answer'])
        else:
            if tid in ('C24-T02','C24-T03') or tid.startswith('C63-'):
                images=[plan_centers(cx,p) for p in images]
            labels=[f'图{i+1}：场景平面图' for i in range(len(images))]
            if tid.startswith('C63-'):
                images.append(geometry_image(cx));labels.append('附图：物体中心、尺寸、高度与障碍几何（米）')
        row['media']=[str(p) for p in [*images,*metadata]]
        labels += ['相机标定（技术详情）']*len(metadata)
        row['question_spec']=make_spec(row,source,labels)
        validate_spec(row['question_spec'],row['parameters'],len(row['media']))
        source['question']=question_text(row['question_spec'])
        source['question_spec']=deepcopy(row['question_spec'])
        row['provided_information']=list(row['provided_information'])+['按题型补充的中心标记、可见区域对照、固定表面点或公开几何；属于已给辅助信息']
        new_source=source_dir/Path(row['provenance']['path']).name
        new_source.write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
        row['provenance']={**row['provenance'],'path':str(new_source),'question_revision':args.revision}
    evidence_path=revision/'scene_evidence.jsonl'
    evidence_path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in evidence),encoding='utf-8')
    counts={tid:sum(row['template_id']==tid for row in evidence) for tid in dict.fromkeys(row['template_id'] for row in evidence)}
    result=produce({'selections':[{'template_ids':[tid],'count':count} for tid,count in counts.items()],
                    'evidence':str(evidence_path),'split':'test','seed':1030,'_workspace':str(ws)},revision/'production')
    dataset=Path(result['dataset'])
    new_truth=[json.loads(line) for line in (dataset/'authority.jsonl').read_text().splitlines()]
    if len(new_truth)!=len(old_truth):raise ValueError('Revision changed item count')
    for before,after in zip(old_truth,new_truth):
        expected=before['answer']
        if before['template_id']=='C28-T02': expected={'choice_id':expected['label']}
        if before['item_id']!=after['item_id'] or expected!=after['answer']:raise ValueError('Revision changed semantic truth or item order')
    report=json.loads((dataset/'quality_report.json').read_text())
    report['question_revision']={'version':args.revision,'previous_dataset':str(original),'items':len(evidence),
        'writing_checks_passed':True,'semantic_truth_preserved':True,'output_key_corrections':corrected_schema,
        'public_information_condition':'supplied_intermediate','model_quality_judging':False}
    (dataset/'quality_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    result['question_revision']=report['question_revision']
    (revision/'bundles').mkdir()
    bundles=package({'dataset':str(dataset)},revision/'bundles')
    # Activation is reversible and happens only after the new dataset and bundles validate.
    backup=revision/'delivery-before';backup.mkdir()
    for name in ['questions.jsonl','authority.jsonl','quality_report.json','scene_evidence.jsonl','public_bundle.zip','authority_bundle.zip','REPORT.md']:
        if (delivery/name).exists():shutil.copy2(delivery/name,backup/name)
    saved_dataset=backup/'dataset'
    try:
        if (delivery/'dataset').exists(): (delivery/'dataset').rename(saved_dataset)
        shutil.copytree(dataset,delivery/'dataset')
        for name in ['questions.jsonl','authority.jsonl','quality_report.json']:
            shutil.copy2(dataset/name,delivery/name)
        shutil.copy2(evidence_path,delivery/'scene_evidence.jsonl')
        for kind in ['public','authority']:shutil.copy2(bundles[kind+'_bundle'],delivery/(kind+'_bundle.zip'))
        state['steps']['questions']['result']=result
        if 'outputs' in state:state['outputs']['questions']=result
        if 'package' in state['steps']:state['steps']['package']['result']=bundles
        if 'outputs' in state:state['outputs']['package']=bundles
        temporary=state_path.with_suffix('.readable-new');temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(state_path)
    except Exception:
        state_path.write_bytes((revision/'state-before.json').read_bytes())
        for saved in backup.iterdir():
            if saved.is_file():shutil.copy2(saved,delivery/saved.name)
        if saved_dataset.exists():
            if (delivery/'dataset').exists():(delivery/'dataset').rename(revision/'failed-delivery-dataset')
            saved_dataset.rename(delivery/'dataset')
        raise
    note='\n\n## 2026-11-04 题面修订\n100题已改为短题干、公开条件、作答规则与选项分栏；补充中心标记、可见区域/完整轮廓对照、固定表面点记录和公开障碍几何。保留原题顺序、场景组与真值含义；4道可见点题的输出字段从label纠正为模板规定的choice_id。公开辅助条件单列为supplied_intermediate，不能当作未经辅助的自然视觉恢复。旧版本保存在本次question-revisions目录。未调用模型进行质量判定。\n'
    with (delivery/'REPORT.md').open('a',encoding='utf-8') as file:file.write(note)
    receipt={'dataset':str(dataset),'revision':str(revision),'accepted':result['accepted'],'per_template':counts,
             'semantic_truth_preserved':True,'output_key_corrections':corrected_schema,'public_bundle':bundles['public_bundle'],
             'production_api_calls':0,'model_api_calls':0,'service_restarts':0}
    (revision/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
