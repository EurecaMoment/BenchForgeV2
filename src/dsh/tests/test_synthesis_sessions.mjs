import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {apply as applySubagentPolicy} from '../tools/subagent_policy.mjs';
import {createSynthesisSessions} from '../host/sessions/synthesis_sessions.js';

async function fixture(t, batchSize = 3) {
  const temporaryRoot = await fs.realpath(os.tmpdir());
  const temporary = await fs.mkdtemp(path.join(temporaryRoot, 'benchforge-synthesis-factory-'));
  const workspace = path.join(temporary, 'workspace');
  await fs.mkdir(workspace);
  t.after(async () => {
    const resolved = path.resolve(temporary), relative = path.relative(temporaryRoot, resolved);
    assert.ok(relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative));
    assert.ok(path.basename(resolved).startsWith('benchforge-synthesis-factory-'));
    await fs.rm(resolved, {recursive: true, force: true});
  });
  const parent = {id: 'session-parent', status: 'running',
    options: {provider: 'qwen-flash', model: 'Qwen/Qwen3.8-Flash-Next', reasoningEffort: 'max'},
    session: {header: {id: 'session-parent', cwd: workspace}}};
  const agents = new Map([[parent.id, parent]]), sessions = new Map([[parent.id, {header: parent.session.header}]]);
  const catalog = [], calls = [], observations = [], capabilityRequests = [], modelRequests = [];
  let reasoningInfo = {efforts: [{id: 'medium', name: 'Medium'}], defaultEffort: 'max'};
  const accept = spec => {
    const content = spec.prompt;
    assert.ok(Array.isArray(content) && content.some(block => block.type === 'text' && block.text.trim()),
      'the native initial user message must contain effective ContentBlock text');
    const selectedEffort = spec.agentOptions?.reasoningEffort;
    if (selectedEffort === undefined || reasoningInfo?.efforts?.some(effort => effort.id === selectedEffort)) {
      modelRequests.push({role: 'user', content, ...(selectedEffort ? {reasoningEffort: selectedEffort} : {})});
    }
    sessions.set(spec.childId, {header: {id: spec.childId, cwd: workspace, parentSession: parent.id, origin: 'subagent'}});
    agents.set(spec.childId, {id: spec.childId, status: 'running'});
    catalog.push({id: spec.childId, mode: 'continuable', label: spec.label});
    return {childId: spec.childId, messageId: 'message-' + spec.childId};
  };
  let implementation = accept;
  const services = {
    agents, sessions,
    llm: {resolveModelInfo: async (provider, model, signal) => {
      capabilityRequests.push({provider, model, signal});
      return {provider, id: model, name: model, reasoning: reasoningInfo};
    }},
    subagents: {
      startActivation: async spec => {
        calls.push(spec);
        return implementation(spec);
      },
    },
    sessionQuery: {observeSession: async (id, options) => {
      observations.push({id, options});
      if (id === parent.id) return {header: parent.session.header, projections: {values: {subagentCatalog: catalog}}, [Symbol.dispose]() {}};
      const value = sessions.get(id);
      if (!value) throw Object.assign(new Error('not found'), {code: 'SESSION_QUERY_SESSION_NOT_FOUND'});
      return {...value, [Symbol.dispose]() {}};
    }},
  };
  parent.ctx = {get: name => services[name]};
  const ctx = {get: name => services[name]};
  const factory = createSynthesisSessions({ctx, workspacePath: workspace, batchSize});
  const task = async key => {
    const outputDirectory = path.join(workspace, 'synthesis', key);
    await fs.mkdir(outputDirectory, {recursive: true});
    return {key, label: key + ' preparation', prompt: 'Prepare ' + key + ' from the frozen plan.', outputDirectory};
  };
  const request = (tasks, batchKey = 'repair') => ({parentId: parent.id, batchKey, tasks});
  return {temporary, workspace, parent, agents, sessions, catalog, calls, observations, services, ctx,
    capabilityRequests, modelRequests, factory, task, request, accept,
    setImplementation: value => { implementation = value; },
    setEfforts: ids => { reasoningInfo = {efforts: ids.map(id => ({id, name: id})), defaultEffort: 'max'}; },
    setReasoningInfo: value => { reasoningInfo = value; }};
}

