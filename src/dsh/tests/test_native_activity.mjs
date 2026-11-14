import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createSynthesisSessions} from '../host/sessions/synthesis_sessions.js';

function pendingActivity() {
  let resolve, subscriptions = 0;
  const promise = new Promise(done => { resolve = done; });
  const then = promise.then;
  promise.then = function (...args) { subscriptions++; return then.apply(this, args); };
  return {promise, resolve, get subscriptions() { return subscriptions; }};
}

async function fixture(t) {
  const temporaryRoot = await fs.realpath(os.tmpdir());
  const workspace = await fs.mkdtemp(path.join(temporaryRoot, 'benchforge-native-activity-'));
  t.after(async () => {
    const resolved = path.resolve(workspace), relative = path.relative(temporaryRoot, resolved);
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
    assert.ok(path.basename(resolved).startsWith('benchforge-native-activity-'));
    await fs.rm(resolved, {recursive: true, force: true});
  });
  const parentId = 'session-parent', childId = 'session-child', batchKey = 'diagnostic';
  const parent = {id: parentId, status: 'idle', session: {header: {id: parentId, cwd: workspace}}};
  const child = {id: childId, status: 'idle'};
  const agents = new Map([[parentId, parent], [childId, child]]);
  const services = {agents, sessions: new Map([[parentId, {header: parent.session.header}]]),
    subagents: {startActivation() { assert.fail('read must not start native work'); }},
    sessionQuery: {observeSession() { assert.fail('accepted startup needs no new catalog query'); }}};
  const ctx = {get: name => services[name]};
  const directory = path.join(workspace, '.benchforge', 'synthesis-sessions');
  await fs.mkdir(directory, {recursive: true});
  const recordPath = path.join(directory, 'batch-' + Buffer.from(batchKey).toString('base64url') + '.json');
  const original = JSON.stringify({schema: 'benchforge.synthesis-sessions/v1', parentId, batchKey,
    tasks: [{key: 'questions', label: 'question preparation', childId, state: 'accepted', prompt: 'private input'}]});
  await fs.writeFile(recordPath, original);
  const factory = createSynthesisSessions({ctx, workspacePath: workspace});
  return {workspace, ctx, factory, parent, child, agents, childId, recordPath, original,
    request: {parentId, batchKey}};
}

test('native activity reads bound pending work and reuse one unfinished probe across factories', {timeout: 1500}, async t => {
  const f = await fixture(t);
  const parentPending = pendingActivity(), childPending = pendingActivity();
  t.after(() => { parentPending.resolve(); childPending.resolve(); });
  let parentCalls = 0, childCalls = 0;
  f.parent.status = 'running';
  f.parent.whenIdle = () => { parentCalls++; return parentPending.promise; };
  f.child.whenIdle = () => { childCalls++; return childPending.promise; };
  Object.defineProperty(f.parent, 'phase', {get() { assert.fail('private phase must not be inspected'); }});
  Object.defineProperty(f.child, 'driver', {get() { assert.fail('private driver must not be inspected'); }});
  const started = performance.now();
  const first = await f.factory.read(f.request);
  assert.ok(performance.now() - started < 500, 'an unfinished native activity must not hold the read indefinitely');
  assert.deepEqual(first.parentNativeActivity, {available: true, agentStatus: 'running', idleConfirmed: false, activityPending: true});
  assert.deepEqual(first.tasks[0].nativeActivity, {available: true, agentStatus: 'idle', idleConfirmed: false, activityPending: true});
  const other = createSynthesisSessions({ctx: f.ctx, workspacePath: f.workspace});
  const repeated = await Promise.all([f.factory.read(f.request), other.read(f.request)]);
  assert.ok(repeated.every(value => value.tasks[0].nativeActivity.activityPending));
  assert.equal(parentCalls, 1);
  assert.equal(childCalls, 1);
  assert.equal(parentPending.subscriptions, 1);
  assert.equal(childPending.subscriptions, 1, 'timed-out reads must not stack completion listeners');
  assert.equal(first.state, 'accepted', 'native activity must not change startup acceptance into production completion');
  assert.ok(!('prompt' in first.tasks[0]));
  assert.equal(await fs.readFile(f.recordPath, 'utf8'), f.original, 'native diagnostics must not persist runtime snapshots');
});

test('native activity confirms settled work and refreshes after a new activity with the same idle status', {timeout: 1500}, async t => {
  const f = await fixture(t);
  let calls = 0;
  f.parent.whenIdle = () => Promise.resolve();
  f.child.whenIdle = () => { calls++; return Promise.resolve(); };
  const settled = await f.factory.read(f.request);
  assert.equal(settled.parentNativeActivity.idleConfirmed, true);
  assert.deepEqual(settled.tasks[0].nativeActivity, {available: true, agentStatus: 'idle', idleConfirmed: true, activityPending: false});
  const pending = pendingActivity();
  t.after(pending.resolve);
  f.child.whenIdle = () => { calls++; return pending.promise; };
  const active = await f.factory.read(f.request);
  assert.equal(calls, 2, 'a completed probe must not permanently certify a later maintenance activity as idle');
  assert.equal(active.tasks[0].nativeActivity.agentStatus, 'idle');
  assert.equal(active.tasks[0].nativeActivity.idleConfirmed, false);
  assert.equal(active.tasks[0].nativeActivity.activityPending, true);
  pending.resolve();
  const recovered = await f.factory.read(f.request);
  assert.equal(recovered.tasks[0].nativeActivity.idleConfirmed, true);
  assert.equal(recovered.tasks[0].nativeActivity.activityPending, false);
});

test('native activity reports unavailable APIs and failed probes without inventing idle', {timeout: 1500}, async t => {
  const f = await fixture(t);
  f.child.whenIdle = () => Promise.reject(Object.assign(new Error('activity failed before its driver ran'), {code: 'AGENT_NOT_LIVE'}));
  const failed = await f.factory.read(f.request);
  assert.equal(failed.parentNativeActivity.agentStatus, 'idle');
  assert.equal(failed.parentNativeActivity.idleConfirmed, false);
  assert.equal(failed.parentNativeActivity.activityPending, null);
  assert.match(failed.parentNativeActivity.reason, /whenIdle.*unavailable/);
  assert.equal(failed.tasks[0].nativeActivity.idleConfirmed, false);
  assert.equal(failed.tasks[0].nativeActivity.activityPending, null);
  assert.deepEqual(failed.tasks[0].nativeActivity.error, {name: 'Error', message: 'activity failed before its driver ran', code: 'AGENT_NOT_LIVE'});
  f.agents.delete(f.childId);
  const absent = await f.factory.read(f.request);
  assert.deepEqual(absent.tasks[0].nativeActivity, {available: false, agentStatus: null, idleConfirmed: false, activityPending: null});
});
