import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createCaptureWatcher} from '../plugin/capture_watch.mjs';
import {createLegacyCaptureStep} from '../plugin/capture_runtime.mjs';

const observation=(state='RUNNING')=>({run_id:'sf_test',state,terminal:state==='FAILED_FINAL',tasks:[{
  id:'sf_test.scene0',state,phase:'capture',revision:0,
  ...(state==='FAILED_FINAL'?{failure:{stage:'capture_transport',error:'Isaac exited'}}:{})}]});

test('one native background wait wakes only its owner once and retains the failed outcome',async(t)=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'capture-watch-'));
  let finish;const waiting=new Promise(resolve=>finish=resolve),calls=[],messages=[];
  const watch=createCaptureWatcher({artifacts:root,read:async(route,args)=>{
    calls.push({route,args});return route==='/observe'?observation():waiting;
  },notify:async(agent,record)=>messages.push({agent,record:structuredClone(record)})});
  t.after(async()=>{await watch.whenSettled();await fs.rm(root,{recursive:true,force:true});});
  const agent={id:'session-parent'},abort=new AbortController(),exec={agent,signal:abort.signal};
  const registered=await watch({run_id:'sf_test'},exec);
  assert.equal(registered.watch.background,true);assert.equal(registered.state,'RUNNING');
  assert.equal(messages.length,0);
  const duplicate=await watch({run_id:'sf_test'},exec);
  assert.equal(duplicate.watch.receipt_path,registered.watch.receipt_path);
  assert.equal(calls.filter(c=>c.route==='/observe').length,1);
  abort.abort(); // The originating turn can finish without canceling the observer.
  finish(observation('FAILED_FINAL'));await watch.whenSettled();
  assert.equal(messages.length,1);assert.equal(messages[0].agent,agent);
  assert.equal(messages[0].record.observation.state,'FAILED_FINAL');
  assert.equal(messages[0].record.observation.tasks[0].failure.error,'Isaac exited');
  assert.equal(calls.filter(c=>c.route==='/wait').length,1);
});

test('already terminal captures return immediately without registering or notifying',async(t)=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'capture-terminal-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const watch=createCaptureWatcher({artifacts:root,read:async()=>observation('FAILED_FINAL'),notify:()=>assert.fail('duplicate notification')});
  const result=await watch({run_id:'sf_test'},{agent:{id:'session-parent'}});
  assert.equal(result.terminal,true);assert.equal(result.watch,undefined);
  assert.deepEqual(await fs.readdir(root),[]);
});

test('observer errors produce one actionable notice instead of polling or claiming success',async(t)=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'capture-error-'));let calls=0,result;
  const watch=createCaptureWatcher({artifacts:root,read:async()=>{
    if(++calls===1)return observation();throw new Error('Native service unavailable');
  },notify:async(_agent,record)=>result=structuredClone(record)});
  t.after(async()=>{await watch.whenSettled();await fs.rm(root,{recursive:true,force:true});});
  await watch({run_id:'sf_test'},{agent:{id:'session-parent'}});await watch.whenSettled();
  assert.equal(result.state,'observer_failed');assert.equal(result.observation.state,'RUNNING');
  assert.equal(result.error,'Native service unavailable');assert.equal(calls,2);
});

test('an already-bound old parent automatically gets one background receipt after native capture',async()=>{
  const events=[{type:'tool/call',data:{name:'spatialforge_capture',callId:'capture-1',arguments:'{}'}},
    {type:'tool/result',data:{message:{toolCallId:'capture-1',content:[{type:'text',text:'{"run_id":"sf_test"}'}]}}}];
  const agent={id:'session-parent',session:{header:{},snapshotEvents:()=>events},ctx:{get:()=>({get:()=>({description:'Legacy bounded wait'})})}};
  let watches=0;
  const hook=createLegacyCaptureStep({watch:async()=>{watches++;return {...observation(),watch:{accepted:true,background:true}};},createMessage:value=>value});
  const result=await hook({agent},async()=>({kind:'enter',messages:[]}));
  assert.equal(result.messages.length,1);assert.match(result.messages[0].content[0].text,/不再逐分钟模型轮询/);
  assert.equal(result.messages[0].source.kind,'spatialforge/capture-runtime');
  assert.equal((await hook({agent},async()=>({kind:'enter',messages:[]}))).messages.length,0);
  assert.equal(watches,1);
});

test('legacy retry rejection is recovered once through canonical validation and cannot hide quality failure',async()=>{
  const events=[{type:'tool/call',data:{name:'spatialforge_retry',callId:'retry-1',arguments:'{"task_id":"sf_test.scene0"}'}},
    {type:'tool/result',data:{message:{toolCallId:'retry-1',isError:true,content:[{type:'text',text:'Unreviewed scene retries require an admitted native capture'}]}}}];
  const agent={id:'session-parent',session:{header:{},snapshotEvents:()=>events},ctx:{get:()=>({get:()=>({description:'Legacy bounded wait'})})}};
  let recovered=0;
  const hook=createLegacyCaptureStep({recover:async args=>{recovered++;assert.equal(args.task_id,'sf_test.scene0');throw new Error('repair scene quality through capture/refine');},
    watch:()=>assert.fail('Quality failure must not be queued'),createMessage:value=>value});
  const result=await hook({agent},async()=>({kind:'enter',messages:[]}));
  assert.equal(recovered,1);assert.match(result.messages[0].content[0].text,/恢复尚未完成/);
  assert.match(result.messages[0].content[0].text,/repair scene quality/);
});
