import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {apply} from '../tools/scene/tools.mjs';
import {apply as applyCoreTools} from '../tools/core.mjs';

test('BenchForge plugin exposes shared handoffs without service calls', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-collab-'));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const config = path.join(root, 'service.json');
  await fs.writeFile(config, JSON.stringify({port: 9, operator_token: 'test-token', execution_mode: 'exploration'}));
  const registered = new Map();
  await apply({
    tools: {register: tool => registered.set(tool.name, tool)},
    on: () => {},
    get: () => undefined,
    attachments: {saveImage: async () => ({})},
    llm: {resolveModelInfo: async () => ({inputModalities: []})},
  }, {serviceConfig: config});
  const tool = registered.get('benchforge_scene_collaboration');
  assert.ok(tool);
  const exec = {signal:new AbortController().signal,agent: {session: {id: 'agent-a'}}};
  const first = await tool.execute({workspace: root, action: 'publish', role: 'planner', status: 'ready', summary: 'split prepared'}, exec);
  await tool.execute({workspace: root, action: 'publish', handoff_id: 'review', role: 'visual', reply_to: first.handoff_id, status: 'blocked', summary: 'camera needs review'}, exec);
  assert.equal((await tool.execute({workspace: root, action: 'list', filter: {role: 'visual'}}, exec)).handoffs.length, 1);
  assert.equal((await tool.execute({workspace: root, action: 'read', handoff_id: 'review'}, exec)).reply_to, first.handoff_id);
  const completed = await tool.execute({workspace: root, action: 'publish', handoff_id: 'review', role: 'delivery', status: 'done', summary: 'Camera fixed and inspected', agent: 'agent-b', artifacts: ['render.png']}, exec);
  assert.deepEqual((await tool.execute({workspace: root, action: 'list', filter: {status: 'blocked'}}, exec)).handoffs, []);
  assert.deepEqual((await tool.execute({workspace: root, action: 'list', filter: {role: 'visual'}}, exec)).handoffs, []);
  assert.deepEqual((await tool.execute({workspace: root, action: 'list', filter: {agent: 'agent-b'}}, exec)).handoffs, [completed]);
  assert.deepEqual((await tool.execute({workspace: root, action: 'list'}, exec)).handoffs, [first, completed]);
  assert.deepEqual(await tool.execute({workspace: root, action: 'read', handoff_id: 'review'}, exec), completed);
  assert.equal((await tool.execute({workspace: root, action: 'list', history: true, filter: {status: 'blocked'}}, exec)).handoffs.length, 1);
  assert.equal((await fs.readFile(path.join(root, '.benchforge/collaboration/handoffs.jsonl'), 'utf8')).trim().split('\n').length, 3);

  await applyCoreTools({
    tools: {register: tool => registered.set(tool.name, tool)},
    effect: () => {},
    get: () => undefined,
  }, {includeTools: ['collaboration']});
  const coreTool = registered.get('benchforge_collaboration');
  assert.deepEqual(coreTool.parameters.required, tool.parameters.required);
  assert.deepEqual(await coreTool.execute({workspace: root, action: 'read', handoff_id: 'review'}, exec), completed);

  const abort = new AbortController();
  abort.abort();
  const publish = {workspace: root, action: 'publish', handoff_id: 'review', role: 'delivery', summary: 'Confirmed'};
  await assert.rejects(coreTool.execute(publish, {signal: abort.signal}), {name:'AbortError'});
  await assert.rejects(tool.execute({...publish, summary: ''}, exec), /needs role and summary/);
  const [updated, separate] = await Promise.all([
    coreTool.execute({...publish, confidence:0}, {}),
    tool.execute({...publish, handoff_id:'separate', summary:'independent'}, exec),
  ]);
  assert.equal(updated.confidence, 0);
  assert.equal(updated.agent, 'current-agent');
  assert.equal(updated.status, 'working');
  assert.deepEqual((await tool.execute({workspace: root, action: 'list'}, exec)).handoffs, [first, updated, separate]);
});
