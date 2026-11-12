import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createCaptureWatcher, deliverCaptureNotice, compactCaptureObservation} from '../plugin/capture_watch.mjs';
import {createLegacyCaptureStep,createScopedCaptureObservations} from '../plugin/capture_runtime.mjs';

const observation=(state='RUNNING')=>({run_id:'sf_test',state,terminal:state==='FAILED_FINAL',tasks:[{
  id:'sf_test.scene0',state,phase:'capture',revision:0,
  ...(state==='FAILED_FINAL'?{failure:{stage:'capture_transport',error:'Isaac exited'}}:{})}]});

test('native observe packets without an inspect unit survive the lossless tool transport',()=>{
  for(const state of ['RUNNING','SUCCEEDED','FAILED_FINAL']) {
    const raw={run_id:'sf_native',state,tasks:[{id:'sf_native.scene0',state,
      progress:{stage:state==='RUNNING'?'capture':'complete'},
      ...(state==='FAILED_FINAL'?{failure:{stage:'review',error:'Shelf remains dark'}}:{})}]};
    const value=compactCaptureObservation(raw);
    assert.deepEqual(value,JSON.parse(JSON.stringify(value)));
    assert.deepEqual(compactCaptureObservation(value),JSON.parse(JSON.stringify(value)));
    assert.equal(value.tasks[0].state,state);
    if(state==='FAILED_FINAL')assert.equal(value.tasks[0].failure.error,'Shelf remains dark');
  }
  const missingRun=compactCaptureObservation({state:'RUNNING',tasks:[]});
  assert.deepEqual(missingRun,JSON.parse(JSON.stringify(missingRun)));
});

test('failed quality summaries retain every defect without repeating the saved scene narrative',()=>{
  const raw={run_id:'sf_native',state:'FAILED_FINAL',tasks:[{id:'sf_native.scene0',state:'FAILED_FINAL',failure:{
    next_action:'repair_complete_program_and_resubmit',artifacts_preserved:'/native/revision_0',
    scene_review:{acceptable:false,issues:['Shelf remains dark'],repair_suggestions:['Add shelf lighting'],
      scene_brief:{summary:'A long saved narrative'},brief_alignment:{passed:false,relation_checks:[{index:3,passed:false,view:'view_3.png',observation:'Shelf base cannot be seen'}]}}}}]};
  const value=compactCaptureObservation(raw);
  assert.equal(value.tasks[0].failure.next_action,'repair_complete_program_and_resubmit');
  assert.deepEqual(value.tasks[0].failure.scene_review.issues,['Shelf remains dark']);
  assert.deepEqual(value.tasks[0].failure.scene_review.repair_suggestions,['Add shelf lighting']);
  assert.equal(value.tasks[0].failure.scene_review.scene_brief,undefined);
  assert.ok(value.tasks[0].diagnostics.some(row=>row.view==='view_3.png' && row.passed===false && row.observation==='Shelf base cannot be seen'));
  assert.deepEqual(compactCaptureObservation(value),value);
  assert.equal(raw.tasks[0].failure.scene_review.scene_brief.summary,'A long saved narrative');
});

test('pending machine failures are replaced by current results without touching human instructions',()=>{
  const human={id:'human',source:{kind:'user'},content:[{type:'text',text:'Keep the original design'}]};
  const queue=[human];const step=[],woken=[];let sequence=0;
  const agent={status:'running',followup:value=>woken.push(value),inbox:{nextTurn:queue,nextStep:step,
    append:(target,value)=>(target==='next-step'?step:queue).push(value),
    remove:id=>{for(const rows of [queue,step]){const index=rows.findIndex(value=>value.id===id);if(index>=0){rows.splice(index,1);return true;}}return false;},
    replace:(id,value)=>{for(const rows of [queue,step]){const index=rows.findIndex(value=>value.id===id);if(index>=0){rows[index]=value;return true;}}return false;}}};
  const create=value=>({...value,id:'machine-'+(++sequence)});
  deliverCaptureNotice(agent,{run_id:'sf_test',started_at:1,state:'FAILED_FINAL'},create);
  deliverCaptureNotice(agent,{run_id:'sf_test',started_at:2,state:'SUCCEEDED'},create);
  deliverCaptureNotice(agent,{run_id:'sf_test',started_at:1,state:'FAILED_FINAL'},create);
  assert.deepEqual(queue,[human]);assert.equal(step.length,1);assert.match(step[0].content[0].text,/SUCCEEDED/);
  assert.equal(woken.length,0);
  agent.status='idle';deliverCaptureNotice(agent,{run_id:'sf_other',started_at:3,state:'SUCCEEDED'},create);
  assert.equal(woken.length,1);
});

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

