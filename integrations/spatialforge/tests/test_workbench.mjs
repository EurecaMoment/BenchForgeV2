import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import vm from 'node:vm';
import {createWorkbenchHandler} from '../ui/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const fixtureCode = [
  'import json,sys',
  'from pathlib import Path',
  'from benchforge_core.runtime import Runtime',
  'root=Path(sys.argv[1])',
  'r=Runtime(root)',
  'outputs=[]',
  'for seed,count in [(101,30),(202,3)]:',
  ' p=r.call("pipeline_plan",{"template_ids":["C01-T01"],"target_items":count,"seed":seed})',
  ' outputs.append(r.call("pipeline_run",{"plan":p["plan"]}))',
  'r.close()',
  'print(json.dumps(outputs))',
].join('\n');

test('real persisted pipelines: session-workspace isolation, public pagination, contracts and no mutation', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-'));
  const otherDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-other-'));
  try {
    const outputs = JSON.parse(execFileSync(python, ['-c', fixtureCode, directory], {
      cwd: ROOT, env: {...process.env, PYTHONPATH: path.join(ROOT, 'src'), BENCHFORGE_DSH_SESSION_ID: 'session-fixture'}, encoding: 'utf8',
    }));
    const dbStat = await fs.stat(path.join(directory, 'runs.sqlite'));
    const handler = createWorkbenchHandler({}, () => [
      {id: 'registered-workspace', path: directory, title: 'Actual fixture'},
      {id: 'other-workspace', path: otherDirectory, title: 'Other environment'},
    ]);
    const request = async (params) => {
      const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({workspace_path: directory, session_id: 'session-fixture', ...params})));
      assert.equal(response.status, 200, await response.clone().text());
      return response.json();
    };
    const summary = await request({view: 'summary'});
    assert.deepEqual(summary.sources.map((source) => source.workspace), ['Actual fixture']);
    assert.equal(summary.runs.length, 2);
    assert.equal(summary.datasets.length, 2);
    const progress = await request({view: 'progress'});
    assert.ok(progress.pipelines.some((run) => run.steps.some((step) => step.uses === 'data.package' && step.stage === 'S5')));
    const fresh = await request({view: 'summary', session_id: 'session-fresh'});
    assert.deepEqual(fresh.runs, []);
    assert.deepEqual(fresh.datasets, []);
    assert.deepEqual((await request({view: 'progress', session_id: 'session-fresh'})).pipelines, []);
    const missingSession = await request({view: 'summary', session_id: ''});
    assert.deepEqual(missingSession.runs, []);
    assert.equal(summary.counts.verified, 0);
    assert.ok(summary.counts.candidate > 0);
    const version = summary.datasets.find((x) => x.report.accepted === 30);
    const small = summary.datasets.find((x) => x.report.accepted === 3);
    assert.notEqual(version.id, small.id);
    const otherSummary = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({view: 'summary', workspace_path: otherDirectory})));
    assert.deepEqual((await otherSummary.json()).runs, []);
    const unscopedSummary = await handler(new Request('http://dsh.test/api/benchforge/workbench?view=summary'));
    assert.deepEqual((await unscopedSummary.json()).runs, []);
    const secondPage = await request({view: 'dataset', dataset: version.id, page: 2, page_size: 24});
    assert.equal(secondPage.total, 30);
    assert.equal(secondPage.items.length, 6);
    assert.equal(secondPage.items[0].item_id, 'item_00000024');
    assert.equal(secondPage.authority_exposed, false);
    const other = await request({view: 'dataset', dataset: small.id});
    assert.equal(other.total, 3);
    const crossWorkspace = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({
      view: 'dataset', dataset: version.id, workspace_path: otherDirectory,
    })));
    assert.equal(crossWorkspace.status, 404);
    const filtered = await request({view: 'dataset', dataset: version.id, q: 'item_00000024', template: 'C01-T01', split: 'train'});
    assert.equal(filtered.total, 1);
    assert.equal(filtered.items[0].item_id, 'item_00000024');
    const media = await handler(new Request('http://dsh.test/' + filtered.items[0].media[0]));
    assert.equal(media.status, 200);
    assert.match(media.headers.get('content-type'), /^image\//);
    const details = await request({view: 'run', run: version.run_id});
    const unrelatedRun = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({
      workspace_path: directory, session_id: 'session-fresh', view: 'run', run: version.run_id,
    })));
    assert.equal(unrelatedRun.status, 403);
    const unrelatedDataset = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({
      workspace_path: directory, session_id: 'session-fresh', view: 'dataset', dataset: version.id,
    })));
    assert.equal(unrelatedDataset.status, 403);
    assert.ok(details.artifacts.every((x) => x.status === 'candidate'));
    assert.equal(details.plan.steps[0].uses, 'templates.produce');
    assert.equal(details.plan.selections[0].count, 30);
    assert.equal(details.plan.template_contracts[0].id, 'C01-T01');
    assert.ok(details.stage_artifacts.some((row) => row.stage === 'S1'));
    assert.ok(details.stage_artifacts.some((row) => row.stage === 'S4'));
    const qualityProduct = details.stage_artifacts.find((row) => row.stage === 'S5');
    assert.equal(qualityProduct.data.accepted, 30);
    const productResponse = await handler(new Request('http://dsh.test/' + qualityProduct.url));
    assert.equal(productResponse.status, 200);
    assert.equal((await productResponse.json()).accepted, 30);
    assert.equal((await fs.stat(path.join(directory, 'runs.sqlite'))).mtimeMs, dbStat.mtimeMs);

    const runFolder = path.join(directory, JSON.parse(Buffer.from(version.run_id, 'base64url').toString())[1]);
    const savedPlanFile = path.join(runFolder, 'plan.json');
    const savedPlan = JSON.parse(await fs.readFile(savedPlanFile, 'utf8'));
    savedPlan.authority = 'PRIVATE_PLAN_SENTINEL';
    savedPlan.inputs.operator_token = 'PRIVATE_PLAN_SENTINEL';
    savedPlan.selections[0].oracle = 'PRIVATE_PLAN_SENTINEL';
    savedPlan.template_contracts[0].answer = 'PRIVATE_PLAN_SENTINEL';
    await fs.writeFile(savedPlanFile, JSON.stringify(savedPlan));
    const projected = await request({view: 'run', run: version.run_id});
    assert.ok(!JSON.stringify(projected.plan).includes('PRIVATE_PLAN_SENTINEL'));
    const savedStateFile = path.join(runFolder, 'state.json');
    const savedState = JSON.parse(await fs.readFile(savedStateFile, 'utf8'));
    savedState.steps.scene = {state: 'completed', result: {run_id: 'sf_savedscene'}};
    savedState.steps.nested = {state: 'completed', result: {steps: {capture: {result: {run_id: 'sf_nestedscene'}}}}};
    await fs.writeFile(savedStateFile, JSON.stringify(savedState));
    const sceneReferences = await request({view: 'run', run: version.run_id});
    assert.deepEqual(sceneReferences.scene_ids, ['sf_savedscene', 'sf_nestedscene']);

    // A public allowlist still removes accidentally added authority fields.
    const questions = path.join(outputs[0].outputs.questions.dataset, 'questions.jsonl');
    const lines = (await fs.readFile(questions, 'utf8')).trim().split('\n');
    const row = JSON.parse(lines[0]);
    row.answer = 'PRIVATE_ORACLE_SENTINEL';
    row.authority = {oracle: 'PRIVATE_ORACLE_SENTINEL'};
    lines[0] = JSON.stringify(row);
    await fs.writeFile(questions, lines.join('\n') + '\n');
    const response = await request({view: 'dataset', dataset: version.id});
    assert.ok(!JSON.stringify(response).includes('PRIVATE_ORACLE_SENTINEL'));
    const escape = Buffer.from(JSON.stringify(['registered-workspace', '..'])).toString('base64url');
    const workspaceParam = 'workspace_path=' + encodeURIComponent(directory) + '&session_id=session-fixture';
    assert.equal((await handler(new Request('http://dsh.test/api/benchforge/workbench?view=dataset&dataset=' + escape + '&' + workspaceParam))).status, 403);
    const invalidPage = await handler(new Request('http://dsh.test/api/benchforge/workbench?view=dataset&dataset=' + version.id + '&page=-1&' + workspaceParam));
    assert.equal(invalidPage.status, 400);
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
    await fs.rm(otherDirectory, {recursive: true, force: true});
  }
});

