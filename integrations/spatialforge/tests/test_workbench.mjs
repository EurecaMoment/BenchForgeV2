import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {createWorkbenchHandler} from '../ui/index.js';
import {loadClient} from '../ui/tests/load_client.mjs';

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
  ' result=r.call("pipeline_run",{"plan":p["plan"]})',
  ' while result["state"]=="waiting_user":',
  '  r.call("stage_review",{"action":"continue","review_id":result["stage_review"]["review_id"]})',
  '  result=r.call("pipeline_run",{"plan":p["plan"],"run":result["run"]})',
  ' outputs.append(result)',
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
    let publicDirectory = path.join(directory, JSON.parse(Buffer.from(version.id, 'base64url').toString())[1]);
    let questionsFile = path.join(publicDirectory, 'questions.jsonl');
    if (!await fs.stat(questionsFile).catch(() => null)) {
      publicDirectory = path.join(publicDirectory, 'public');
      questionsFile = path.join(publicDirectory, 'items.jsonl');
    }
    const questionLines = (await fs.readFile(questionsFile, 'utf8')).trim().split('\n');
    const publicItem = JSON.parse(questionLines[24]);
    const conditions = {tol: {pixel_sep_min_frac: 0.08}, variant: 'Public coordinate convention'};
    const conditionsPath = path.join(publicDirectory, 'media', 'conditions.json');
    await fs.writeFile(conditionsPath, JSON.stringify(conditions));
    const conditionsIndex = publicItem.media.length;
    publicItem.media.push('media/conditions.json');
    questionLines[24] = JSON.stringify(publicItem);
    await fs.writeFile(questionsFile, questionLines.join('\n') + '\n');
    const withConditions = await request({view: 'dataset', dataset: version.id, q: 'item_00000024'});
    assert.ok(withConditions.items[0].media_types.slice(0, -1).every((type) => type === 'image/png'));
    assert.equal(withConditions.items[0].media_types[conditionsIndex], 'application/json');
    const conditionsUrl = new URL(withConditions.items[0].media[conditionsIndex], 'http://dsh.test/');
    const conditionsResponse = await handler(new Request(conditionsUrl));
    assert.equal(conditionsResponse.status, 200);
    assert.equal(conditionsResponse.headers.get('content-type'), 'application/json');
    assert.deepEqual(await conditionsResponse.json(), conditions);
    conditionsUrl.searchParams.set('session_id', 'session-fresh');
    assert.equal((await handler(new Request(conditionsUrl))).status, 403);
    await fs.writeFile(path.join(publicDirectory, 'private-conditions.json'), JSON.stringify({answer: 'PRIVATE_MEDIA_SENTINEL'}));
    publicItem.media.push('media/../private-conditions.json');
    questionLines[24] = JSON.stringify(publicItem);
    await fs.writeFile(questionsFile, questionLines.join('\n') + '\n');
    const outsideMedia = await request({view: 'dataset', dataset: version.id, q: 'item_00000024'});
    const outsideResponse = await handler(new Request('http://dsh.test/' + outsideMedia.items[0].media[conditionsIndex + 1]));
    assert.equal(outsideResponse.status, 403);
    assert.ok(!(await outsideResponse.text()).includes('PRIVATE_MEDIA_SENTINEL'));
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

    let dictionary, component, records, route;
    const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
      useRef: (current) => ({current}), useEffect() {}, useState: (initial) => {
        const value = typeof initial === 'function' ? initial() : initial;
        return [value && typeof value === 'object' && 'key' in value && 'loading' in value
          ? {key: 'fixture', value: records.shift(), loading: false} : value, () => {}];
      }};
    class FixtureParams extends URLSearchParams {toString() {return 'fixture';}}
    const clientSource = await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8');
    const {api: extracted} = loadClient(clientSource, React, {Date, URLSearchParams: FixtureParams,
      localStorage: {getItem: () => JSON.stringify(route)}});
    component = extracted.Workbench;
    dictionary = extracted.dictionaries.zh;
    const expand = (node) => Array.isArray(node) ? node.map(expand) : !node || typeof node !== 'object' ? node :
      typeof node.type === 'function' ? expand(node.type(node.props)) : {...node, children: expand(node.props.children)};
    const text = (node) => Array.isArray(node) ? node.map(text).join(' ') : !node || typeof node !== 'object'
      ? String(node || '') : node.type === 'details' ? '' : text(node.children);
    const render = (stage, explicitRun = '') => {
      route = {version: 3, stage, run: explicitRun};
      records = [progress, summary, selected, {items: []}, {items: [], total: 0, pages: 1, capabilities: []}, null];
      return expand(component({sessionId: 'session-multirecipe', t: (key) => dictionary[key] || key,
        renderFactorySlot: (name, owner) => {
          assert.equal(name, 'conversation.content');
          assert.equal(owner.variant, 'embedded');
          return {type: 'NativeChatFixture', props: {children: []}};
        },
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
    const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
      : node && typeof node === 'object' ? predicate(node) ? node : find(node.children, predicate) : null;
    const sceneProgress = find(scenePage, (node) => node.props['data-stage-progress'] === 'S2');
    assert.equal(sceneProgress.props['data-progress-state'], 'waiting');
    const captureSteps = capture.steps.filter((step) => step.stage === 'S2');
    assert.equal(find(sceneProgress, (node) => node.type === 'progress').props.max, captureSteps.length);
    assert.equal(find(sceneProgress, (node) => node.type === 'progress').props.value,
      captureSteps.filter((step) => step.state === 'completed').length);
    const sceneTab = find(scenePage, (node) => node.props['data-stage'] === 'S2');
    assert.equal(find(sceneTab, (node) => 'data-stage-state' in node.props).props['data-stage-state'], 'waiting');
    assert.match(text(render('S4')), /目标题量.*6/);
    assert.doesNotMatch(text(render('S4')), /目标题量.*12/);
    assert.match(text(render('S1', capture.id)), /Capture production views/);
    assert.doesNotMatch(text(render('S1', capture.id)), /P002-T01/);
    assert.equal((await read({view: 'summary', session_id: 'session-other'})).plan, null);
  } finally {await fs.rm(directory, {recursive: true, force: true});}
});

test('automatic scenes and paired annotations remain visible behind newer canceled and assessment runs', async () => {
  let route, records, requests;
  const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
    useRef: (current) => ({current}), useEffect() {}, useState: (initial) => {
      const value = typeof initial === 'function' ? initial() : initial;
      if (value && typeof value === 'object' && 'key' in value && 'loading' in value) {
        const record = records.shift();
        return [{key: 'fixture', value: record, loading: false}, () => {}];
      }
      return [value, () => {}];
    }};
  class FixtureParams extends URLSearchParams {
    constructor(value) {super(value); requests.push(Object.fromEntries(this));}
    toString() {return 'fixture';}
  }
  const source = await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8');
  const {api} = loadClient(source, React, {Date, URLSearchParams: FixtureParams,
    localStorage: {getItem: () => JSON.stringify(route)}});
  const {Workbench, dictionaries, stageState, sceneProjects} = api;
  const completedScene = {run_id: 'sf_completed', state: 'SUCCEEDED', terminal: true,
    tasks: [{id: 'sf_completed.scene0', state: 'SUCCEEDED', phase: 'capture', workflow: 'scene', revision: 1}]};
  const canceledScene = {run_id: 'sf_canceled', state: 'CANCELED', terminal: true,
    tasks: [{id: 'sf_canceled.scene0', state: 'RUNNING', phase: 'capture', workflow: 'scene', revision: 1}]};
  const pipeline = {id: 'eval-r4', state: 'completed', updated_at: '2026-11-03T00:00:00Z',
    steps: [{stage: 'S4', state: 'completed'}, {stage: 'S5', state: 'completed'}]};
  const plan = {objective: 'Indoor relations', selections: [{template_ids: ['C24-T01'], count: 100, reason: 'Public observations'}]};
  const artifacts = Array.from({length: 7}, (_, index) => ['png', 'json'].map((extension) => ({
    stage: extension === 'png' ? 'S2' : 'S3', kind: extension === 'png' ? 'image' : 'json',
    task_id: 'sf_completed.scene0', revision: 1, file: 'capture/view_' + index + '.' + extension,
    title: 'view_' + index + '.' + extension, url: 'preview/view_' + index + '.' + extension,
  }))).flat();
  const projects = sceneProjects([...artifacts, {kind: 'video', task_id: 'sf_other.scene0', url: 'capture/tour.mp4'}]);
  assert.equal(projects.length, 2);
  assert.equal(projects[0].frames.length, 7);
  assert.equal(projects[1].video.url, 'capture/tour.mp4');
  const expand = (node) => Array.isArray(node) ? node.map(expand) : !node || typeof node !== 'object' ? node :
    typeof node.type === 'function' ? expand(node.type(node.props)) : {...node, children: expand(node.props.children)};
  const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
    : node && typeof node === 'object' ? predicate(node) ? node : find(node.children, predicate) : null;
  const count = (node, predicate) => Array.isArray(node) ? node.reduce((total, child) => total + count(child, predicate), 0)
    : node && typeof node === 'object' ? Number(predicate(node)) + count(node.children, predicate) : 0;
  const render = (stage, production = '') => {
    route = {version: 3, stage, production, dataset: 'dataset-r4'};
    requests = [];
    records = [{pipelines: [pipeline], scenes: {runs: [canceledScene, completedScene]}},
      {runs: [{id: pipeline.id, label: pipeline.id, state: 'completed'}], plan,
        datasets: [{id: 'dataset-r4', run_id: pipeline.id, version: 'eval-r4'}]},
      {plan, state: {state: 'completed'}, steps: [], repairs: [], scene_ids: [canceledScene.run_id], stage_artifacts: []}, {items: production ? [] : artifacts},
      {items: [], capabilities: []}, {items: [], total: 100, all: 100, pages: 5, facets: {templates: [], splits: []}}];
    return expand(Workbench({sessionId: 'session-target', t: (key) => dictionaries.zh[key] || key,
      renderFactorySlot: () => null, useSessions: (select) => select({byId: {'session-target': {cwd: ROOT}}}),
      useSession: (select) => select({running: false, openState: 'open', pendingSubmissions: []}),
      useInput: (select) => select({phase: 'plain', queue: [], draft: '', attachmentIds: []}), inputActions: {}}));
  };
  for (const stage of ['S2', 'S3', 'S4', 'S5']) {
    const page = render(stage);
    for (const id of ['S1', 'S2', 'S3', 'S4', 'S5']) {
      const tab = find(page, (node) => node.props['data-stage'] === id);
      assert.equal(find(tab, (node) => 'data-stage-state' in node.props).props['data-stage-state'], 'completed', stage + '/' + id);
    }
    assert.equal(requests.find((request) => request.view === 'stage_artifacts').scene, completedScene.run_id);
    assert.equal(requests.find((request) => request.view === 'stage_artifacts').run, '');
    if (['S2', 'S3'].includes(stage)) {
      assert.ok(!requests.some((request) => request.view === 'run'));
      assert.equal(count(page, (node) => stage === 'S2' ? 'data-scene-project' in node.props : node.props['data-preview-kind'] === 'json'), stage === 'S2' ? 1 : 7);
      if (stage === 'S3') {
        const productProgress = find(page, (node) => node.type === 'progress' && node.props['aria-label'] === '已保存产物');
        assert.equal(productProgress.props.max, 7);
        assert.equal(productProgress.props.value, 7);
      }
    }
  }
  const explicit = render('S2', canceledScene.run_id);
  assert.equal(requests.find((request) => request.view === 'stage_artifacts').scene, canceledScene.run_id);
  const explicitTab = find(explicit, (node) => node.props['data-stage'] === 'S2');
  assert.equal(find(explicitTab, (node) => 'data-stage-state' in node.props).props['data-stage-state'], 'canceled');
  assert.equal(stageState('S3', null, completedScene, [], null, []), 'unknown');
  assert.equal(stageState('S3', null, completedScene, [], null, artifacts.slice(0, -1)), 'previewable');
  assert.equal(stageState('S3', null, {...completedScene, state: 'RUNNING'}, [], null, artifacts), 'previewable');
});

