"""Live training events and browser dashboard, backed by append-only JSONL."""
import json
import time
from datetime import datetime
from datetime import timezone
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def emit(run,event,**fields):
    path=Path(run)/'events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    row={'time':datetime.now(timezone.utc).isoformat(),'event':event,**fields}
    with path.open('a',encoding='utf8') as handle:handle.write(json.dumps(row,ensure_ascii=False)+'\n')
    return row


def snapshot(run):
    path=Path(run)/'events.jsonl'
    events=[]
    if path.exists():
        with path.open(encoding='utf8') as handle:
            for line in handle:
                if line.endswith('\n'):events.append(json.loads(line))
    return {'events':events,'latest':events[-1] if events else None}


def guide(run,settings):
    path=Path(run)/'guidance.json'
    existing=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    existing.update(settings)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding='utf8')
    emit(run,'guidance_received',settings=settings)
    return existing




def serve(run,host='127.0.0.1',port=8767):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if urlparse(self.path).path!='/api/guidance':self.send_error(404);return
            settings=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            body=json.dumps(guide(run,settings)).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            route=urlparse(self.path).path
            if route=='/api/state':body=json.dumps(snapshot(run),ensure_ascii=False).encode();mime='application/json'
            elif route in ('/', '/monitor.js', '/styles.css'):
                names = {'/': ('index.html', 'text/html'), '/monitor.js': ('monitor.js', 'text/javascript'), '/styles.css': ('styles.css', 'text/css')}
                name, mime = names[route]
                body = (Path(__file__).resolve().parents[2] / 'client' / name).read_bytes()
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    ThreadingHTTPServer((host,port),Handler).serve_forever()


def monitor(args,directory,config=None):
    if args.get('guidance') is not None:guide(args['run'],args['guidance'])
    return snapshot(args['run'])


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args();serve(args.run,args.host,args.port)
