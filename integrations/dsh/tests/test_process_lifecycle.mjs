import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {Context} from '@deepseek-ai/cordis';
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local';
import {invoke,apply,Config} from '../tools.mjs';

const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function fixture(t) {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'benchforge-lifecycle-'));
  const packageDir=path.join(root,'benchforge_core');
  await fs.mkdir(packageDir);
  await fs.writeFile(path.join(packageDir,'__init__.py'),'');
  await fs.writeFile(path.join(packageDir,'cli.py'),`import json,os,sys,signal,time,subprocess
from pathlib import Path
request=json.load(sys.stdin)
root=Path.cwd()
mode=request.get('mode','normal')
if mode=='normal':
 print(json.dumps({'sentinel':os.getenv('DSH_TEST_SENTINEL'),'explicit':os.getenv('EXPLICIT_TEST_TOKEN'),'cwd':str(root),'request':request}))
elif mode=='overflow':
 print(json.dumps({'value':'x'*10000}))
elif mode=='failure':
 print('expected targeted failure',file=sys.stderr);sys.exit(7)
elif mode=='background':
 import runpy
 start=runpy.run_path(os.environ['BENCHFORGE_TEST_OWNER'])['start_background']
 command=[sys.executable,'-c',"import time;from pathlib import Path;time.sleep(1);Path('background-finished').write_text('complete')"]
 print(json.dumps(start(command,cwd=root,log=root/'background.log')))
else:
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 child=subprocess.Popen([sys.executable,'-c',"import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('descendant.pid').write_text(str(os.getpid()));time.sleep(30)"])
 (root/'parent.pid').write_text(str(os.getpid()))
 time.sleep(30)
`);
  const ctx=new Context();
  const provider=await ctx.plugin(LocalSubprocessRuntime);
  t.after(async()=>{await provider.dispose();await fs.rm(root,{recursive:true,force:true});});
  return {root,ctx,options:{environment:{PYTHONPATH:root},graceMs:100,maxOutputBytes:1024}};
}
async function started(root) {
  const timeout=AbortSignal.timeout(5000);
  while(true) {
    timeout.throwIfAborted();
    try{return await Promise.all(['parent.pid','descendant.pid'].map(async name=>Number(await fs.readFile(path.join(root,name),'utf8'))));}
    catch(error){if(error.code!=='ENOENT')throw error;await pause(10);}
  }
}
async function live(pid) {
  if(process.platform==='linux') {
    try {const stat=await fs.readFile(`/proc/${pid}/stat`,'utf8');return !['Z','X'].includes(stat.slice(stat.lastIndexOf(')')+2).split(' ')[0]);}
    catch(error){if(error.code==='ENOENT')return false;throw error;}
  }
  try{process.kill(pid,0);return true;}catch(error){if(error.code==='ESRCH')return false;throw error;}
}

test('managed invoke scrubs ambient DSH state and preserves explicit opt-ins',async t=>{
  const f=await fixture(t),before=process.env.DSH_TEST_SENTINEL;
  process.env.DSH_TEST_SENTINEL='ambient-only';
  t.after(()=>{if(before===undefined)delete process.env.DSH_TEST_SENTINEL;else process.env.DSH_TEST_SENTINEL=before;});
  const value=await invoke(f.ctx.subprocess,'python3',f.root,undefined,'catalog',{mode:'normal'},undefined,
    {...f.options,environment:{...f.options.environment,EXPLICIT_TEST_TOKEN:'allowed-fixture'}});
  assert.equal(value.sentinel,null);assert.equal(value.explicit,'allowed-fixture');assert.equal(value.cwd,f.root);
  assert.equal(value.request.mode,'normal');
});
test('cancellation settles after TERM-resistant command and descendant are stopped',async t=>{
  const f=await fixture(t),control=new AbortController();
  const running=invoke(f.ctx.subprocess,'python3',f.root,undefined,'catalog',{mode:'resistant'},control.signal,f.options);
  const checked=assert.rejects(running,{name:'AbortError'});
  const pids=await started(f.root);control.abort();await checked;
  assert.deepEqual(await Promise.all(pids.map(live)),[false,false]);
});
test('plugin teardown joins owned work and cancels a live invocation',async t=>{
  const f=await fixture(t),tools=new Map();let dispose;
  await apply({tools:{register:tool=>tools.set(tool.name,tool)},subprocess:f.ctx.subprocess,
    effect:setup=>{dispose=setup();},get(){}},Config({python:'python3',includeTools:['catalog'],environment:{PYTHONPATH:f.root},graceMs:100}));
  const running=tools.get('benchforge_catalog').execute({workspace:f.root,mode:'resistant'},{signal:new AbortController().signal});
  const checked=assert.rejects(running,{name:'AbortError'}),pids=await started(f.root);
  await dispose();await checked;
  assert.deepEqual(await Promise.all(pids.map(live)),[false,false]);
});
test('pre-cancel starts no work; bounded JSON overflow and nonzero exit are explicit',async t=>{
  const f=await fixture(t),control=new AbortController();control.abort();
  await assert.rejects(invoke(f.ctx.subprocess,'python3',f.root,undefined,'catalog',{},control.signal,f.options),{name:'AbortError'});
  await assert.rejects(invoke(f.ctx.subprocess,'python3',f.root,undefined,'catalog',{mode:'overflow'},undefined,f.options),/maxOutputBytes/);
  await assert.rejects(invoke(f.ctx.subprocess,'python3',f.root,undefined,'catalog',{mode:'failure'},undefined,f.options),/expected targeted failure/);
  await assert.rejects(fs.stat(path.join(f.root,'parent.pid')),{code:'ENOENT'});
});
test('explicit background handoff survives CLI cleanup under its independent service', {skip:process.platform!=='linux'},async t=>{
  const f=await fixture(t);
  const helper=fileURLToPath(new URL('../../../src/benchforge_core/processes.py',import.meta.url));
  const value=await invoke(f.ctx.subprocess,'python3',f.root,undefined,'catalog',{mode:'background'},undefined,
    {...f.options,environment:{...f.options.environment,BENCHFORGE_TEST_OWNER:helper}});
  assert.equal(value.owner,'systemd-user');assert.ok(value.service.endsWith('.service'));
  assert.equal(await live(value.pid),true);
  await pause(1200);
  assert.equal(await fs.readFile(path.join(f.root,'background-finished'),'utf8'),'complete');
});