test('public JSON observations render as text and loading failures remain visible', async () => {
  let states, cursor, effects, responseOk = true;
  const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
    useEffect: (effect) => effects.push(effect), useState: (initial) => {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], (value) => {states[index] = typeof value === 'function' ? value(states[index]) : value;}];
    }};
  const source = await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8');
  const {api} = loadClient(source, React, {AbortController,
    fetch: async () => ({ok: responseOk, status: 415, json: async () => ({tol: {pixel_sep_min_frac: 0.08}, variant: '<plain text>'})})});
  const {PublicObservation} = api;
  const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
    : node && typeof node === 'object' ? predicate(node) ? node : find(node.props.children, predicate) : null;
  const render = (type) => {cursor = 0; return PublicObservation({src: 'public-observation', type, label: 'Observation 2', t: (key) => key});};
  states = []; effects = [];
  assert.ok(!find(render('application/json'), (node) => node.type === 'img'));
  const cleanup = effects.shift()();
  await new Promise(setImmediate);
  const loaded = render('application/json');
  assert.match(find(loaded, (node) => node.type === 'pre').props.children[0], /pixel_sep_min_frac/);
  assert.ok(!find(loaded, (node) => 'dangerouslySetInnerHTML' in node.props));
  cleanup();
  states = []; effects = []; responseOk = false;
  render('application/json'); effects.shift()();
  await new Promise(setImmediate);
  assert.ok(find(render('application/json'), (node) => node.props.role === 'alert'));
  states = []; effects = [];
  find(render('image/png'), (node) => node.type === 'img').props.onError();
  assert.ok(find(render('image/png'), (node) => node.props.role === 'alert'));
});

