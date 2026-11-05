import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

let registration;
const source = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
  .replace(/return \{\s+inject:/, 'return {ExecutionFeedback}; return {inject:');
const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}})};
vm.runInNewContext(source, {window: {__ModuleLoader__: {load: (value) => {registration = value;}}}});
const {ExecutionFeedback} = registration.factory(() => React);

test('stage progress measures declared work but never treats recent tool history as a workload total', async () => {
  let loaded;
  const code = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
    .replace(/return \{\s+inject:/, 'return {StageProgress}; return {inject:');
  vm.runInNewContext(code, {window: {__ModuleLoader__: {load: (value) => loaded = value}}, Date});
  const {StageProgress} = loaded.factory(() => React);
  const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
    : node && typeof node === 'object' ? predicate(node) ? node : find(node.props.children, predicate) : null;
  const render = (props) => StageProgress({stage: {id: 'S2', key: 'collection'}, record: {value: {}}, t: (key) => key, ...props});
  const measured = render({pipeline: {steps: ['completed', 'completed', 'failed', 'waiting'].map((state, id) => ({id, stage: 'S2', state}))}});
  const meter = find(measured, (node) => node.type === 'progress');
  assert.equal(meter.props.value, 2);
  assert.equal(meter.props.max, 4);
  assert.equal(measured.props['data-progress-state'], 'failed');
  assert.equal(find(measured, (node) => node.props.className === 'bfw-progress-metric').props.children[0], '50%');
  const history = render({record: {value: {operations: [{stage: 'S2', state: 'completed'}, {stage: 'S2', state: 'running'}]}}});
  assert.equal(find(history, (node) => node.type === 'progress'), undefined);
  const unknown = find(history, (node) => node.props.role === 'progressbar');
  assert.equal(unknown.props['aria-valuenow'], undefined);
  assert.equal(unknown.props['aria-valuetext'], 'progressPending');
  const savedPlan = render({stage: {id: 'S1', key: 'blueprint'}, planReceipt: {state: 'completed'},
    record: {value: {operations: [{stage: 'S1', state: 'completed'}]}}});
  assert.equal(find(savedPlan, (node) => node.type === 'progress').props.value, 1);
  assert.equal(find(savedPlan, (node) => node.type === 'progress').props.max, 1);
});

test('a confirmed session permission survives a missing projection but an explicit permission change takes effect', async () => {
  let loaded, index = 0;
  const hooks = [];
  const React = {createElement: (type, props) => ({type, props}), useEffect() {},
    useRef: (initial) => hooks[index++] ||= {current: initial},
    useState: (initial) => {const slot = index++; if (!(slot in hooks)) hooks[slot] = initial; return [hooks[slot], () => {}];}};
  const code = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
    .replace(/return \{\s+inject:/, 'return {ProductionEnvironment}; return {inject:');
  vm.runInNewContext(code, {window: {__ModuleLoader__: {load: (value) => loaded = value}}});
  const {ProductionEnvironment} = loaded.factory(() => React);
  let permission = {currentValue: 'danger-full-access'};
  const props = {sessionId: 'permission-fixture', useProjection: () => permission, useSession: (read) => read({openState: 'open'})};
  const renderPermission = () => {index = 0; return ProductionEnvironment(props).props.canSubmit;};
  assert.equal(renderPermission(), true);
  permission = undefined;
  assert.equal(renderPermission(), true, 'a temporary missing projection must not disable an already authorized session');
  permission = {currentValue: 'workspace-write'};
  assert.equal(renderPermission(), false, 'an explicit change must not be hidden by retained permissions');
});

test('running task counters update the meter before the task completes and browsing another stage does not redirect live progress', async () => {
  let loaded;
  const code = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
    .replace(/return \{\s+inject:/, 'return {StageProgress, executionStage}; return {inject:');
  vm.runInNewContext(code, {window: {__ModuleLoader__: {load: (value) => loaded = value}}, Date});
  const {StageProgress, executionStage} = loaded.factory(() => React);
  const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
    : node && typeof node === 'object' ? predicate(node) ? node : find(node.props.children, predicate) : null;
  const viewed = {id: 'S1', key: 'blueprint'};
  const live = executionStage(viewed, {S1: 'completed', S2: 'running'}, true);
  assert.equal(live.id, 'S2');
  const props = {stage: live, conversationRunning: true, record: {value: {}, updatedAt: '2026-11-03T06:00:00Z'}, t: (key) => key};
  for (const bytes of [25, 75]) {
    const element = StageProgress({...props, scene: {state: 'RUNNING', tasks: [{id: 'capture', phase: 'capture',
      state: 'RUNNING', progress: {stage: 'upload', bytes_received: bytes, total_bytes: 100}}]}});
    const bar = find(element, (node) => node.type === 'progress');
    assert.equal(bar.props.value, bytes);
    assert.equal(bar.props.max, 100);
    assert.equal(find(element, (node) => node.props.className === 'bfw-progress-metric').props.children[0], bytes + '%');
  }
  const unknown = StageProgress({...props, scene: {state: 'RUNNING', tasks: [{id: 'capture', phase: 'capture', state: 'RUNNING', progress: {stage: 'capture'}}]}});
  assert.equal(find(unknown, (node) => node.type === 'progress'), undefined);
  assert.equal(find(unknown, (node) => node.props.role === 'progressbar').props['aria-valuetext'], 'progressPending');
  assert.equal(executionStage(viewed, {S1: 'completed'}, true).id, 'execution');
  assert.equal(executionStage(viewed, {S1: 'completed', S2: 'running'}, false), viewed);
  assert.equal(executionStage(viewed, {S1: 'completed'}, false, [{state: 'running', stage: null}]).id, 'execution');
  assert.equal(executionStage(viewed, {S1: 'completed'}, false, [{state: 'running', stage: 'S2'}]).id, 'S2');
  assert.equal(executionStage(viewed, {S1: 'completed'}, false, [{state: 'inactive', stage: null}]), viewed);
});

async function clientExports(names, globals = {}) {
  let loaded;
  const code = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
    .replace(/return \{\s+inject:/, 'return {' + names.join(', ') + '}; return {inject:');
  vm.runInNewContext(code, {window: {__ModuleLoader__: {load: (value) => loaded = value}}, Date, URLSearchParams, ...globals});
  return loaded.factory(() => globals.React || React);
}

const findAll = (node, predicate) => Array.isArray(node) ? node.flatMap((child) => findAll(child, predicate)) :
  node && typeof node === 'object' ? [...(predicate(node) ? [node] : []), ...findAll(node.props?.children, predicate)] : [];

test('saved product refresh ignores live counters and timestamps but follows actual outputs and terminal states', async () => {
  const {productionProductsRevision} = await clientExports(['productionProductsRevision']);
  const value = {
    operations: [{id: 'old-plan', state: 'completed'}, {id: 'active-tool', state: 'running'}],
    pipelines: [{id: 'parent', state: 'running', updated_at: '2026-11-05T00:00:00Z', steps: [
      {id: 'plan', state: 'completed'}, {id: 'capture', state: 'running'},
    ]}],
    scenes: {runs: [{run_id: 'scene', state: 'RUNNING', tasks: [
      {id: 'scene.capture', state: 'RUNNING', revision: 1, progress: {completed: 1, total: 20}},
    ]}]},
    parallel_tasks: [{id: 'child', state: 'RUNNING', revision: 1, progress: {completed: 1, total: 10},
      public_artifacts: [{url: 'api/benchforge/workbench?view=stage_media&file=preview', revision: 1}]}],
  };
  const before = productionProductsRevision(value);
  const live = structuredClone(value);
  live.operations.push({id: 'next-tool', state: 'running'});
  live.operations.reverse();
  live.pipelines[0].updated_at = '2026-11-05T00:00:03Z';
  live.pipelines[0].steps[1].state = 'waiting';
  live.scenes.runs[0].tasks[0].progress.completed = 15;
  live.parallel_tasks[0].progress.completed = 8;
  live.parallel_tasks[0].updated_at = '2026-11-05T00:00:03Z';
  live.parallel_tasks.push({id: 'new-child', state: 'RUNNING'});
  assert.equal(productionProductsRevision(live), before);
  for (const change of [
    (next) => next.operations[1].state = 'completed',
    (next) => next.pipelines[0].steps[1].state = 'completed',
    (next) => next.scenes.runs[0].tasks[0].revision++,
    (next) => next.scenes.runs[0].state = 'FAILED_FINAL',
    (next) => next.parallel_tasks[0].public_artifacts[0].revision++,
  ]) {
    const next = structuredClone(value);
    change(next);
    assert.notEqual(productionProductsRevision(next), before, 'saved output changes must invalidate product reads');
  }
});

test('progress updates keep an existing product request and its refresh timer instead of issuing another read', async () => {
  let state, effect, cleanup, reads = 0, serial = 0;
  const timers = new Map();
  const hooks = {
    useState(initial) {state ??= initial; return [state, (update) => state = typeof update === 'function' ? update(state) : update];},
    useEffect(callback, dependencies) {
      if (effect && dependencies.every((value, index) => value === effect[index])) return;
      cleanup?.(); effect = dependencies; cleanup = callback();
    },
  };
  const {useRecord, productionProductsRevision} = await clientExports(['useRecord', 'productionProductsRevision'], {
    React: hooks, AbortController,
    document: {visibilityState: 'visible', addEventListener() {}, removeEventListener() {}},
    setTimeout: (callback, delay) => {const id = ++serial; timers.set(id, {callback, delay}); return id;},
    clearTimeout: (id) => timers.delete(id),
    fetch: async () => {reads++; return {ok: true, json: async () => ({runs: [{id: 'saved-plan'}]})};},
  });
  const value = {pipelines: [{id: 'parent', state: 'running', updated_at: 'first', steps: [{id: 'capture', state: 'running'}]}]};
  const render = () => useRecord({view: 'summary', session_id: 'session-parent'}, productionProductsRevision(value), 30000, true);
  render();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  assert.equal(reads, 1);
  const pendingTimer = [...timers.keys()][0];
  value.pipelines[0].updated_at = 'second';
  value.pipelines[0].steps[0].progress = {completed: 7, total: 10};
  render();
  assert.equal(reads, 1);
  assert.ok(timers.has(pendingTimer), 'the scheduled product refresh should survive each live progress poll');
  value.pipelines[0].steps[0].state = 'completed';
  render();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  assert.equal(reads, 2, 'a newly saved completed step should refresh products immediately');
  cleanup?.();
});

test('parallel tasks show readable names, independent measured work and public artifact links without inventing percentages', async () => {
  const {ParallelProgress} = await clientExports(['ParallelProgress']);
  const panel = ParallelProgress({stage: {id: 'S2'}, t: (key) => key, tasks: [
    {id: 'office', stage: 'S2', display_name: '办公场景', state: 'RUNNING', progress: {completed: 3, total: 10}, artifact_count: 1,
      public_artifacts: [{title: '场景视频', url: 'api/benchforge/workbench?view=stage_media&scene=office'},
        {title: 'Unsafe', url: 'javascript:alert(1)'}, {title: 'External', url: 'https://example.test/private'}]},
    {id: 'opaque-id', stage: 'S2', state: 'RUNNING', progress: {stage: 'synthesis'}},
    {id: 'distance', stage: 'S2', display_name: '距离题组', state: 'SUCCEEDED', completed: 2, total: 2,
      public_artifacts: [{title: '公开配置', url: 'api/benchforge/workbench?view=run_product&product=config'}]},
    {id: 'other-stage', stage: 'S4', display_name: '其他阶段', state: 'RUNNING'},
  ]});
  const tasks = findAll(panel, (node) => node.props?.['data-parallel-task']);
  assert.deepEqual(tasks.map((node) => node.props['data-parallel-task']), ['office', 'opaque-id', 'distance']);
  const officeMeter = findAll(tasks[0], (node) => node.type === 'progress')[0];
  assert.equal(officeMeter.props.value, 3);
  assert.equal(officeMeter.props.max, 10);
  assert.equal(findAll(tasks[1], (node) => node.type === 'progress').length, 0);
  const fallbackName = findAll(tasks[1], (node) => node.type === 'strong')[0].props.children[0];
  assert.equal(fallbackName, 'parallelTask 2');
  assert.deepEqual(findAll(panel, (node) => node.type === 'a').map((node) => node.props.href), [
    'api/benchforge/workbench?view=stage_media&scene=office', 'api/benchforge/workbench?view=run_product&product=config',
  ]);
  assert.equal(findAll(panel, (node) => node.type === 'details')[0].props.open, false);
  assert.equal(findAll(panel, (node) => node.props?.className === 'bfw-parallel-heading')[0].props.children[1].props.children[0],
    'parallelCompleted 1 / 3');
});

test('finished child tasks do not complete the parent stage before its own recorded acceptance', async () => {
  const {StageProgress, ParallelProgress} = await clientExports(['StageProgress', 'ParallelProgress']);
  const element = StageProgress({stage: {id: 'S2', key: 'collection'}, pipeline: {steps: [{id: 'accept', stage: 'S2', state: 'waiting'}]},
    record: {value: {parallel_tasks: [{id: 'child', stage: 'S2', display_name: '办公场景', state: 'completed'}]}}, t: (key) => key});
  assert.equal(element.props['data-progress-state'], 'waiting');
  const panel = findAll(element, (node) => node.type === ParallelProgress)[0];
  assert.equal(panel.props.tasks[0].id, 'child');
});

test('native child inactivity is readable and does not count as finished synthesis', async () => {
  const {ParallelProgress, StageProgress, dictionaries} = await clientExports(['ParallelProgress', 'StageProgress', 'dictionaries']);
  const panel = ParallelProgress({stage: {id: 'execution'}, t: (key) => dictionaries.zh[key] || key, tasks: [
    {id: 'child-idle', display_name: '场景草案', stage: null, state: 'inactive', artifact_count: 1,
      public_artifacts: [{title: '评测计划', url: 'api/benchforge/workbench?view=run_product&product=plan'}]},
    {id: 'child-unavailable', display_name: '题目合成', stage: null, state: 'unavailable'},
  ]});
  assert.deepEqual(findAll(panel, (node) => node.props?.className?.startsWith('bfw-pill')).map((node) => node.props.children[0]),
    ['等待后续任务', '状态暂不可用']);
  assert.equal(findAll(panel, (node) => node.type === 'details').length, 0);
  assert.equal(findAll(panel, (node) => node.props?.className === 'bfw-parallel-heading')[0].props.children[1].props.children[0],
    '正在执行 0 / 2');
  assert.equal(findAll(panel, (node) => node.type === 'a').length, 1);
  const active = StageProgress({stage: {id: 'S2', key: 'collection'}, t: (key) => key,
    pipeline: {steps: [{id: 'earlier-capture', stage: 'S2', state: 'completed'}]},
    record: {value: {parallel_tasks: [{id: 'live-child', stage: 'S2', state: 'running'}]}}});
  assert.equal(active.props['data-progress-state'], 'running');
  assert.equal(findAll(active, (node) => node.type === 'progress').length, 0,
    'previously completed output must not become a 100% meter for a new active child');
});

test('live stage progress includes all active owned scene tasks and excludes replaced historical failures', async () => {
  const {StageProgress, ParallelProgress} = await clientExports(['StageProgress', 'ParallelProgress']);
  const scenes = [
    {run_id: 'current-a', state: 'RUNNING', terminal: false, tasks: [
      {id: 'a', revision: 1, phase: 'capture', state: 'SUCCEEDED', progress: {stage: 'synthesis', completed: 2, total: 2}}]},
    {run_id: 'current-b', state: 'RUNNING', terminal: false, tasks: [
      {id: 'b', revision: 1, phase: 'capture', state: 'RUNNING', progress: {stage: 'synthesis', completed: 3, total: 10}}]},
    {run_id: 'old-failed', state: 'FAILED_FINAL', terminal: true, tasks: [
      {id: 'old', phase: 'capture', state: 'FAILED_FINAL', failure: 'Historical failure'}]},
  ];
  const element = StageProgress({stage: {id: 'S2', key: 'collection'}, scene: scenes[2],
    record: {value: {scenes: {status: 'connected', runs: scenes}}}, t: (key) => key});
  assert.equal(element.props['data-progress-state'], 'running');
  const meter = findAll(element, (node) => node.type === 'progress')[0];
  assert.equal(meter.props.value, 5);
  assert.equal(meter.props.max, 12);
  const scenePanel = findAll(element, (node) => node.type === ParallelProgress && node.props.titleKey === 'progressTasks')[0];
  assert.deepEqual(scenePanel.props.tasks.map((row) => row.id), ['a', 'b']);
  const caption = findAll(ParallelProgress(scenePanel.props), (node) => node.props?.className === 'bfw-parallel-heading')[0];
  assert.equal(caption.props.children[1].props.children[0], 'parallelCompleted 1 / 2');
});

test('independent scene counters with different units remain separate instead of using the first task as the whole stage', async () => {
  const {StageProgress, ParallelProgress} = await clientExports(['StageProgress', 'ParallelProgress']);
  const scene = {state: 'RUNNING', tasks: [
    {id: 'upload', phase: 'capture', state: 'RUNNING', progress: {stage: 'upload', bytes_received: 50, total_bytes: 100}},
    {id: 'items', phase: 'capture', state: 'RUNNING', progress: {stage: 'capture', completed: 3, total: 10}},
  ]};
  const element = StageProgress({stage: {id: 'S2', key: 'collection'}, scene, record: {value: {}}, t: (key) => key});
  assert.equal(findAll(element, (node) => node.type === 'progress').length, 0);
  assert.equal(findAll(element, (node) => node.props?.role === 'progressbar')[0].props['aria-valuetext'], 'progressPending');
  const scenePanel = findAll(element, (node) => node.type === ParallelProgress && node.props.titleKey === 'progressTasks')[0];
  assert.deepEqual(findAll(ParallelProgress(scenePanel.props), (node) => node.type === 'progress').map((node) =>
    [node.props.value, node.props.max]), [[50, 100], [3, 10]]);
});

test('a captured child scene still waits for the parent acceptance step and a queued sibling does not hide active work', async () => {
  const {StageProgress} = await clientExports(['StageProgress']);
  const props = {stage: {id: 'S2', key: 'collection'}, record: {value: {}}, t: (key) => key};
  const captured = StageProgress({...props, scene: {state: 'SUCCEEDED', tasks: [{id: 'capture', phase: 'capture', state: 'SUCCEEDED'}]},
    pipeline: {steps: [{id: 'accept', stage: 'S2', state: 'waiting'}]}});
  assert.equal(captured.props['data-progress-state'], 'waiting');
  const mixed = StageProgress({...props, scene: {state: 'RUNNING', tasks: [
    {id: 'queued', phase: 'capture', state: 'RUNNING', queue: {reason: 'Waiting for capture worker'}},
    {id: 'active', phase: 'capture', state: 'RUNNING'},
  ]}});
  assert.equal(mixed.props['data-progress-state'], 'running');
});

test('workbench embeds the native conversation through its authorized factory without replacing its content', () => {
  const calls = [];
  const nativeChat = {type: 'NativeChatView', props: {children: [
    {type: 'NativeMarkdown', props: {text: '## Actual reply\n**Scene saved**'}},
    {type: 'NativeProcessDisclosure', props: {expanded: true, tool: 'scene_capture', live: true}},
  ]}};
  const element = ExecutionFeedback({t: (key) => key, renderFactorySlot: (name, owner) => {
    calls.push({name, owner});
    return nativeChat;
  }});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].name, 'conversation.content');
  assert.equal(calls[0].owner.variant, 'embedded');
  assert.equal(calls[0].owner.phase, 'active');
  assert.equal(calls[0].owner.hero, false);
  assert.equal(element.props['data-native-chat-view'], true);
  assert.equal(element.props.children[0], nativeChat, 'Markdown, live tool cards and disclosures remain owned by DSH');
  assert.equal(nativeChat.props.children[1].props.live, true);
});
