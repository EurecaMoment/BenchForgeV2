import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDeliveryReview, pendingCapture, sourceKind } from '../plugin/delivery_review.mjs';

const captureEvents = (id = 'c1', run = 'sf_example') => [
  { type: 'turn/start', data: { turn: 1 } },
  { type: 'tool/call', data: { name: 'spatialforge_capture', callId: id } },
  { type: 'tool/result', data: { message: { toolCallId: id, content: [{ type: 'text', text: JSON.stringify({run_id: run, task_id: run + '.scene0'}) }] } } },
];
const receipt = { tasks: [{ id: 'sf_example.scene0', state: 'SUCCEEDED', unit: { revision: 0, intent: {} },
  result: { operation: 'capture_only', scene_quality_assessed: false, data_exported: false, directory: '/capture-source',
    report: { status: 'captured', interaction: { test_kind: 'external_force_response', action_results: [{id:'push',success:false,translation_m:0}] } } } }] };

function replay(events, response = receipt) {
  const requests = [], messages = [];
  const agent = { session: { snapshotEvents: () => events }, steer: message => {
    messages.push(message); events.push({type:'user/message',data:message});
  } };
  const review = createDeliveryReview({ api: async (path, args) => { requests.push({path,args}); return response; }, createMessage: x => x });
  return {requests,messages,run: signal => review({agent,turn:1,signal:signal ?? new AbortController().signal})};
}

test('a completed capture prompts delivery review, preserving failed action evidence', async () => {
  const r = replay(captureEvents()); await r.run();
  assert.equal(r.messages.length, 1);
  assert.equal(r.messages[0].source.kind, sourceKind);
  assert.match(r.messages[0].content[0].text, /"success":false/);
  assert.match(r.messages[0].content[0].text, /no extra robot, dataset/);
  assert.match(r.messages[0].content[0].text, /formal delivery response/);
  assert.match(r.messages[0].content[0].text, /Do not claim that all views were inspected/);
  assert.match(r.messages[0].content[0].text, /A visible omission or mismatch is unfinished work/);
  assert.match(r.messages[0].content[0].text, /Do not write a generic/);
});

test('physical success retains invisible demonstration and actual location evidence', async () => {
  const response=structuredClone(receipt);
  response.tasks[0].result.report.interaction.action_results=[{
    id:'push_box',object_id:'box',success:true,translation_m:.134,
    checks:{moved_in_force_direction:true},before:{position:[.62,-1.3,.0525]},after:{position:[.754,-1.3,.0525]},
    before_image:'interaction_0_before.png',after_image:'interaction_0_after.png',
    visual_evidence:{before:{visible_pixels:0,bbox_xyxy:null},after:{visible_pixels:0,bbox_xyxy:null}},
  }];
  const r=replay(captureEvents(),response);await r.run();
  const text=r.messages[0].content[0].text;
  const facts=JSON.parse(text.split('Latest capture receipt: ')[1].split('\n')[0]);
  assert.equal(facts.actions[0].success,true);
  assert.equal(facts.actions[0].before_visibility.visible_pixels,0);
  assert.equal(facts.actions[0].after_visibility.visible_pixels,0);
  assert.equal(facts.actions[0].before_position_m[2],.0525);
  assert.match(text,/not whether it occurred at the requested location/);
});

test('repeated final/status does not repeat the review; a new capture does', async () => {
  const events = captureEvents(), r = replay(events); await r.run();
  events.push({type:'tool/call',data:{name:'spatialforge_status',callId:'poll'}});
  await r.run();
  assert.equal(r.requests.length,1);
  events.push(...captureEvents('c2').slice(1)); await r.run();
  assert.equal(r.messages.length,2);
});

test('review deduplication survives replay and previous turns do not force new work', () => {
  const events = captureEvents();
  events.push({type:'user/message',data:{source:{kind:sourceKind,capture_call_id:'c1'}}});
  assert.equal(pendingCapture(structuredClone(events),1),undefined);
  events.push({type:'turn/start',data:{turn:2}});
  assert.equal(pendingCapture(events,2),undefined);
});

test('refine supersedes its parent capture, including older receipts without task_id', async () => {
  const events=captureEvents();
  events.push({type:'tool/call',data:{name:'spatialforge_refine',callId:'refine1'}},
    {type:'tool/result',data:{message:{toolCallId:'refine1',content:[{type:'text',text:JSON.stringify({run_id:'sf_refined'})}]}}});
  assert.equal(pendingCapture(events,1).taskId,'sf_refined.scene0');
  const response=structuredClone(receipt);response.tasks[0].id='sf_refined.scene0';
  const r=replay(events,response);await r.run();
  assert.equal(r.messages[0].source.task_id,'sf_refined.scene0');
  const active=structuredClone(response);active.tasks[0].state='RUNNING';
  const unreviewed=events.filter(e=>e.type!=='user/message');
  const waiting=replay(unreviewed,active);await waiting.run();
  assert.equal(waiting.messages.length,0);
  assert.equal(waiting.requests[0].args.run_id,'sf_refined');
});

test('non-capture, active, failed and cancelled work is not forced to keep waiting', async () => {
  const noCapture=replay([{type:'turn/start',data:{turn:1}}]); await noCapture.run();
  assert.equal(noCapture.requests.length,0);
  for (const state of ['RUNNING','FAILED_FINAL','CANCELLED']) {
    const response=structuredClone(receipt); response.tasks[0].state=state;
    const r=replay(captureEvents(),response); await r.run(); assert.equal(r.messages.length,0);
  }
  const r=replay(captureEvents()), controller=new AbortController();controller.abort();
  await assert.rejects(r.run(controller.signal),{name:'AbortError'});
  assert.equal(r.requests.length,0);
});