test('missing manifest counts remain unknown and an empty index is not invented as verified data', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-empty-'));
  try {
    const handler = createWorkbenchHandler({workspacePaths: [directory]});
    const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({workspace_path: directory})));
    const summary = await response.json();
    assert.equal(summary.counts, null);
    assert.deepEqual(summary.runs, []);
    assert.equal(summary.sources[0].status, 'no_index');
  } finally { await fs.rm(directory, {recursive: true, force: true}); }
});

test('the current conversation can inspect a saved plan before any pipeline execution', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-plan-'));
  try {
    const code = ['import json,sys', 'from benchforge_core.runtime import Runtime',
      'r=Runtime(sys.argv[1])',
      'print(json.dumps(r.call("pipeline_plan", {"objective":"Measure distances", "template_ids":["C01-T01"], "target_items":12})))',
      'r.close()'].join('\n');
    const saved = JSON.parse(execFileSync(python, ['-c', code, directory], {cwd: ROOT, encoding: 'utf8',
      env: {...process.env, PYTHONPATH: path.join(ROOT, 'src'), BENCHFORGE_DSH_SESSION_ID: 'session-planning'}}));
    const raw = JSON.parse(await fs.readFile(saved.plan, 'utf8'));
    raw.inputs.operator_token = 'PRIVATE_PLAN_SENTINEL';
    raw.authority = 'PRIVATE_PLAN_SENTINEL';
    await fs.writeFile(saved.plan, JSON.stringify(raw));
    const handler = createWorkbenchHandler({}, () => [{id: 'workspace', path: directory}]);
    const read = async (session_id) => (await handler(new Request('http://dsh.test/api/benchforge/workbench?' +
      new URLSearchParams({view: 'summary', workspace_path: directory, session_id})))).json();
    const current = await read('session-planning');
    assert.deepEqual(current.runs, []);
    assert.equal(current.plan.objective, 'Measure distances');
    assert.equal(current.plan.selections[0].count, 12);
    assert.equal(current.plan_source.operation_id, saved.operation_id);
    assert.ok(!JSON.stringify(current.plan).includes('PRIVATE_PLAN_SENTINEL'));
    assert.equal((await read('session-fresh')).plan, null);
  } finally {await fs.rm(directory, {recursive: true, force: true});}
});

