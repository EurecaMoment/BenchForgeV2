import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createPreparationHandler} from '../plugin/preparation.mjs';

test('preparation binds native parent and saved plan before any delegation', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'sf-preparation-tool-'));
  t.after(() => fs.rm(root, {recursive: true, force: true}));
  const workspace = path.join(root, 'workspace'), operation = path.join(workspace, 'operations', 'plan');
  await fs.mkdir(operation, {recursive: true});
  const plan = path.join(operation, 'plan.json');
  await fs.writeFile(plan, '{}');
  await fs.writeFile(path.join(operation, 'request.json'), JSON.stringify({context: {session_id: 'parent'}}));
  const calls = [], ctx = {};
  const handler = createPreparationHandler({ctx, createController: config => ({start: async (request, signal) => {
    calls.push({config, request, signal}); return {state: 'accepted', acceptedCount: 1};
  }})});
  const signal = new AbortController().signal;
  const exec = {signal, agent: {id: 'parent', session: {header: {id: 'parent', cwd: workspace}}}};
  const args = {workspace, plan_path: plan, batch_key: 'repair', tasks: [{key: 'annotations'}]};
  assert.equal((await handler(args, exec)).acceptedCount, 1);
  assert.deepEqual(calls[0], {config: {ctx, workspacePath: await fs.realpath(workspace), batchSize: 3},
    request: {parentId: 'parent', planPath: await fs.realpath(plan), batchKey: 'repair', tasks: args.tasks}, signal});
  const other = {...exec, agent: {id: 'other', session: {header: {id: 'other', cwd: workspace}}}};
  await assert.rejects(handler(args, other), /not associated/);
  await assert.rejects(handler({...args, workspace: operation}, exec), /belong to the named workspace/);
  const abort = new AbortController(); abort.abort();
  await assert.rejects(handler(args, {...exec, signal: abort.signal}), {name: 'AbortError'});
  assert.equal(calls.length, 1, 'invalid scope and cancellation must never create workers');
});
