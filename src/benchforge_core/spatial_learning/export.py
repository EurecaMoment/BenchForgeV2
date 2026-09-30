"""Portable Parquet export: public observations and private authority stay separate."""
import json
from pathlib import Path
from .evaluation import read_rows
from .generation import PARTITIONS,write_json


def export(args,directory,config=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    source=Path(args['dataset']);root=Path(directory)/'parquet';root.mkdir(parents=True)
    counts={}
    for part in PARTITIONS:
        rows=read_rows(source/part/'questions.jsonl')
        public=[]
        for q in rows:
            public.append({'id':q['id'],'template_id':q['template_id'],'capabilities':q['capabilities'],
                'scene_group':q['scene_group'],'condition':q['condition'],'difficulty':q['difficulty'],
                'question':q['question'],'inputs_json':json.dumps(q['inputs'],ensure_ascii=False),
                'images':[(source/p).read_bytes() for p in q['images']],'record_json':json.dumps(q,ensure_ascii=False)})
        schema=pa.schema([('id',pa.string()),('template_id',pa.string()),('capabilities',pa.list_(pa.string())),
            ('scene_group',pa.string()),('condition',pa.string()),('difficulty',pa.int32()),('question',pa.string()),
            ('inputs_json',pa.string()),('images',pa.list_(pa.binary())),('record_json',pa.string())])
        pq.write_table(pa.Table.from_pylist(public,schema=schema),root/f'{part}.parquet',compression='zstd')
        # Answers are never added to evaluation observations. Training authority
        # can be joined by ID by the owner who is preparing supervised batches.
        private=root/'authority';private.mkdir(exist_ok=True)
        authority=[{'id':r['id'],'authority_json':json.dumps(r,ensure_ascii=False)} for r in read_rows(source/part/'authority.jsonl')]
        pq.write_table(pa.Table.from_pylist(authority,schema=pa.schema([('id',pa.string()),('authority_json',pa.string())])),private/f'{part}.parquet',compression='zstd')
        counts[part]=len(rows)
    write_json(root/'manifest.json',{'items':counts,'images':'embedded PNG bytes','authority':'separate owner-only directory','source_manifest':json.loads((source/'manifest.json').read_text(encoding='utf8'))})
    return {'parquet':str(root),'items':counts}