test('automatic assessment products retain explicit template intent while a separate capture is waiting', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-multirecipe-'));
  try {
    const code = ['import json,sys', 'from benchforge_core.runtime import Runtime',
      'r=Runtime(sys.argv[1])',
      'assessment=r.call("pipeline_plan", {"pipeline_id":"data.capability","objective":"Measure object visibility","selections":[{"template_ids":["P002-T01","P002-T02"],"count":6,"reason":"Observe the selected scene from recorded viewpoints"}]})',
      'capture=r.call("pipeline_plan", {"pipeline_id":"scene.capture","objective":"Capture production views","inputs":{"scene_program_path":"scene.json"}})',
      'r.close()', 'print(json.dumps({"assessment":assessment,"capture":capture}))'].join('\n');
    const saved = JSON.parse(execFileSync(python, ['-c', code, directory], {cwd: ROOT, encoding: 'utf8',
      env: {...process.env, PYTHONPATH: path.join(ROOT, 'src'), BENCHFORGE_DSH_SESSION_ID: 'session-multirecipe'}}));
    const operation = path.join(directory, 'operations', 'capture-run'), runFolder = path.join(operation, 'pipeline_run');
    await fs.mkdir(runFolder, {recursive: true});
    await fs.copyFile(saved.capture.plan, path.join(runFolder, 'plan.json'));
    await fs.writeFile(path.join(operation, 'request.json'), JSON.stringify({arguments: {}, context: {session_id: 'session-multirecipe'}}));
    await fs.writeFile(path.join(runFolder, 'state.json'), JSON.stringify({state: 'waiting', step: 'capture_ready',
      context: {session_ids: ['session-multirecipe']}, steps: {
        capture: {state: 'completed', result: {run_id: 'sf_capturefixture'}},
        capture_ready: {state: 'waiting', result: {run_id: 'sf_capturefixture'}},
      }}));
    const db = new DatabaseSync(path.join(directory, 'runs.sqlite'));
    try {db.prepare('INSERT INTO operations(id,tool,state,artifact) VALUES (?,?,?,?)').run('capture-run', 'pipeline_run', 'completed', operation);}
    finally {db.close();}
    const handler = createWorkbenchHandler({}, () => [{id: 'workspace', path: directory}]);
    const read = async (params) => {
      const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' +
        new URLSearchParams({workspace_path: directory, session_id: 'session-multirecipe', ...params})));
      assert.equal(response.status, 200, await response.clone().text());
      return response.json();
    };
    const summary = await read({view: 'summary'}), progress = await read({view: 'progress'});
    assert.equal(summary.plan_source.operation_id, saved.assessment.operation_id);
    assert.equal(summary.plan.pipeline_id, 'data.capability');
    assert.equal(summary.plan.selections[0].count, 6);
    assert.deepEqual(summary.plan.selections[0].template_ids, ['P002-T01', 'P002-T02']);
    const capture = progress.pipelines[0], selected = await read({view: 'run', run: capture.id});
    assert.equal(selected.plan.pipeline_id, 'scene.capture');
    assert.equal(capture.steps.find((step) => step.id === 'capture_ready').stage, 'S2');
    assert.equal(capture.current.id, 'capture_ready');
    assert.equal(capture.current.state, 'waiting');
    assert.equal(capture.completed, 1);
    assert.equal(capture.total, 2);

    let registration, dictionary, component, records, route;
    const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
      useRef: (current) => ({current}), useEffect() {}, useState: (initial) => {
        const value = typeof initial === 'function' ? initial() : initial;
        return [value && typeof value === 'object' && 'key' in value && 'loading' in value
          ? {key: 'fixture', value: records.shift(), loading: false} : value, () => {}];
      }};
    class FixtureParams extends URLSearchParams {toString() {return 'fixture';}}
    vm.runInNewContext(await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8'), {
      window: {__ModuleLoader__: {load: (value) => {registration = value;}}}, Date, URLSearchParams: FixtureParams,
      localStorage: {getItem: () => JSON.stringify(route)},
    });
    registration.factory(() => React).apply({effect: (effect) => effect(),
      locale: {register: (_, values) => {dictionary = values.zh;}, bind: () => (key) => dictionary[key] || key},
      sidebarRight: {}, sidebarRightTabs: {register() {}},
      slots: {inject: (_, effect) => effect(), register: (options, view) => {
        if (options.key === 'benchforge-spatialforge-evaluation') component = view;
      }},
    });
    const expand = (node) => Array.isArray(node) ? node.map(expand) : !node || typeof node !== 'object' ? node :
      typeof node.type === 'function' ? expand(node.type(node.props)) : {...node, children: expand(node.props.children)};
    const text = (node) => Array.isArray(node) ? node.map(text).join(' ') : !node || typeof node !== 'object'
      ? String(node || '') : node.type === 'details' ? '' : text(node.children);
    const render = (stage, explicitRun = '') => {
      route = {version: 3, stage, run: explicitRun};
      records = [progress, summary, selected, {items: []}, {items: [], total: 0, pages: 1, capabilities: []}, null];
      return expand(component({sessionId: 'session-multirecipe', useProjection: () => 'spatialforge-standard-ptc',
        useSessions: (select) => select({byId: {'session-multirecipe': {cwd: directory}}}),
        useSession: (select) => select({running: true, openState: 'open', pendingSubmissions: []}),
        useConversation: (select) => select({views: {get: () => ({legacy: {runningCalls: [], nodes: []}})}}),
        useInput: (select) => select({phase: 'plain', queue: [], draft: '', attachmentIds: []}), inputActions: {},
      }));
    };
    assert.match(text(render('S1')), /Measure object visibility/);
    assert.match(text(render('S1')), /P002-T01, P002-T02/);
    assert.match(text(render('S1')), /本组总题数.*6/);
    assert.doesNotMatch(text(render('S1')), /Capture production views/);
    const scenePage = render('S2');
    assert.match(text(scenePage), /capture_ready/);
    const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
      : node && typeof node === 'object' ? predicate(node) ? node : find(node.children, predicate) : null;
    const sceneTab = find(scenePage, (node) => node.props['data-stage'] === 'S2');
    assert.equal(find(sceneTab, (node) => 'data-stage-state' in node.props).props['data-stage-state'], 'waiting');
    assert.match(text(render('S4')), /目标题量.*6/);
    assert.doesNotMatch(text(render('S4')), /目标题量.*12/);
    assert.match(text(render('S1', capture.id)), /Capture production views/);
    assert.doesNotMatch(text(render('S1', capture.id)), /P002-T01/);
    assert.equal((await read({view: 'summary', session_id: 'session-other'})).plan, null);
  } finally {await fs.rm(directory, {recursive: true, force: true});}
});

