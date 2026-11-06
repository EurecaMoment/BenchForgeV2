import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const client = readFileSync(new URL('../client.js', import.meta.url), 'utf8');
const marker = "    return {\n      inject: ['slots', 'locale', 'uiSession', 'sessions', 'uiConversation'],";
assert.ok(client.includes(marker));
const instrumented = client.replace(marker,
  '    globalThis.testApi = {sceneCollectionProgress, stageState, StageProgress, executionStage, currentGeneration, productionProductsRevision, dictionaries};\n' + marker);
const context = {window: {__ModuleLoader__: {load({factory}) {factory((id) => {
  assert.equal(id, 'react');
  return {createElement: (type, props, ...children) => ({type, props: props || {}, children}), Fragment: 'fragment'};
});}}}};
vm.runInNewContext(instrumented, context, {filename: 'candidate-client.js'});
const api = context.testApi;
const t = (key) => api.dictionaries.zh[key] || key;
const plan = {assessment: {scenes: {target_scene_count: 3, designs: [
  {id: 'design-office', scene_id: 'sf_office', name: '办公室工作区'},
  {id: 'design-lounge', scene_id: 'sf_lounge', name: '起居会客角'},
  {id: 'design-study', scene_id: 'sf_study', name: '阅览茶水角'},
]}}};
const collection = {status: 'current', target: 3, accepted: 3, complete: true, ledger_version: 6,
  plan_path: '/controlled/current/plan.json', rows: plan.assessment.scenes.designs.map((row, index) => ({
    design_id: row.id, scene_id: row.scene_id, name: row.name, run_id: 'sf_current' + index,
    task_id: 'sf_current' + index + '.scene0', revision: 0, state: 'completed', captured_view_count: 8,
  }))};
const old = [{run_id: 'sf_old', state: 'CANCELED', terminal: true, tasks: [{id: 'sf_old.scene0', scene_id: 'sf_office',
  name: '办公室工作区', workflow: 'scene', state: 'RUNNING', progress: {stage: 'desktop_capture_queued'}}]}];
function generation(change = {}) {return {schema: 'bench-office100-generation-progress-v1', source: 'generation_progress',
  association: 'current_applied_plan', run_id: 'items-controlled', target_items: 100, state: 'running', phase: 'writing',
  fresh: true, process_alive: true, heartbeat_at: Date.now() / 1000, written_count: 17, verified_count: 13,
  candidate_count: 100, published_count: 0, ...change};}
function nodes(value) {return Array.isArray(value) ? value.flatMap(nodes) :
  value && typeof value === 'object' ? [value, ...nodes(value.children)] : [];}
function text(value) {return Array.isArray(value) ? value.map(text).join(' ') :
  value && typeof value === 'object' ? text(value.children) : value == null ? '' : String(value);}
function render(stage, value, pipeline = null) {return api.StageProgress({stage: {id: stage, key: stage === 'S2' ? 'collection' : 'synthesis'},
  collectionPlan: plan, pipeline, record: {value, updatedAt: new Date().toISOString()}, conversationRunning: false, t});}

test('current native registrations display 3/3 while prior queued receipts stay in details', () => {
  const tree = render('S2', {current_collection: collection, scenes: {status: 'partial', runs: old}});
  const rail = nodes(tree).find((node) => node.type === 'progress');
  assert.equal(rail.props.max, 3);
  assert.equal(rail.props.value, 3);
  assert.equal(tree.props['data-progress-state'], 'completed');
  assert.match(text(tree), /已通过 3 \/ 3/);
  assert.match(text(tree), /desktop_capture_queued/);
  assert.match(text(tree), /采集回执详情/);
});

test('pending or mismatched registrations cannot complete a newly displayed plan', () => {
  for (const saved of [{...collection, status: 'pending'}, {...collection, accepted: 2},
    {...collection, rows: collection.rows.map((row) => ({...row, design_id: 'other-' + row.design_id}))}]) {
    const result = api.sceneCollectionProgress(plan, old, saved);
    assert.equal(result.passed, 0);
    assert.notEqual(result.state, 'completed');
  }
});

test('live independent generator keeps real counters and selects S4 when parent is idle', () => {
  const generated = generation();
  const states = {S1: 'completed', S2: 'failed', S4: 'failed'};
  assert.equal(api.executionStage({id: 'S2'}, states, false, [], generated).id, 'S4');
  assert.equal(api.stageState('S4', null, null, [], null, [], null, generated), 'running');
  const tree = render('S4', {generation: generated, scenes: {status: 'unavailable', runs: []}});
  const rail = nodes(tree).find((node) => node.type === 'progress');
  assert.equal(tree.props['data-progress-state'], 'running');
  assert.equal(rail.props.value, 17);
  assert.equal(rail.props.max, 100);
  assert.match(text(tree), /已写出 17 \/ 100/);
  assert.match(text(tree), /公开校验通过 13 \/ 100/);
  assert.match(text(tree), /已发布 0/);
});

