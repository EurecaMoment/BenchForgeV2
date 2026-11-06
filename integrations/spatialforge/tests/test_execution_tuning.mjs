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

test('a reasoning-only native response reports decoding latency without claiming production progress',async t=>{
  const f=await fixture(t);
  f.agent.status='idle';
  f.agent.session.snapshotEvents=()=>[
    {type:'step/start',time:1000,data:{turn:1,step:1}},
    {type:'request/header',time:1001,data:{}},
    {type:'assistant/message',time:11000,data:{turn:1,step:1,usage:{inputTokens:48179,outputTokens:800},
      message:{content:[{type:'reasoning',text:'This private text must not be returned.'}]},stream:[{type:'reasoning-chunks',time0:3000}]}},
    {type:'turn/end',time:11001,data:{turn:1}},
  ];
  const value=await f.tuning.observe(f.root,f.agent.id),step=value.recent_steps[0];
  assert.equal(step.seconds,10);assert.equal(step.first_stream_seconds,2);
  assert.equal(step.output_tokens_per_second,100);assert.equal(step.reasoning_only,true);
  assert.equal(value.current_activity.phase,'idle');assert.equal(value.current_activity.production_complete,undefined);
  assert.ok(!JSON.stringify(value).includes('private text'));
});

test('a current native model request and paired tool call expose their actual active phase',async t=>{
  const f=await fixture(t),time=Date.now()-1000;
  const rows=[{type:'step/start',time,data:{turn:2,step:3}},{type:'request/header',time,data:{}}];
  f.agent.session.snapshotEvents=()=>rows;
  let value=await f.tuning.observe(f.root,f.agent.id);
  assert.equal(value.current_activity.phase,'model');assert.ok(value.current_activity.elapsed_seconds>=1);
  rows.push({type:'tool/call',time,data:{callId:'capture-one',name:'spatialforge_capture'}});
  value=await f.tuning.observe(f.root,f.agent.id);
  assert.equal(value.current_activity.phase,'tool');assert.equal(value.current_activity.active_tools[0].name,'spatialforge_capture');
  rows.push({type:'tool/result',time,data:{message:{toolCallId:'capture-one'}}});
  assert.equal((await f.tuning.observe(f.root,f.agent.id)).current_activity.phase,'between_steps');
});

test('a checkpoint gets a concise final directive without rewriting ordinary calls, config or the cached prefix',async t=>{
  const f=await fixture(t),signal=new AbortController().signal;
  await f.tuning.arm(f.root,f.agent.id,{reasoning_effort:'high',compact_history:true},signal);
  const hook=f.handlers.get('llm/stream');let dispatched=0;
  const runtime={stream:options=>hook.call(runtime,options,()=>{dispatched++;return options;})};
  const prefix={role:'user',content:[{type:'text',text:'saved user requirements'}]};
  const call={...f.current,sessionId:f.agent.id,purpose:'compaction',messages:[prefix,{role:'user',content:[{type:'text',text:'You are now acting as a compaction engine.'}]}]};
  const before=structuredClone(call),bounded=runtime.stream(call);
  assert.deepEqual(call,before);assert.equal(bounded.messages[0],prefix);
  assert.equal(bounded.maxTokens,call.maxTokens);assert.equal(bounded.model,call.model);
  assert.match(bounded.messages.at(-1).content[0].text,/1500 tokens/);assert.equal(dispatched,1);
  const normal={...call,purpose:undefined};assert.equal(runtime.stream(normal),normal);
  const other={...call,sessionId:'session-other'};assert.equal(runtime.stream(other),other);
  const frozen=Object.freeze({...call});assert.equal(runtime.stream(frozen),frozen);
});
