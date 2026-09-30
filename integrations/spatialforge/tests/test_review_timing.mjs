import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createDeliveryReview, createCaptureReviewStep, pendingCapture} from '../plugin/delivery_review.mjs';

const turn={type:'turn/start',data:{turn:1}};
const step={type:'step/start',data:{turn:1,step:1}};
const value={run_id:'sf_example',task_id:'sf_example.scene0'};
const native=[{type:'tool/call',data:{name:'spatialforge_capture',callId:'capture'}},
  {type:'tool/result',data:{message:{toolCallId:'capture',content:[{type:'text',text:JSON.stringify(value)}]}}}];
const nested=(name,args,body,isError=false)=>({type:'tool/ptc-dispatch',data:{name,arguments:args,subCallId:'code:ptc:1',rootCallId:'code',isError,content:[{type:'text',text:JSON.stringify(body)}]}});
const receipt={tasks:[{id:value.task_id,state:'SUCCEEDED',unit:{revision:0,intent:{}},result:{
  operation:'capture_only',directory:'/actual',scene_quality_assessed:false,
  report:{status:'captured',interaction:{action_results:[{id:'requested_push',success:false}]}}
}}]};

test('capture review enters the next decision before goal completion, once per capture',async()=>{
  const events=[turn,step,...native];const requests=[],steers=[];
  const agent={session:{snapshotEvents:()=>events},steer:m=>steers.push(m)};
  const review=createDeliveryReview({api:async()=>{requests.push('inspect');return receipt;},createMessage:x=>x});
  const hook=createCaptureReviewStep(review);
  const input={agent,turn:1,signal:new AbortController().signal};
  const existing={source:{kind:'user'},content:[{type:'text',text:'current steering'}]};
  const decision=await hook(input,async()=>({kind:'enter',messages:[existing]}));
  assert.equal(decision.messages[0],existing);
  assert.equal(decision.messages.length,2);
  assert.match(decision.messages[1].content[0].text,/"success":false/);
  assert.equal(steers.length,0);
  events.push({type:'user/message',data:decision.messages[1]},
    {type:'step/start',data:{turn:1,step:2}},
    {type:'tool/call',data:{name:'update_goal',callId:'complete',arguments:'{"action":"complete"}'}});
  assert.deepEqual(await hook(input,async()=>({kind:'enter',messages:[]})),{kind:'enter',messages:[]});
  await review(input);
  assert.equal(requests.length,1);
});

test('PTC capture and later PTC status retain the inner task identity across turns',()=>{
  const capture=nested('spatialforge_capture',{},value);
  assert.equal(pendingCapture([turn,capture],1).callId,'code:ptc:1');
  const status=nested('spatialforge_status',{run_id:value.run_id},{state:'SUCCEEDED'});
  assert.equal(pendingCapture([turn,capture,{type:'turn/start',data:{turn:2}},status],2).taskId,value.task_id);
  assert.equal(pendingCapture([turn,nested('spatialforge_status',{run_id:value.run_id},{},true)],1),undefined);
});

test('receiving PTC observation gets review before the next decision',async()=>{
  const events=[turn,step,nested('spatialforge_status',{run_id:value.run_id},{state:'SUCCEEDED'})];
  const review=createDeliveryReview({api:async()=>receipt,createMessage:x=>x});
  const decision=await createCaptureReviewStep(review)({agent:{session:{snapshotEvents:()=>events}},turn:1,signal:new AbortController().signal},async()=>({kind:'enter',messages:[]}));
  assert.equal(decision.messages[0].source.task_id,value.task_id);
});

test('unrelated turns and rejected steps do not inspect old scenes or schedule more work',async()=>{
  let calls=0;
  const hook=createCaptureReviewStep(async()=>{calls++});
  const input={agent:{session:{snapshotEvents:()=>[turn,step,...native,{type:'turn/start',data:{turn:2}}]}},turn:2};
  assert.deepEqual(await hook(input,async()=>({kind:'enter',messages:[]})),{kind:'enter',messages:[]});
  assert.deepEqual(await hook(input,async()=>({kind:'reject'})),{kind:'reject'});
  assert.equal(calls,0);
});
