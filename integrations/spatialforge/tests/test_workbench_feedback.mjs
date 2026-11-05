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
