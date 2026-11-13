import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {loadClient} from './load_client.mjs';

const client = readFileSync(new URL('../client.js', import.meta.url), 'utf8');
const React = {createElement: (type, props, ...children) => ({type, props: props || {}, children}), Fragment: 'fragment'};
const {api} = loadClient(client, React);
const t = (key) => api.dictionaries.zh[key] || key;
const plan = {assessment: {scenes: {target_scene_count: 3, designs: [
  {id: 'design-office-work', name: '办公室工作区（sf_office_work_area）', artifact: 'scenes/sf_office_work_area.scene_program.json → captures/sf_office_work_area/'},
  {id: 'design-lounge-meeting', name: '起居会客角（sf_lounge_meeting_corner）', artifact: 'scenes/sf_lounge_meeting_corner.scene_program.json → captures/sf_lounge_meeting_corner/'},
  {id: 'design-study-pantry', name: '阅览茶水角（sf_study_pantry_corner）', artifact: 'scenes/sf_study_pantry_corner.scene_program.json → captures/sf_study_pantry_corner/'},
]}}};
function native(run_id, scene_id, name, state, created_at, phase = 'complete', progressStage = phase) {
  return {run_id, state, terminal: state !== 'RUNNING', tasks: [{id: run_id + '.scene0',
    scene_id, name, state, workflow: 'scene', phase, revision: 0, created_at,
    progress: {stage: progressStage}}]};
}
// The six real run identities and admission times from the hot-deployed observer.
const observed = [
  native('sf_9499947c2ca44112', 'sf_lounge_meeting_corner', '起居会客角', 'FAILED_FINAL', 1793961061.7132092, 'review', 'scene_acceptance_failed'),
  native('sf_02452ba29e6d42e9', 'sf_study_pantry_corner', '阅览茶水角', 'SUCCEEDED', 1793960525.4859145),
  native('sf_013bdd4f220440cc', 'sf_lounge_meeting_corner', '起居会客角', 'FAILED_FINAL', 1793960521.00942, 'capture', 'failed'),
  native('sf_e2c04440dc5c4d65', 'sf_lounge_meeting_corner', '起居会客角', 'FAILED_FINAL', 1793959058.4678328, 'review', 'scene_acceptance_failed'),
  native('sf_bffde8281ae7403b', 'sf_study_pantry_corner', '阅览茶水角', 'FAILED_FINAL', 1793959081.4423714, 'capture', 'failed'),
  native('sf_57ce66dc82c24460', 'sf_office_work_area', '办公室工作区', 'SUCCEEDED', 1793959038.6296408),
];
function nodes(value) {
  if (Array.isArray(value)) return value.flatMap(nodes);
  return value && typeof value === 'object' ? [value, ...nodes(value.children)] : [];
}
function text(value) {
  if (Array.isArray(value)) return value.map(text).join(' ');
  return value && typeof value === 'object' ? text(value.children) : value == null ? '' : String(value);
}
function render(runs) {
  return api.StageProgress({stage: {id: 'S2', key: 'collection'}, collectionPlan: plan,
    record: {value: {scenes: {status: 'connected', runs}}, updatedAt: '2026-11-06T13:40:00Z'},
    conversationRunning: true, t});
}

test('six native receipts aggregate to the parent plan: two of three accepted, latest lounge review fails', () => {
  const unrelated = native('unrelated', 'sf_unrelated_scene', '办公室工作区', 'SUCCEEDED', 1793969999);
  const result = api.sceneCollectionProgress(plan, [...observed, unrelated]);
  assert.equal(result.total, 3);
  assert.equal(result.passed, 2);
  assert.equal(result.rows.length, 3);
  assert.equal(result.state, 'failed');
  const lounge = result.rows.find((row) => row.scene_id === 'sf_lounge_meeting_corner');
  assert.equal(lounge.run_id, 'sf_9499947c2ca44112');
  assert.equal(lounge.name, '起居会客角');
  assert.equal(lounge.statusLabel, 'sceneNeedsRepair');
  assert.equal(api.sceneStage({workflow: 'scene', phase: 'review'}), 'S2');
  assert.equal(api.sceneStage({workflow: 'dataset', phase: 'review'}), 'S4');
});

test('numeric string admission times select new repair, capture and queue receipts over an older success', () => {
  const old = native('old-pass', 'sf_lounge_meeting_corner', '起居会客角', 'SUCCEEDED', '1793960000.01');
  for (const [stage, queue, label] of [['scene_repair', null, 'sceneRepairing'],
    ['capturing', null, 'sceneCapturing'], ['queued', {reason: 'native worker'}, 'sceneQueued']]) {
    const retry = native('new-retry', 'sf_lounge_meeting_corner', '起居会客角', 'RUNNING', '1793962000.02', 'capture', stage);
    retry.tasks[0].queue = queue;
    const result = api.sceneCollectionProgress(plan, [old, observed[1], observed[5], retry]);
    assert.equal(result.passed, 2);
    assert.equal(result.rows.find((row) => row.scene_id === 'sf_lounge_meeting_corner').statusLabel, label);
    assert.notEqual(api.stageState('S2', {steps: [{stage: 'S2', state: 'completed'}]}, null, [], null, [], result), 'completed');
  }
});

test('one accepted scene keeps the three-scene denominator and never completes the full S2 stage', () => {
  const result = api.sceneCollectionProgress(plan, [observed[5]]);
  assert.equal(result.total, 3);
  assert.equal(result.passed, 1);
  assert.equal(result.state, 'waiting');
  const tree = render([observed[5]]);
  const rail = nodes(tree).find((node) => node.type === 'progress');
  assert.equal(rail.props.max, 3);
  assert.equal(rail.props.value, 1);
  assert.match(text(tree), /33%/);
  assert.notEqual(api.sceneCollectionProgress(null, [observed[5]]).state, 'completed');
});

test('current native task states render compact 2/3 progress and select blocked S2 instead of an unrecorded stage', () => {
  const tree = render(observed);
  const rail = nodes(tree).find((node) => node.type === 'progress');
  assert.equal(rail.props.max, 3);
  assert.equal(rail.props.value, 2);
  assert.match(text(tree), /67%/);
  assert.match(text(tree), /已通过 2 \/ 3/);
  assert.doesNotMatch(text(tree), /未记录/);
  assert.equal(nodes(tree).filter((node) => node.props['data-scene-id']).length, 3);
  assert.equal(api.executionStage({id: 'S1'}, {S1: 'completed', S2: 'failed', S4: 'running'}, true).id, 'S2');
});

test('only a newer accepted lounge receipt completes all three planned scenes', () => {
  const accepted = native('new-lounge-pass', 'sf_lounge_meeting_corner', '起居会客角', 'SUCCEEDED', 1793963000);
  const result = api.sceneCollectionProgress(plan, [...observed, accepted]);
  assert.equal(result.passed, 3);
  assert.equal(result.state, 'completed');
  const rejectedAcceptance = {...accepted, tasks: [{...accepted.tasks[0], acceptance_passed: false}]};
  assert.notEqual(api.sceneCollectionProgress(plan, [...observed, rejectedAcceptance]).state, 'completed');
});
