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
  return {requests,messages,run: (signal, turn = 1) => review({agent,turn,signal:signal ?? new AbortController().signal})};
}

const observationEvents = (name, args, isError = false) => [
  {type:'tool/call',data:{name,callId:'observe-'+name,arguments:JSON.stringify(args)}},
  {type:'tool/result',data:{message:{toolCallId:'observe-'+name,isError,content:[{type:'text',text:'{}'}]}}},
];

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
    recording:{source:'rendered_simulation_steps',video:'interaction_0.mp4',timeline_file:'interaction_0_recording.json',frame_count:67,fps:30,interpolated_frames:0},
    object_contacts:{sampling_hz:120,summary:{receiver:{nonzero_contact_steps:3,displacement_vector_m:[0,.02,0]}}},
    visual_evidence:{before:{visible_pixels:0,bbox_xyxy:null},after:{visible_pixels:0,bbox_xyxy:null}},
  }];
  const r=replay(captureEvents(),response);await r.run();
  const text=r.messages[0].content[0].text;
  const facts=JSON.parse(text.split('Latest capture receipt: ')[1].split('\n')[0]);
  assert.equal(facts.actions[0].success,true);
  assert.equal(facts.actions[0].before_visibility.visible_pixels,0);
  assert.equal(facts.actions[0].after_visibility.visible_pixels,0);
  assert.equal(facts.actions[0].before_position_m[2],.0525);
  assert.equal(facts.actions[0].recording.video,'interaction_0.mp4');
  assert.equal(facts.actions[0].recording.interpolated_frames,0);
  assert.equal(facts.actions[0].object_contacts.summary.receiver.nonzero_contact_steps,3);
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

test('a capture that finishes in a later turn receives its review when work resumes', async () => {
  const events = captureEvents(), response = structuredClone(receipt);
  response.tasks[0].state = 'RUNNING';
  const r = replay(events, response); await r.run();
  assert.equal(r.messages.length, 0);
  events.push({type:'turn/start',data:{turn:2}}, ...observationEvents('spatialforge_wait', {run_id:'sf_example'}));
  response.tasks[0].state = 'SUCCEEDED';
  await r.run(undefined, 2);
  assert.equal(r.messages.length, 1);
  assert.equal(r.messages[0].source.capture_call_id, 'c1');
  assert.match(r.messages[0].content[0].text, /"success":false/);
  events.push({type:'turn/start',data:{turn:3}}, ...observationEvents('spatialforge_status', {run_id:'sf_example'}));
  await r.run(undefined, 3);
  assert.equal(r.messages.length, 1);
  assert.equal(r.requests.length, 2);
});

test('status and task evidence can resume review without a duplicate capture', () => {
  for (const [name, args] of [
    ['spatialforge_status', {run_id:'sf_example', detail:true}],
    ['spatialforge_evidence', {task_id:'sf_example.scene0', file:'report.json'}],
  ]) {
    const events = [...captureEvents(), {type:'turn/start',data:{turn:2}}, ...observationEvents(name,args)];
    assert.equal(pendingCapture(events,2).callId,'c1');
  }
});

test('unrelated, failed or superseded observations do not resurrect an old capture', () => {
  const next = [...captureEvents(), {type:'turn/start',data:{turn:2}}];
  assert.equal(pendingCapture(next,2),undefined);
  assert.equal(pendingCapture([...next, ...observationEvents('spatialforge_status',{run_id:'sf_other'})],2),undefined);
  assert.equal(pendingCapture([...next, ...observationEvents('spatialforge_evidence',{task_id:'sf_example.scene1'})],2),undefined);
  assert.equal(pendingCapture([...next, ...observationEvents('spatialforge_wait',{run_id:'sf_example'},true)],2),undefined);
  const superseded = [...captureEvents(), ...captureEvents('c2','sf_new').slice(1),
    {type:'turn/start',data:{turn:2}}, ...observationEvents('spatialforge_status',{run_id:'sf_example'})];
  assert.equal(pendingCapture(superseded,2),undefined);
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

test('an agent receiving a capture can review it without the submitting session', async () => {
  for (const name of ['spatialforge_status','spatialforge_wait']) {
    const events=[{type:'turn/start',data:{turn:1}},...observationEvents(name,{run_id:'sf_example'})];
    const r=replay(events);await r.run();
    assert.equal(r.messages.length,1);
    assert.equal(r.messages[0].source.task_id,'sf_example.scene0');
    assert.match(r.messages[0].content[0].text,/"success":false/);
    events.push({type:'turn/start',data:{turn:2}},...observationEvents(name,{run_id:'sf_example'}));
    await r.run(undefined,2);
    assert.equal(r.messages.length,1);
    assert.equal(r.requests.length,1);
    assert.equal(pendingCapture(structuredClone(events),2),undefined);
  }
});

test('receiving agents resume active captures later, without reopening them on unrelated turns', async () => {
  const events=[{type:'turn/start',data:{turn:1}},...observationEvents('spatialforge_status',{run_id:'sf_example'})];
  const response=structuredClone(receipt);response.tasks[0].state='RUNNING';
  const r=replay(events,response);await r.run();assert.equal(r.messages.length,0);
  events.push({type:'turn/start',data:{turn:2}});await r.run(undefined,2);
  assert.equal(r.requests.length,1);
  events.push({type:'turn/start',data:{turn:3}},...observationEvents('spatialforge_wait',{run_id:'sf_example'}));
  response.tasks[0].state='SUCCEEDED';await r.run(undefined,3);
  assert.equal(r.messages.length,1);
});

test('observing another operation or an unsuccessful tool does not create a scene review', async () => {
  const events=[{type:'turn/start',data:{turn:1}},...observationEvents('spatialforge_status',{run_id:'image_run'})];
  const r=replay(events,{tasks:[{id:'image_run.diffusion',state:'SUCCEEDED',result:{operation:'diffusion'}}]});
  await r.run();assert.equal(r.messages.length,0);
  const failed=replay([{type:'turn/start',data:{turn:1}},...observationEvents('spatialforge_status',{run_id:'sf_example'},true)]);
  await failed.run();assert.equal(failed.requests.length,0);
});