test('scene playback uses its saved movie on the first render and after reopening', async () => {
  const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
    useState: (value) => [value, () => {}], useEffect: (effect) => effect()};
  const source = await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8');
  const {api} = loadClient(source, React);
  const {SceneVideo, sceneProjects} = api;
  const project = sceneProjects([
    {task_id: 'sf_one.scene0', kind: 'image', url: 'public/view_0.png'},
    {task_id: 'sf_one.scene0', kind: 'video', url: 'public/interaction_0.mp4'},
    {task_id: 'sf_one.scene0', kind: 'video', purpose: 'scene_tour', url: 'public/scene.mp4'},
  ])[0];
  const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
    : node && typeof node === 'object' ? predicate(node) ? node : find(node.props.children, predicate) : null;
  for (let open = 0; open < 2; open++) {
    const rendered = SceneVideo({project, t: (key) => key});
    const movie = find(rendered, (node) => node.type === 'video');
    assert.equal(movie.props.src, 'public/scene.mp4');
    assert.equal(movie.props.preload, 'auto');
    assert.equal(movie.props.controls, true);
    assert.equal(movie.props.autoPlay, true);
    assert.ok(!find(rendered, (node) => node.type === 'canvas' || node.type === 'progress'));
  }
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

test('parent progress and products include verified children while browser query cannot add another session', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-family-'));
  const db = new DatabaseSync(path.join(directory, 'runs.sqlite'));
  try {
    db.exec('CREATE TABLE operations (id TEXT PRIMARY KEY,tool TEXT,state TEXT,artifact TEXT,error TEXT)');
    for (const [id, owner] of [['parent', 'session-parent'], ['child', 'session-child'], ['other', 'session-other']]) {
      const operation = path.join(directory, 'operations', id), run = path.join(operation, 'pipeline_run');
      await fs.mkdir(run, {recursive: true});
      db.prepare('INSERT INTO operations VALUES (?,?,?,?,?)').run(id, 'pipeline_run', 'completed', operation, null);
      await fs.writeFile(path.join(operation, 'request.json'), JSON.stringify({arguments: {}, context: {session_id: owner}}));
      await fs.writeFile(path.join(run, 'plan.json'), JSON.stringify({steps: [
        {id: 'native_capture_review', uses: 'spatialforge.observe', review_stage: 'S2', await_terminal: true}]}));
      await fs.writeFile(path.join(run, 'state.json'), JSON.stringify({state: 'completed',
        context: {session_ids: [owner]}, steps: {native_capture_review: {state: 'completed', result: {state: 'SUCCEEDED'}}}}));
    }
    const handler = createWorkbenchHandler({}, () => [{id: 'workspace', path: directory}],
      async (parent) => parent === 'session-parent' ? [{id: 'session-child', label: '场景设计', state: 'inactive'}] : []);
    const request = (extra) => handler(new Request('http://dsh.test/api/benchforge/workbench?' +
      new URLSearchParams({workspace_path: directory, session_id: 'session-parent', session_ids: 'session-other', ...extra})));
    const progress = await (await request({view: 'progress'})).json();
    assert.deepEqual(progress.operations.map((row) => row.id).sort(), ['child', 'parent']);
    assert.equal(progress.pipelines.length, 2);
    assert.ok(progress.pipelines.every((row) => row.steps[0].stage === 'S2'));
    assert.equal(progress.parallel_tasks[0].state, 'inactive');
    assert.equal(progress.association, 'parent_and_verified_child_context');
    const child = progress.pipelines.find((row) => row.session_id === 'session-child');
    assert.equal((await request({view: 'run_product', product: 'plan', run: child.id})).status, 200);
    const other = Buffer.from(JSON.stringify(['workspace', 'operations/other/pipeline_run'])).toString('base64url');
    assert.equal((await request({view: 'run', run: other})).status, 403);
    assert.ok(!(await (await request({view: 'summary'})).json()).runs.some((row) => row.id === other));
  } finally {db.close(); await fs.rm(directory, {recursive: true, force: true});}
});