test('production observations follow persisted running/waiting/failed/completed transitions without changing records', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-progress-'));
  const operation = path.join(directory, 'operations', 'progress-fixture');
  const run = path.join(operation, 'pipeline_run');
  await fs.mkdir(run, {recursive: true});
  const db = new DatabaseSync(path.join(directory, 'runs.sqlite'));
  try {
    db.exec('CREATE TABLE operations (id TEXT PRIMARY KEY,tool TEXT,state TEXT,artifact TEXT,error TEXT)');
    db.prepare('INSERT INTO operations VALUES (?,?,?,?,?)').run('progress-fixture', 'pipeline_run', 'running', operation, null);
    await fs.writeFile(path.join(operation, 'request.json'), JSON.stringify({time: '2026-10-28T10:00:00Z', arguments: {}, context: {session_id: 'session-progress'}}));
    await fs.writeFile(path.join(run, 'plan.json'), JSON.stringify({steps: [
      {id: 'scene', uses: 'spatialforge.capture'}, {id: 'items', uses: 'templates.produce'}, {id: 'report', uses: 'templates.package'},
    ]}));
    const handler = createWorkbenchHandler({}, () => [{id: 'progress-workspace', path: directory}]);
    const request = () => handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({view: 'progress', workspace_path: directory, session_id: 'session-progress'})));
    const snapshot = async (state, steps) => {
      const file = path.join(run, 'state.json');
      await fs.writeFile(file, JSON.stringify({state, steps}));
      const before = (await fs.stat(file)).mtimeMs;
      const response = await request();
      assert.equal(response.status, 200);
      const result = await response.json();
      assert.equal((await fs.stat(file)).mtimeMs, before);
      assert.equal(result.pipelines[0].state, state);
      assert.equal(result.pipelines[0].total, 3);
      return result.pipelines[0];
    };
    const running = await snapshot('running', {});
    assert.equal(running.completed, 0);
    assert.equal(running.current.stage, 'S2');
    assert.equal(running.current.state, 'unknown'); // No invented per-step execution status.
    const steps = {scene: {state: 'completed'}};
    const waiting = await snapshot('needs_evidence', {...steps, items: {state: 'needs_evidence'}});
    assert.equal(waiting.completed, 1);
    assert.equal(waiting.current.stage, 'S4');
    const failed = await snapshot('failed', {...steps, items: {state: 'failed', error: 'fixture missing camera'}});
    assert.equal(failed.current.error, 'fixture missing camera');
    const complete = await snapshot('completed', {...steps, items: {state: 'completed'}, report: {state: 'completed'}});
    assert.equal(complete.completed, 3);
    assert.equal(complete.current, undefined);
    assert.equal(db.prepare('SELECT state FROM operations').get().state, 'running');
    await fs.writeFile(path.join(operation, 'request.json'), JSON.stringify({arguments: {}}));
    const unassociated = await (await request()).json();
    assert.deepEqual(unassociated.pipelines, []);
    assert.equal(unassociated.unassociated_records, 1);
    const unscoped = await handler(new Request('http://dsh.test/api/benchforge/workbench?view=progress'));
    assert.deepEqual((await unscoped.json()).operations, []);
  } finally {db.close(); await fs.rm(directory, {recursive: true, force: true});}
});

