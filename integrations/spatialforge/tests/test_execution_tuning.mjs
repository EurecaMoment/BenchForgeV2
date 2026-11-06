import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createExecutionTuning} from '../plugin/execution_tuning.mjs';

async function fixture(t) {
  const root=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'execution-tuning-')));
  const current={provider:'qwen-flash',model:'Qwen/test',reasoningEffort:'max',maxTokens:48000,temperature:0.6};
  const agent={id:'session-parent',status:'running',session:{header:{id:'session-parent',cwd:root},
    requestHeader:()=>({config:current}),snapshotEvents:()=>[]},whenIdle:()=>{throw new Error('Running production must not be stopped');}};
  const handlers=new Map(),agents=new Map([[agent.id,agent]]),calls=[];
  const services={agents,llm:{resolveModelInfo:async()=>({reasoning:{efforts:[{id:'high'},{id:'max'}]}})},
    agentDefaultModel:{saveSelection:()=>assert.fail('Host model settings must stay unchanged')},
    compaction:{compactNow:()=>assert.fail('No idle compaction while production runs'),compactRegion:async(start,end)=>{
      calls.push([start,end]);return {shadowedTokenCount:500000,summarySeq:55};
    }},tokenMeter:{measure:()=>({nodes:[{seq:0,tokens:1000},{seq:11,tokens:500000},{seq:32,tokens:500},{seq:8,tokens:33000}]})}};
  const ctx={get:name=>services[name],on:(name,handler)=>{handlers.set(name,handler);return ()=>handlers.delete(name);}};
  agent.ctx=ctx;agent.session.surface={nodes:[0,11,32,8]};
  agent.session.eventAt=seq=>({seq,type:seq===0?'system/message':seq===11?'user/message':'tool/result'});
  const pairing={toolPairingBalancedBefore:(_session,seq)=>seq!==8,toolPairingBalancedAfter:(_session,seq)=>seq===11};
  const tuning=createExecutionTuning({ctx,pairing});
  t.after(async()=>{
    await tuning.dispose();
    const relative=path.relative(await fs.realpath(os.tmpdir()),root);
    assert.ok(relative && !relative.startsWith('..') && path.basename(root).startsWith('execution-tuning-'));
    await fs.rm(root,{recursive:true,force:true});
  });
  return {root,current,agent,agents,handlers,tuning,calls,services};
}

test('a single advertised effort change preserves route and output limits, and needs an admitted native header',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  await f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high'},signal);
  const changed=await f.handlers.get('agent/request')({agent:f.agent,turn:1,step:2,signal},async()=>f.current);
  assert.deepEqual(changed,{...f.current,reasoningEffort:'high'});
  assert.equal((await f.tuning.observe(f.root,f.agent.id)).policy.state,'prepared');
  await f.handlers.get('session/event')({id:f.agent.id},{type:'request/header',time:8,seq:12,data:{header:{config:changed}}});
  assert.equal((await f.tuning.observe(f.root,f.agent.id)).policy.state,'applied');
  // An explicit later model choice is not forcibly overwritten.
  assert.equal(await f.handlers.get('agent/request')({agent:f.agent,signal},async()=>f.current),f.current);
});

test('another workspace, subagent or model without high cannot be adjusted',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  await assert.rejects(f.tuning.arm(path.join(f.root,'other'),f.agent.id,{reasoning_effort:'high'},signal));
  f.agent.session.header.origin='subagent';
  await assert.rejects(f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high'},signal),/parent is unavailable/);
  delete f.agent.session.header.origin;
  f.services.llm.resolveModelInfo=async()=>({reasoning:{efforts:[{id:'max'}]}});
  await assert.rejects(f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high'},signal),/does not advertise/);
});

test('a changed native selection wins before the requested adjustment',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  await f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high'},signal);
  const other={...f.current,model:'other'};
  assert.equal(await f.handlers.get('agent/request')({agent:f.agent,signal},async()=>other),other);
  assert.equal((await f.tuning.observe(f.root,f.agent.id)).policy.state,'superseded');
});

test('history reduction waits for a step boundary, retains the system and recent tail, and keeps tool pairs together',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  await f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high',compact_history:true},signal);
  assert.deepEqual(f.calls,[]);
  let continued=false;
  await f.handlers.get('agent/pre-step')({agent:f.agent,signal},async()=>{continued=true;return {kind:'enter'};});
  assert.deepEqual(f.calls,[[11,11]]);
  assert.equal(continued,true);
  const record=(await f.tuning.observe(f.root,f.agent.id)).policy;
  assert.equal(record.compact.state,'complete');
  assert.equal(record.compact.shadowed_tokens,500000);
  assert.ok(record.compact.retained_tokens>=32768);
  await f.handlers.get('agent/pre-step')({agent:f.agent,signal},async()=>({kind:'enter'}));
  assert.equal(f.calls.length,1);
});

test('an isolated preset uses its registered idle-only command and records native completion',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  delete f.services.compaction;delete f.services.tokenMeter;
  f.agent.status='idle';f.agent.whenIdle=async()=>{};
  let finish,started;
  const ready=new Promise(resolve=>started=resolve),pending=new Promise(resolve=>finish=resolve);
  f.services.commands={find:()=>({name:'compact'}),execute:async(agent,line,attachments)=>{
    assert.equal(agent,f.agent);assert.equal(line,'/compact');assert.deepEqual(attachments,[]);
    started();return pending;
  }};
  await f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high',compact_history:true},signal);
  await ready;
  finish({commandId:'native-command',result:{kind:'success',text:'Compacted native history.',sourceEventSeq:41}});
  // A subsequent status event cannot start a second maintenance command.
  await new Promise(resolve=>setTimeout(resolve,30));
  const record=(await f.tuning.observe(f.root,f.agent.id)).policy;
  assert.equal(record.compact.state,'complete');assert.equal(record.compact.summary_seq,41);
});

test('status reconciles an external compact only after its native successful command pair has a summary',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  const receipt=await f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high',compact_history:true},signal);
  const run={type:'command/run',time:receipt.requested_at+1,data:{name:'compact',commandId:'external'}};
  f.agent.session.snapshotEvents=()=>[run,{type:'command/done',time:receipt.requested_at+2,data:{commandId:'external',kind:'error'}}];
  assert.notEqual((await f.tuning.observe(f.root,f.agent.id)).policy.compact.state,'complete');
  f.agent.session.snapshotEvents=()=>[run,{type:'command/done',time:receipt.requested_at+3,data:{commandId:'external',kind:'success',sourceEventSeq:45,text:'Compacted.'}}];
  assert.equal((await f.tuning.observe(f.root,f.agent.id)).policy.compact.summary_seq,45);
});