test('BenchForgeV2_UI preserves legacy SpatialForge sessions and leaves both headless presets alone', async () => {
  const source = await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8');
  const {api: plugin} = loadClient(source, {createElement: (type, props) => ({type, props})});
  const observable = (value) => {
    const listeners = new Set();
    return {getSnapshot: () => value, subscribe: (fn) => {listeners.add(fn); return () => listeners.delete(fn);},
      set: (next) => {value = next; for (const fn of [...listeners]) fn();}};
  };
  const preset = observable('standard'), slots = new Map(), seats = [], effects = [];
  const current = observable({key: 'fresh-sf', keyedHooks: {projection: () => preset}});
  let removed = 0;
  plugin.apply({
    locale: {register: (_ns, dictionaries) => {
      assert.deepEqual(Object.keys(dictionaries.zh), Object.keys(dictionaries.en)); return () => {};
    }, bind: () => (key) => key},
    uiSession: {adapter: {current}}, sessions: {},
    effect: (fn) => effects.push(fn()),
    slots: {inject: (seat, fn) => {seats.push(seat); effects.push(fn());}, register: (options, component) => {
      assert.equal(options.name, 'main.conversation'); assert.equal(options.priority, -20);
      assert.equal(options.children?.['conversation.view'], undefined, 'the native conversation.view is already declared by DSH and must not be registered twice');
      slots.set(options.name, component); return () => {removed++; slots.delete(options.name);};
    }},
  });
  assert.deepEqual(seats, ['main.conversation']);
  assert.equal(slots.size, 0, 'ordinary environments retain their original conversation');
  for (const headless of ['benchforge', 'benchforgev2']) {
    preset.set(headless);
    assert.equal(slots.size, 0, headless + ' must retain the standard conversation');
  }
  preset.set('spatialforge-standard-ptc');
  const main = slots.get('main.conversation');
  assert.equal(typeof main, 'function');
  assert.equal(main({sessionId: 'fresh-sf'}).props.key, 'fresh-sf');
  assert.equal(main({sessionId: 'existing-sf'}).props.key, 'existing-sf');
  preset.set(undefined);
  assert.equal(slots.get('main.conversation'), main, 'a transient unresolved preset retains the active main view');
  current.set({key: 'fresh-sf', keyedHooks: {projection: () => preset}});
  assert.equal(slots.get('main.conversation'), main, 'rebinding the same session cannot expose the old chat');
  const rebound = observable(undefined);
  current.set({key: 'fresh-sf', keyedHooks: {projection: () => rebound}});
  assert.equal(slots.get('main.conversation'), main, 'a new projection hook for the same session retains component identity');
  rebound.set('spatialforge-standard-ptc');
  assert.equal(slots.get('main.conversation'), main);
  preset.set('benchforgev2');
  assert.equal(slots.get('main.conversation'), main, 'the previous detached preset hook has no effect');
  rebound.set('benchforgev2');
  assert.equal(slots.size, 0, 'leaving SpatialForge removes the shadow rather than rendering null');
  assert.equal(removed, 1);
  rebound.set('spatialforge-standard-ptc');
  current.set({key: 'other-session', keyedHooks: {projection: () => observable(undefined)}});
  assert.equal(slots.size, 0, 'an unresolved different session must not inherit the SpatialForge workbench');
  assert.equal(removed, 2);
  current.set({key: 'fresh-sf', keyedHooks: {projection: () => preset}});
  preset.set('spatialforge-standard-ptc');
  effects.filter((fn) => typeof fn === 'function').reverse().forEach((fn) => fn());
  assert.equal(slots.size, 0);
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