test('parallel admission is idempotent and catalog acceptance survives lost receipts', async t => {
  const f = await fixture(t);
  const tasks = await Promise.all(['annotation', 'questions', 'scene'].map(f.task));
  let active = 0, peak = 0;
  f.setImplementation(async spec => {
    peak = Math.max(peak, ++active);
    await delay(20);
    active--;
    return f.accept(spec);
  });
  const signal = new AbortController().signal;
  const [first, repeated] = await Promise.all([f.factory.start(f.request(tasks), signal), f.factory.start(f.request(tasks), signal)]);
  assert.equal(first.state, 'accepted');
  assert.equal(first.acceptedCount, 3);
  assert.deepEqual(repeated.tasks.map(row => row.childId), first.tasks.map(row => row.childId));
  assert.equal(f.calls.length, 3);
  assert.equal(f.modelRequests.length, 3, 'accepted inputs must be eligible to reach a model request');
  assert.equal(peak, 3, 'independent native creations must run concurrently');
  assert.ok(first.tasks.every(row => !('prompt' in row)));
  for (const spec of f.calls) {
    assert.equal(spec.provider, 'spawn');
    assert.equal(spec.parent, f.parent);
    assert.equal(spec.delivery, 'parent');
    assert.equal(spec.signal, signal);
    assert.deepEqual(spec.agentOptions, {reasoningEffort: 'medium'});
    assert.equal(spec.maxDepth, 1);
    assert.ok(!('toolFilter' in spec) && !('persona' in spec));
    assert.ok(!('model' in spec.agentOptions) && !('maxTokens' in spec.agentOptions));
    assert.match(spec.prompt[0].text, /Assigned output directory:/);
  }
  const saved = JSON.parse(await fs.readFile(first.recordPath, 'utf8'));
  for (const row of saved.tasks) { row.state = 'starting'; delete row.messageId; }
  await fs.writeFile(first.recordPath, JSON.stringify(saved));
  const recovered = await f.factory.start(f.request([...tasks].reverse()), signal);
  assert.equal(f.calls.length, 3);
  assert.equal(recovered.acceptedCount, 3);
  assert.ok(recovered.tasks.every(row => row.recovered));
  f.agents.delete(f.parent.id);
  const read = await f.factory.read({parentId: f.parent.id, batchKey: 'repair'}, signal);
  assert.equal(read.acceptedCount, 3, 'status must remain readable when the parent Agent is not resident');
});

test('typed rejection retries its reserved identity while uncertain startup waits for catalog evidence', async t => {
  const f = await fixture(t);
  const task = await f.task('annotation');
  f.setImplementation(() => { throw Object.assign(new Error('provider rejected before admission'),
    {name: 'SubagentError', code: 'CHILD_CAPACITY_EXCEEDED'}); });
  const rejected = await f.factory.start(f.request([task]));
  assert.equal(rejected.state, 'failed');
  assert.equal(rejected.acceptedCount, 0);
  assert.equal(rejected.failedCount, 1);
  assert.match(rejected.reason, /provider rejected before admission/);
  assert.ok(!rejected.reason.includes('batch budget'));
  f.setImplementation(f.accept);
  const retried = await f.factory.start(f.request([task]));
  assert.equal(retried.acceptedCount, 1);
  assert.equal(f.calls[0].childId, f.calls[1].childId, 'retry must retain its durable child identity');

  const uncertainTask = await f.task('questions');
  f.setImplementation(spec => {
    f.sessions.set(spec.childId, {header: {id: spec.childId, cwd: f.workspace,
      parentSession: f.parent.id, origin: 'subagent'}});
    throw new Error('connection ended before the startup receipt');
  });
  const uncertain = await f.factory.start(f.request([uncertainTask], 'uncertain'));
  assert.equal(uncertain.state, 'waiting');
  assert.equal(uncertain.acceptedCount, 0);
  assert.equal(uncertain.tasks[0].state, 'starting');
  assert.match(uncertain.reason, /connection ended before the startup receipt/);
  const calls = f.calls.length;
  const waiting = await f.factory.start(f.request([uncertainTask], 'uncertain'));
  assert.equal(waiting.state, 'waiting');
  assert.equal(f.calls.length, calls, 'an existing child without accepted catalog evidence must not be recreated');
  f.catalog.push({id: uncertain.tasks[0].childId, mode: 'continuable'});
  const recovered = await f.factory.read({parentId: f.parent.id, batchKey: 'uncertain'});
  assert.equal(recovered.acceptedCount, 1);
  assert.equal(recovered.tasks[0].recovered, true);
});