test('100 written with 89 public passes shows 11 repairs; generator completion still waits for admission', () => {
  const legacy = generation({source: 'legacy_summary', association: 'current_plan_path_after_save',
    state: 'incomplete', fresh: false, process_alive: false, phase: 'complete',
    written_count: 100, verified_count: 89, published_count: null, candidate_count: null});
  const tree = render('S4', {generation: legacy});
  assert.equal(tree.props['data-progress-state'], 'needs_evidence');
  assert.equal(nodes(tree).find((node) => node.type === 'progress').props.value, 89);
  assert.match(text(tree), /公开校验通过 89 \/ 100/);
  assert.match(text(tree), /待修题目 11/);
  const repair = generation({written_count: 100, verified_count: 89, repair_candidate_verified_count: 4});
  const repairTree = render('S4', {generation: repair});
  const repairBar = nodes(repairTree).find((node) => node.type === 'progress' && node.props['aria-label'] === t('generationRepairVerified'));
  assert.equal(repairBar.props.value, 4);
  assert.equal(repairBar.props.max, 11);
  assert.equal(nodes(repairTree).find((node) => node.type === 'progress').props.value, 89);
  const complete = generation({state: 'complete', written_count: 100, verified_count: 100, published_count: 0});
  assert.equal(api.stageState('S4', null, null, [], null, [], null, complete), 'waiting');
  assert.match(text(render('S4', {generation: complete})), /生成结束，待入库/);
  assert.equal(api.stageState('S4', {steps: [{stage: 'S4', state: 'completed'}]}, null, [], null, [], null, complete), 'completed');
});

test('finished generation preserves the current formal admission state while superseding history', () => {
  const complete = generation({state: 'complete', written_count: 100, verified_count: 100, published_count: 0});
  for (const state of ['failed', 'running', 'paused', 'needs_input', 'waiting_user', 'canceled']) {
    assert.equal(api.stageState('S4', {steps: [{stage: 'S4', state}]}, null, [], null, [], null, complete), state);
  }
  assert.equal(api.stageState('S4', null, null, [{stage: 'S4', state: 'failed'}], null, [], null, complete), 'waiting');
});

test('stale or dead generators stop activity; heartbeats and live counters do not refetch saved products', () => {
  for (const generated of [generation({process_alive: false}), generation({heartbeat_at: Date.now() / 1000 - 45})]) {
    assert.equal(api.currentGeneration(generated).state, 'incomplete');
    assert.notEqual(api.stageState('S4', null, null, [], null, [], null, generated), 'running');
  }
  const before = {current_collection: collection, generation: generation()};
  const after = {current_collection: collection, generation: generation({written_count: 18, heartbeat_at: Date.now() / 1000 + 0.01})};
  assert.equal(api.productionProductsRevision(before), api.productionProductsRevision(after));
  const acceptedNew = {...collection, rows: collection.rows.map((row) => ({...row, revision: 1}))};
  assert.notEqual(api.productionProductsRevision(before), api.productionProductsRevision({...after, current_collection: acceptedNew}));
});

test('repair scope can include plan and presentation failures beyond public measurement failures', () => {
  const generated = generation({written_count: 100, verified_count: 89, contract_eligible_count: 81,
    repair_target_count: 19, repair_candidate_verified_count: 19});
  const tree = render('S4', {generation: generated});
  const rails = nodes(tree).filter((node) => node.type === 'progress');
  assert.equal(rails[0].props.value, 81);
  assert.equal(rails[0].props.max, 100);
  assert.equal(rails[1].props.value, 19);
  assert.equal(rails[1].props.max, 19);
  assert.match(text(tree), /公开校验通过 89 \/ 100/);
  assert.match(text(tree), /题目校验通过 81 \/ 100/);
  assert.match(text(tree), /待修题目 19/);
  assert.doesNotMatch(text(tree), /119 \/ 100/);
  const falseComplete = generation({state: 'complete', written_count: 100, verified_count: 100, contract_eligible_count: 81});
  assert.equal(api.stageState('S4', null, null, [], null, [], null, falseComplete), 'needs_evidence');
});
