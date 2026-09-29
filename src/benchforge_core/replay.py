"""Replay native-depth measurements in a relocated compiler bundle."""
import argparse
import json
from pathlib import Path


def replay(bundle):
    import numpy as np
    bundle=Path(bundle).resolve()
    records=[json.loads(line) for line in (bundle/'evidence_index.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    checked=[];skipped=[];errors=[]
    for record in records:
        if not record.get('raw_depth_path') or not record.get('camera'):
            skipped.append(record.get('id',record.get('sample_id')));continue
        camera=record['camera'].get('intrinsics',record['camera'])
        path=Path(record['raw_depth_path'])
        if not path.is_absolute():path=bundle/path
        z=np.load(path).squeeze()
        for obj in record.get('objects',[]):
            if obj.get('depth_median') is None:continue
            box=obj.get('bbox_xyxy') or obj.get('bbox_2d',{}).get('xyxy')
            if box is None:
                errors.append({'id':record['id'],'object':obj.get('object_id'),'reason':'missing measurement footprint'});continue
            x1,y1,x2,y2=map(int,box)
            if not (0<=x1<x2<=z.shape[1] and 0<=y1<y2<=z.shape[0]):raise ValueError('Measurement footprint outside depth frame')
            yy,xx=np.mgrid[y1:y2,x1:x2]
            ranges=z[y1:y2,x1:x2]*np.sqrt(1+((xx-camera['cx'])/camera['fx'])**2+((yy-camera['cy'])/camera['fy'])**2)
            value=float(np.median(ranges))
            if not np.isfinite(ranges).all() or not np.all(ranges>0) or abs(value-obj['depth_median'])>1e-3:
                errors.append({'id':record['id'],'object':obj.get('object_id'),'stored':obj['depth_median'],'replayed':value})
            checked.append({'id':record['id'],'object':obj.get('object_id'),'replayed':value})
    return {'measurements':len(checked),'errors':errors,'skipped_records':skipped,
            'status':'failed' if errors else 'passed' if checked else 'not_applicable',
            'note':'Checks native camera-range measurements only; other source schemas require their explicit oracle adapter.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',required=True);args=parser.parse_args()
    result=replay(args.bundle);print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(1 if result['errors'] else 0)
