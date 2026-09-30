"""Live training events and browser dashboard, backed by append-only JSONL."""
import json
import time
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
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


PAGE='''<!doctype html><meta charset="utf-8"><title>BenchForge Training</title>
<style>body{font:16px system-ui;margin:36px;background:#f7f7f4;color:#222}h1{font-size:28px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd}pre{white-space:pre-wrap}svg{background:white;width:100%;height:230px}small{color:#666}</style>
<h1>空间能力课程训练</h1><p id="state">等待训练事件</p><svg id="curve" viewBox="0 0 1000 230"></svg><p id="summary"></p>
<p><button onclick="guide({pause:true})">暂停更新</button> <button onclick="guide({pause:false})">继续更新</button> <button onclick="guide({stop_after_window:true})">本窗口后保存并停止</button></p>
<h2>能力与课程</h2><table><thead><tr><th>能力 / 条件</th><th>开发成功率</th><th>场景数</th><th>指导</th></tr></thead><tbody id="skills"></tbody></table>
<h2>最近事件</h2><pre id="events"></pre><small>程序真值评分。开发反馈用于选课，封存测试不进入调度。</small>
<script>async function guide(settings){await fetch('/api/guidance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});refresh()}async function refresh(){const data=await(await fetch('/api/state')).json();const rows=data.events;document.getElementById('state').textContent=data.latest?data.latest.event+' · '+data.latest.time:'等待训练事件';
const loss=rows.filter(r=>r.loss!==undefined);const svg=document.getElementById('curve');svg.replaceChildren();if(loss.length){let max=Math.max(...loss.map(r=>r.loss),.01);let line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',loss.map((r,i)=>(20+960*i/Math.max(1,loss.length-1))+','+(210-190*r.loss/max)).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#2b6b77');line.setAttribute('stroke-width','2');svg.appendChild(line);document.getElementById('summary').textContent='更新步 '+loss.at(-1).step+' · Loss '+loss.at(-1).loss.toFixed(4)}
const dev=rows.filter(r=>r.event==='development').at(-1);const tbody=document.getElementById('skills');tbody.replaceChildren();if(dev)for(const [k,v]of Object.entries(dev.mastery)){let tr=document.createElement('tr');for(const x of [k,(100*v.success_rate).toFixed(1)+'%',v.scene_count,v.promote?'升级':v.regression>.03?'增加保持训练':'当前课程']){let td=document.createElement('td');td.textContent=x;tr.appendChild(td)}tbody.appendChild(tr)}document.getElementById('events').textContent=rows.slice(-8).map(r=>JSON.stringify(r)).join('\\n');}refresh();setInterval(refresh,2000)</script>'''


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
            elif route=='/':body=PAGE.encode();mime='text/html'
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
