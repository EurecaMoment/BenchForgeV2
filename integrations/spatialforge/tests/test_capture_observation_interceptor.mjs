import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {attachCaptureRuntime,createScopedCaptureObservations,createCaptureEvidence} from '../plugin/capture_runtime.mjs';

function fixture() {
  const hooks=new Set();
  let disposed=0;
  const agent={ctx:{get(name) {
    if(name==='tools')return {
      get:()=>({name:'retained orphan definition'}),
      register:()=>{throw Error('orphan registration must never be replaced');}
    };
  },on(name,callback) {
    assert.equal(name,'tools/execute');
    hooks.add(callback);
    let active=true;
    return ()=>{if(active){active=false;hooks.delete(callback);disposed++;}};
  }}};
  async function call(name,args={},caller=agent,signal=new AbortController().signal) {
    const listeners=[...hooks];
    const exec=Object.freeze({name,arguments:Object.freeze({...args}),agent:caller,signal});
    let index=0;
    const next=()=>index<listeners.length?listeners[index++](exec,next):Promise.resolve({fallback:true});
    return {result:await next(),exec};
  }
  return {agent,hooks,call,get disposed(){return disposed;}};
}

const observation=()=>({run_id:'sf_test',state:'RUNNING',cursor:7,tasks:[{id:'sf_test.scene0',state:'RUNNING',result:{program:{large:true}}}]});

test('workbench capture runtime follows the projected client pointer and keeps the server workspace', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-workbench-config-'));
  t.after(() => fs.rm(root, {recursive: true, force: true}));
  const client = path.join(root, 'client.json');
  const server = path.join(root, 'server');
  await fs.mkdir(server);
  await fs.writeFile(path.join(server, 'service.json'), JSON.stringify({
    service_url: 'https://fixture.invalid', execution_mode: 'exploration', operator_token: 'default-token',
  }));
  await fs.writeFile(client, JSON.stringify({
    service_config: 'server/service.json', operator_token: 'fixture-token',
  }));
  const hooks = new Map(), cleanup = [];
  const ctx = {
    get: () => undefined,
    on: (name, callback) => hooks.set(name, callback),
    effect: effect => cleanup.push(effect()),
  };
  t.after(() => cleanup.reverse().forEach(dispose => dispose()));
  await attachCaptureRuntime(ctx, {productionConfig: client, productionPython: 'python3'});
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push([url, options.headers.Authorization]);
    return Response.json(observation());
  });

  const agent = {id: 'session-fixture', session: {header: {cwd: server}}, ctx: {
    get: () => ({get: () => true}),
    on: (_, hook) => {hooks.set('tools/execute', hook); return () => {};},
  }};
  await hooks.get('agent/pre-step')({agent, signal: new AbortController().signal}, async () => ({messages: []}));
  assert.ok(hooks.has('tools/execute'));
  await hooks.get('tools/execute')({agent, name: 'spatialforge_status', arguments: {run_id: 'sf_test'},
    signal: new AbortController().signal}, async () => assert.fail('workbench must use its configured service'));
  assert.deepEqual(calls, [['https://fixture.invalid/observe', 'Bearer fixture-token']]);
});

test('status uses current bridge with immutable args and preserves full detail on request',async()=>{
  const f=fixture(),reads=[];
  const runtime=createScopedCaptureObservations({read:async(route,args,signal)=>{
    reads.push({route,args,signal});return observation();
  },watch:async()=>{throw Error('unexpected watch');}});
  runtime.install(f.agent);
  const {result,exec}=await f.call('spatialforge_status',{run_id:'sf_test.scene0',cursor:123});
  assert.equal(result.isError,false);
  assert.deepEqual(result.content,[]);
  assert.equal(reads[0].route,'/observe');
  assert.deepEqual(reads[0].args,{run_id:'sf_test'});
  assert.equal(reads[0].signal,exec.signal);
  assert.equal(exec.arguments.run_id,'sf_test.scene0');
  assert.equal(exec.arguments.cursor,123);
  assert.equal('cursor' in result.value,false);
  assert.equal('program' in result.value.tasks[0].result,false);
  const detailed=await f.call('spatialforge_status',{run_id:'sf_test',detail:true});
  assert.equal(reads[1].route,'/inspect');
  assert.deepEqual(detailed.result.value.tasks[0].result.program,{large:true});
  runtime.dispose();
});

