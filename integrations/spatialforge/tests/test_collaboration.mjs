import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {apply} from '../plugin/tools.mjs';

test('SpatialForge plugin exposes shared handoffs without service calls', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'spatialforge-collab-'));
  const dsh = path.join(root, 'dsh');
  await fs.mkdir(path.join(dsh, 'packages/core/tools/lib'), {recursive: true});
  await fs.mkdir(path.join(dsh, 'packages/llm/llm/lib'), {recursive: true});
  await fs.writeFile(path.join(dsh, 'packages/core/tools/lib/package.json'), JSON.stringify({type: 'module'}));
  await fs.writeFile(path.join(dsh, 'packages/core/tools/lib/index.js'), 'export function defineTool(value){return value;}');
  await fs.writeFile(path.join(dsh, 'packages/llm/llm/lib/package.json'), JSON.stringify({type: 'module'}));
  await fs.writeFile(path.join(dsh, 'packages/llm/llm/lib/index.js'), 'export function createUserMessage(value){return value;}');
  const config = path.join(root, 'service.json');
  await fs.writeFile(config, JSON.stringify({port: 9}));
  process.env.SPATIALFORGE_OPERATOR_TOKEN = 'test-token';
  const registered = new Map();
  await apply({
    tools: {register: tool => registered.set(tool.name, tool)},
    on: () => {},
    get: () => ({saveImage: async () => ({})}),
    llm: {resolveModelInfo: async () => ({inputModalities: []})},
  }, {dshRoot: dsh, serviceConfig: config});
  const tool = registered.get('spatialforge_collaboration');
  assert.ok(tool);
  const exec = {agent: {session: {id: 'agent-a'}}};
  const first = await tool.execute({workspace: root, action: 'publish', role: 'planner', status: 'ready', summary: 'split prepared'}, exec);
  await tool.execute({workspace: root, action: 'publish', handoff_id: 'review', role: 'visual', reply_to: first.handoff_id, status: 'blocked', summary: 'camera needs review'}, exec);
  assert.equal((await tool.execute({workspace: root, action: 'list', filter: {role: 'visual'}}, exec)).handoffs.length, 1);
  assert.equal((await tool.execute({workspace: root, action: 'read', handoff_id: 'review'}, exec)).reply_to, first.handoff_id);
});