test('evaluation launcher is gated to SpatialForge and opens its right-side session panel', async () => {
  let registration;
  vm.runInNewContext(await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8'),
    {window: {__ModuleLoader__: {load: (value) => registration = value}}});
  assert.equal(registration.id, '@eurecamoment/benchforge-spatialforge-ui');
  const plugin = registration.factory((id) => {
    assert.equal(id, 'react');
    return {createElement: (type, props, ...children) => ({type, props: props || {}, children})};
  });
  const seats = [], disposed = [], opened = [], components = new Map();
  let definition;
  plugin.apply({
    locale: {register: (_ns, dictionaries) => {
      assert.deepEqual(Object.keys(dictionaries.zh), Object.keys(dictionaries.en));
      return () => disposed.push('locale');
    }, bind: () => (key) => key},
    effect: (effect) => { const cleanup = effect(); disposed.push(cleanup); },
    sidebarRight: {openTab: (kind) => opened.push(kind)},
    sidebarRightTabs: {register: (value) => { definition = value; return () => {}; }},
    slots: {inject: (seat, callback) => { seats.push(seat); callback(); }, register: (options, component) => {
      components.set(options.id || options.key, component);
      return () => {};
    }},
  });
  assert.deepEqual(seats, ['sidebar.right.pane.tab', 'conversation.session.header.utilities', 'conversation.input.right']);
  assert.equal(definition.kind, 'benchforge-spatialforge-evaluation');
  assert.equal(definition.guide, undefined);
  const launcher = components.get('spatialforge-evaluation-launcher');
  assert.equal(launcher({useProjection: () => 'benchforgev2'}), null);
  const spatialForgeButton = launcher({useProjection: () => 'spatialforge-standard-ptc'});
  assert.equal(spatialForgeButton.type, 'button');
  spatialForgeButton.props.onClick();
  assert.deepEqual(opened, ['benchforge-spatialforge-evaluation']);
  const emptyLauncher = components.get('spatialforge-empty-evaluation-launcher');
  const blank = {useSession: (select) => select({blank: true})};
  assert.equal(emptyLauncher({...blank, useProjection: () => 'benchforgev2'}), null);
  assert.equal(emptyLauncher({useSession: (select) => select({blank: false}), useProjection: () => 'spatialforge-standard-ptc'}), null);
  const emptyButton = emptyLauncher({...blank, useProjection: () => 'spatialforge-standard-ptc'});
  assert.equal(emptyButton.type, 'button');
  emptyButton.props.onClick();
  assert.equal(opened.length, 2);
  assert.equal(components.get('benchforge-spatialforge-evaluation')({useProjection: () => 'benchforgev2'}), null);
  disposed.find((entry) => typeof entry === 'function')();
  assert.ok(disposed.includes('locale'));
});

test('template selector pages the real catalog and filters by capability without exposing oracle fields', async () => {
  const handler = createWorkbenchHandler({});
  const query = async (params) => {
    const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({view: 'catalog', ...params})));
    assert.equal(response.status, 200);
    return response.json();
  };
  const first = await query({});
  const second = await query({page: '2'});
  assert.equal(first.task_count, 89);
  assert.equal(first.template_count, 267);
  assert.equal(first.items.length, 12);
  assert.notEqual(first.items[0].id, second.items[0].id);
  const selected = await query({q: 'C01-T01', capability: 'N01'});
  assert.equal(selected.total, 1);
  assert.equal(selected.items[0].id, 'C01-T01');
  assert.ok(!('effective_oracle' in selected.items[0]));
  const mismatch = await query({q: 'C01-T01', capability: 'N27'});
  assert.equal(mismatch.total, 0);
});