test('background wait returns the receipt and synchronous wait forwards the bounded request',async()=>{
  const f=fixture(),reads=[],watches=[];
  const runtime=createScopedCaptureObservations({read:async(route,args)=>{
    reads.push({route,args});return observation();
  },watch:async(args,exec)=>{watches.push({args,exec});return {...observation(),watch:{accepted:true}};}});
  runtime.install(f.agent);
  const background=await f.call('spatialforge_wait',{run_id:'sf_test.scene0',background:true});
  assert.deepEqual(watches[0].args,{run_id:'sf_test'});
  assert.equal(watches[0].exec,background.exec);
  assert.equal(background.result.value.watch.accepted,true);
  assert.equal(reads.length,0);
  await f.call('spatialforge_wait',{run_id:'sf_test',background:false,timeout_seconds:5,cursor:2});
  assert.deepEqual(reads,[{route:'/wait',args:{run_id:'sf_test',timeout_seconds:5}}]);
  runtime.dispose();
});

test('evidence resolves one actual task and refuses an ambiguous multi-task run',async()=>{
  const f=fixture(),evidence=[];
  let tasks=[{id:'sf_test.scene0'}];
  const runtime=createScopedCaptureObservations({read:async()=>({...observation(),tasks}),watch:async()=>{},
    evidence:async(args)=>{evidence.push(args);return {task_id:args.task_id,files:['report.json']};}});
  runtime.install(f.agent);
  const result=await f.call('spatialforge_evidence',{task_id:'sf_test',file:'report.json'});
  assert.equal(result.exec.arguments.task_id,'sf_test');
  assert.equal(result.result.value.task_id,'sf_test.scene0');
  assert.deepEqual(evidence[0],{task_id:'sf_test.scene0',file:'report.json'});
  tasks=[{id:'sf_test.scene0'},{id:'sf_test.scene1'}];
  await assert.rejects(f.call('spatialforge_evidence',{task_id:'sf_test'}),/Choose the exact task_id/);
  assert.equal(evidence.length,1);
  runtime.dispose();
});

test('hook never intercepts another Agent or unrelated tools',async()=>{
  const f=fixture();
  const runtime=createScopedCaptureObservations({read:async()=>{throw Error('unexpected read');},watch:async()=>{}});
  runtime.install(f.agent);
  assert.deepEqual((await f.call('spatialforge_status',{run_id:'sf_test'},{})).result,{fallback:true});
  assert.deepEqual((await f.call('task_code',{})).result,{fallback:true});
  runtime.dispose();
});

test('runtime generations replace only owned hooks and cleanup is idempotent',async()=>{
  const f=fixture();
  const first=createScopedCaptureObservations({read:async()=>observation(),watch:async()=>{}});
  const second=createScopedCaptureObservations({read:async()=>({...observation(),state:'SUCCEEDED'}),watch:async()=>{}});
  first.install(f.agent);first.install(f.agent);
  assert.equal(f.hooks.size,1);
  second.install(f.agent);
  assert.equal(f.hooks.size,1);
  assert.equal(f.disposed,1);
  first.dispose();first.dispose();
  assert.equal(f.hooks.size,1);
  assert.equal((await f.call('spatialforge_status',{run_id:'sf_test'})).result.value.state,'SUCCEEDED');
  second.dispose();second.dispose();
  assert.equal(f.hooks.size,0);
  assert.equal(f.disposed,2);
});

test('cancellation and bridge failures cannot become successful observation values',async()=>{
  const f=fixture(),failure=Error('native bridge unavailable');
  let reads=0;
  const runtime=createScopedCaptureObservations({read:async()=>{reads++;throw failure;},watch:async()=>{}});
  runtime.install(f.agent);
  const controller=new AbortController();controller.abort();
  await assert.rejects(f.call('spatialforge_status',{run_id:'sf_test'},f.agent,controller.signal),{name:'AbortError'});
  assert.equal(reads,0);
  await assert.rejects(f.call('spatialforge_status',{run_id:'sf_test'}),error=>error===failure);
  assert.equal(reads,1);
  runtime.dispose();
});

test('native JSON evidence stays on its existing API route',async()=>{
  const apiCalls=[];
  const evidence=createCaptureEvidence({api:async(route,args,signal)=>{
    apiCalls.push({route,args,signal});return {task_id:args.task_id,files:['report.json']};
  }});
  const signal=new AbortController().signal;
  assert.deepEqual(await evidence({task_id:'sf_test.scene0'},{signal}),{task_id:'sf_test.scene0',files:['report.json']});
  assert.equal(apiCalls[0].route,'/evidence');
  assert.equal(apiCalls[0].signal,signal);
});