test('scoped subagent policy keeps production calls with the parent', () => {
  const parent = {session: {header: {}}};
  const child = {session: {header: {origin: 'subagent'}}};
  let guard, section;
  applySubagentPolicy({tools: {guard: value => {guard = value;}},
    systemPrompt: {section: value => {section = value;}}},
  {persona: 'Prepare only', parentTools: ['benchforge_pipeline_run', 'benchforge_capture']});
  assert.match(guard({agent: child, name: 'benchforge_pipeline_run'}), /parent agent/);
  assert.match(guard({agent: child, name: 'pipeline_run'}), /parent agent/);
  assert.match(guard({agent: child, name: 'spatialforge_capture'}), /parent agent/);
  assert.equal(guard({agent: child, name: 'benchforge_pipeline_evaluate'}), undefined);
  assert.equal(guard({agent: parent, name: 'benchforge_capture'}), undefined);
  assert.equal(section.text({scope: parent}), '');
  assert.equal(section.text({scope: child}), 'Prepare only');
});

test('preset migration removes retired delegation options and retains the production tool scope', () => {
  const program = String.raw`
import ast, json, sys
from pathlib import Path
source = Path(sys.argv[1])
tree = ast.parse(source.read_text(encoding='utf-8'))
constants = {'PARENT_OWNED_SYNTHESIS_TOOLS', 'DEFAULT_SYNTHESIS_REASONING_EFFORT', 'SYNTHESIS_WORKER_PERSONA'}
functions = {'configured_synthesis_tools', 'configure_synthesis_delegation'}
selected = [node for node in tree.body if
    isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id in constants for name in node.targets)
    or isinstance(node, ast.FunctionDef) and node.name in functions]
namespace = {}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)
worker = {'name': '@deepseek-ai/dsh-tool-subagent', 'config': {'provider': 'spawn',
    'agentOptions': {'provider': 'saved-route', 'model': 'saved-model', 'maxTokens': 100},
    'toolFilter': {'deny': ['pipeline_run', 'pipeline_evaluate', 'benchforge_capture']}}}
plugins = [worker, {'id': 'spatial-learning-tools', 'config': {'includeTools': ['pipeline_run', 'stage_review']}}]
namespace['configure_synthesis_delegation'](plugins)
initial = sorted(namespace['configured_synthesis_tools'](plugins))
configured = json.dumps(worker, sort_keys=True)
namespace['configure_synthesis_delegation'](plugins)
assert configured == json.dumps(worker, sort_keys=True)
options = worker['config']['agentOptions']
plugins.append({'id': 'benchforge-scene-tools', 'config': {}})
with_spatial = sorted(namespace['configured_synthesis_tools'](plugins))
empty = [{'name': '@deepseek-ai/dsh-tool-subagent', 'config': {'provider': 'fork', 'toolFilter': {'deny': ['pipeline_run']}}}]
namespace['configure_synthesis_delegation'](empty)
print(json.dumps({'initial': initial, 'options': options, 'withSpatial': with_spatial,
    'spawnFilter': 'toolFilter' in worker['config'], 'forkFilter': 'toolFilter' in empty[0]['config']}))
`;
  const python = process.env.BENCHFORGE_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const result = JSON.parse(execFileSync(python, ['-B', '-c', program,
    fileURLToPath(new URL('../presets/preset_definition.py', import.meta.url))], {encoding: 'utf8'}));
  assert.deepEqual(result.initial, ['benchforge_pipeline_run', 'benchforge_stage_review']);
  assert.deepEqual(result.options, {provider: 'saved-route', model: 'saved-model'});
  assert.ok(result.withSpatial.includes('benchforge_capture'));
  assert.ok(!result.withSpatial.includes('benchforge_pipeline_evaluate'));
  assert.equal(result.spawnFilter, false);
  assert.equal(result.forkFilter, false);
});

