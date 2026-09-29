import json
import sys
from pathlib import Path

from data_juicer.ops.mapper.clean_html_mapper import CleanHtmlMapper
from data_juicer.ops.mapper.clean_links_mapper import CleanLinksMapper
from data_juicer.ops.filter.text_length_filter import TextLengthFilter
from data_juicer.utils.constant import Fields

if __name__=='__main__':
    texts=json.loads(Path(sys.argv[1]).read_text())
    batch={'text':texts,Fields.stats:[{} for _ in texts]}
    for op in [CleanHtmlMapper(text_key='text'),CleanLinksMapper(text_key='text')]:batch=op.process_batched(batch)
    op=TextLengthFilter(min_len=1,max_len=20000,text_key='text');batch=op.compute_stats_batched(batch)
    Path(sys.argv[2]).write_text(json.dumps({'texts':batch['text'],'keep':list(op.process_batched(batch))}))