function retainedObservationScope(id) {
  const hooks=new Set(),agent={id},definitions=new Map();
  for(const name of ['spatialforge_status','spatialforge_wait','spatialforge_evidence'])definitions.set(name,
    Object.freeze({name,description:'Retained '+name,parameters:{},output:{render:JSON.stringify}}));
  const tools={get:(name,scope)=>{assert.equal(scope,agent);return definitions.get(name);},
    register:()=>assert.fail('Existing tool registrations must stay intact')};
  agent.ctx={get:name=>name==='tools'?tools:undefined,on:(name,callback)=>{
    assert.equal(name,'tools/execute');hooks.add(callback);return ()=>hooks.delete(callback);
  }};
  const dispatch=async(name,args)=>{
    const exec=Object.freeze({agent,name,arguments:Object.freeze({...args}),signal:new AbortController().signal});
    const listeners=[...hooks];let index=0;
    const next=()=>index<listeners.length?listeners[index++](exec,next):assert.fail('Expected the current observation hook');
    return next();
  };
  return {agent,hooks,definitions,dispatch};
}

test('a retained caller receives concise observations, full detail and background receipts through one public hook',async(t)=>{
  const raw={...observation('FAILED_FINAL'),tasks:[{...observation('FAILED_FINAL').tasks[0],
    progress:{stage:'review',scene_review:{narrative:'large repeated review',issues:['lamp support remains unresolved']}},
    result:{scene_review:{acceptable:false,issues:['lamp support remains unresolved'],description:'large repeated review'}}}]};
  const scope=retainedObservationScope('session-old');
  const retained=scope.definitions.get('spatialforge_wait');
  let watched=0;
  const adapters=createScopedCaptureObservations({read:async()=>({...raw,cursor:'version'}),
    watch:async()=>{watched++;return {run_id:'sf_test',state:'RUNNING',tasks:[],watch:{accepted:true}};}});
  t.after(()=>adapters.dispose());
  adapters.install(scope.agent);adapters.install(scope.agent);
  assert.equal(scope.hooks.size,1);
  assert.equal(scope.definitions.get('spatialforge_wait'),retained);
  const concise=await scope.dispatch('spatialforge_status',{run_id:'sf_test'});
  assert.equal(concise.isError,false);assert.deepEqual(concise.content,[]);
  assert.equal(concise.value.tasks[0].result.scene_review,undefined);
  assert.equal(concise.value.tasks[0].failure.error,'Isaac exited');
  assert.ok(concise.value.tasks[0].diagnostics.some(row=>row.acceptable===false));
  assert.deepEqual((await scope.dispatch('spatialforge_status',{run_id:'sf_test',detail:true})).value,raw);
  assert.equal((await scope.dispatch('spatialforge_wait',{run_id:'sf_test',background:true})).value.watch.accepted,true);
  assert.equal(watched,1);
  adapters.dispose();assert.equal(scope.hooks.size,0);
  assert.equal(scope.definitions.size,3);
});

test('identifier aliases resolve only the one task actually returned by the native run',async(t)=>{
  const scope=retainedObservationScope('session-alias');
  let packet=observation('FAILED_FINAL'),last;
  const adapters=createScopedCaptureObservations({read:async(_route,args)=>{last=args;return packet;},
    watch:async()=>({}),evidence:async args=>args});
  t.after(()=>adapters.dispose());
  adapters.install(scope.agent);
  await scope.dispatch('spatialforge_status',{run_id:'sf_test.scene0'});
  assert.equal(last.run_id,'sf_test');
  assert.equal((await scope.dispatch('spatialforge_evidence',{task_id:'sf_test'})).value.task_id,'sf_test.scene0');
  packet={...packet,tasks:[...packet.tasks,{...packet.tasks[0],id:'sf_test.scene1'}]};
  await assert.rejects(scope.dispatch('spatialforge_evidence',{task_id:'sf_test'}),/Choose the exact task_id/);
  adapters.dispose();assert.equal(scope.hooks.size,0);
});