test('preparation selects only supported effort on the route the native child actually inherits', async t => {
  const f = await fixture(t, 6);
  f.setEfforts(['high', 'max']);
  f.parent.options = {provider: 'creation-provider', model: 'creation-model', reasoningEffort: 'max'};
  f.parent.session.requestHeader = () => ({config: {provider: 'qwen-flash', model: 'Qwen/Qwen3.8-Flash-Next', reasoningEffort: 'max'}});
  const result = await f.factory.start(f.request([await f.task('compatible')]));
  assert.equal(f.capabilityRequests[0].provider, 'qwen-flash');
  assert.equal(f.capabilityRequests[0].model, 'Qwen/Qwen3.8-Flash-Next');
  assert.equal(result.reasoningSelection.selectedEffort, 'high');
  assert.deepEqual(result.reasoningSelection.supportedEfforts, ['high', 'max']);
  assert.match(result.reasoningSelection.reason, /does not support low.*supported high/);
  assert.equal(result.tasks[0].reasoningSelection.selectedEffort, 'high');
  assert.deepEqual(f.calls[0].agentOptions, {reasoningEffort: 'high'});
  assert.equal(f.modelRequests.length, 1, 'support-aware preparation must avoid accepted-but-no-model-request failure');
  assert.match(f.modelRequests[0].content[0].text, /Prepare compatible from the frozen plan/);
  assert.equal(f.parent.options.reasoningEffort, 'max');
  f.setEfforts(['off', 'low', 'medium', 'high', 'max']);
  const supportedLow = await f.factory.start(f.request([await f.task('supported-low')], 'supported-low'));
  assert.equal(supportedLow.reasoningSelection.selectedEffort, 'low');
  assert.deepEqual(f.calls.at(-1).agentOptions, {reasoningEffort: 'low'});
  assert.equal(f.parent.options.reasoningEffort, 'max');
  f.setEfforts(['none', 'max']);
  const lighter = await f.factory.start(f.request([await f.task('lighter')], 'lighter'));
  assert.equal(lighter.reasoningSelection.selectedEffort, 'none');
  f.setEfforts(['max']);
  const maxOnly = await f.factory.start(f.request([await f.task('max-only')], 'max-only'));
  assert.equal(maxOnly.acceptedCount, 1);
  assert.equal(maxOnly.reasoningSelection.selectedEffort, 'max');
  assert.match(maxOnly.reasoningSelection.reason, /no supported preferred or lighter.*max.*explicitly/);
  f.setEfforts(['vendor-auto']);
  const opaque = await f.factory.start(f.request([await f.task('opaque')], 'opaque'));
  assert.equal(opaque.reasoningSelection.selectedEffort, 'vendor-auto');
  assert.deepEqual(f.calls.at(-1).agentOptions, {reasoningEffort: 'vendor-auto'});
  f.setReasoningInfo(undefined);
  const withoutControl = await f.factory.start(f.request([await f.task('no-reasoning-control')], 'no-reasoning-control'));
  assert.equal(withoutControl.reasoningSelection.selectionMode, 'not_applicable');
  assert.ok(!('selectedEffort' in withoutControl.reasoningSelection));
  assert.ok(!('agentOptions' in f.calls.at(-1)), 'a model without exposed reasoning control must not receive a fabricated override');
  assert.match(withoutControl.reasoningSelection.reason, /no reasoningEffort override/);
  assert.equal(f.modelRequests.length, 6);
});

test('batch identity binds an optional existing workspace plan and injects its real path into user content', async t => {
  const f = await fixture(t);
  const firstPlan = path.join(f.workspace, 'first-plan.json'), secondPlan = path.join(f.workspace, 'second-plan.json');
  await fs.writeFile(firstPlan, '{}');
  await fs.writeFile(secondPlan, '{}');
  const tasks = [await f.task('plan-bound')];
  const first = await f.factory.start({...f.request(tasks), planPath: firstPlan});
  assert.equal(first.planPath, firstPlan);
  assert.ok(f.modelRequests[0].content[0].text.includes('Saved frozen plan: ' + firstPlan));
  const repeated = await f.factory.start({...f.request(tasks), planPath: path.join(f.workspace, '.', 'first-plan.json')});
  assert.equal(repeated.tasks[0].childId, first.tasks[0].childId);
  assert.equal(f.calls.length, 1);
  await assert.rejects(f.factory.start({...f.request(tasks), planPath: secondPlan}), error => error.status === 409);
  await assert.rejects(f.factory.start({...f.request(tasks, 'missing'), planPath: path.join(f.workspace, 'missing.json')}),
    /must be an existing file/);
  await assert.rejects(f.factory.start({...f.request(tasks, 'directory'), planPath: f.workspace}), /must be a file/);
  const outside = path.join(f.temporary, 'outside-plan.json');
  await fs.writeFile(outside, '{}');
  await assert.rejects(f.factory.start({...f.request(tasks, 'outside'), planPath: outside}), error => error.status === 403);
  assert.equal(f.calls.length, 1);
});

test('workspace scope, distinct outputs and adjustable active-worker budget constrain admission', async t => {
  const f = await fixture(t, 2);
  const tasks = await Promise.all(['scene', 'annotation', 'questions'].map(f.task));
  const outside = path.join(f.temporary, 'other-workspace');
  await fs.mkdir(outside);
  const aliased = path.join(f.workspace, 'outside-link');
  await fs.symlink(outside, aliased, process.platform === 'win32' ? 'junction' : 'dir');
  for (const outputDirectory of [f.workspace, outside, aliased]) {
    await assert.rejects(f.factory.start(f.request([{...tasks[0], outputDirectory}])), error => error.status === 403);
  }
  await assert.rejects(f.factory.start(f.request([tasks[0], {...tasks[1], outputDirectory: tasks[0].outputDirectory}])),
    /non-overlapping output directories/);
  await assert.rejects(f.factory.start({...f.request([tasks[0]]), agentOptions: {reasoningEffort: 'max'}}),
    /Unsupported synthesis request fields/);
  await assert.rejects(f.factory.start(f.request([{...tasks[0], model: 'other-model'}])), /Unsupported synthesis task fields/);
  const first = await f.factory.start(f.request(tasks));
  assert.equal(first.acceptedCount, 2);
  assert.equal(first.state, 'waiting');
  assert.equal(f.calls.length, 2);
  const waiting = await f.factory.start(f.request(tasks));
  assert.equal(f.calls.length, 2);
  assert.match(waiting.reason, /batch budget \(2\)/);
  const wider = createSynthesisSessions({ctx: f.ctx, workspacePath: f.workspace, batchSize: 3});
  const finished = await wider.start(f.request(tasks));
  assert.equal(f.calls.length, 3);
  assert.equal(finished.acceptedCount, 3, 'the workspace budget is configurable rather than a permanent hard cap');
  const lockPath = path.join(path.dirname(finished.recordPath), '.startup.lock');
  await fs.writeFile(lockPath, JSON.stringify({pid: process.pid}));
  try {
    const locked = await f.factory.start(f.request(tasks));
    assert.equal(locked.acceptedCount, 3);
    await assert.rejects(f.factory.start(f.request([{...tasks[0], prompt: 'Different work.'}, ...tasks.slice(1)])),
      error => error.status === 409);
    f.agents.set('session-other', {id: 'session-other', session: {header: {id: 'session-other', cwd: f.workspace}}});
    await assert.rejects(f.factory.start({...f.request(tasks), parentId: 'session-other'}), error => error.status === 409);
  } finally { await fs.unlink(lockPath); }
  const parentCwd = f.parent.session.header.cwd;
  f.parent.session.header.cwd = outside;
  try { await assert.rejects(f.factory.start(f.request(tasks)), error => error.status === 403); }
  finally { f.parent.session.header.cwd = parentCwd; }
});
