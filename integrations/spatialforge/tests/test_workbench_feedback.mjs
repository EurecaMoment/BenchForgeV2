import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

let registration;
const source = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
  .replace(/return \{\s+inject:/, 'return {conversationFeedback, ExecutionFeedback}; return {inject:');
const React = {
  createElement: (type, props, ...children) => ({type, props: {...props, children}}),
  useRef: (current) => ({current}), useEffect() {},
};
vm.runInNewContext(source, {window: {__ModuleLoader__: {load: (value) => {registration = value;}}}, Date});
const {conversationFeedback, ExecutionFeedback} = registration.factory(() => React);
const state = (patch = {}) => ({running: true, pendingSubmissions: [], ...patch});
const request = (seq, text, kind = 'user') => ({kind, seq, time: seq * 1000,
  source: {kind: 'user'}, content: [{type: 'text', text}]});
const assistant = (seq, text, patch = {}) => ({kind: 'assistant', seq, time: seq * 1000,
  turn: 1, step: 1, blocks: [{kind: 'reasoning', text: 'PRIVATE_REASONING_SENTINEL'}, {kind: 'text', text}], ...patch});
const result = (seq, id, name, text, patch = {}) => ({kind: 'tool-result', seq, callId: id,
  time: seq * 1000, call: {name, argsRaw: '{"scene":"actual"}'},
  isError: false, content: [{type: 'text', text}], subCalls: [], ...patch});
const running = (id, phase, patch = {}) => ({kind: 'tool-call', callId: id, name: 'pipeline_run',
  phase, time: 3000, argsRaw: '{"target_items":6}', subCalls: [], ...patch});
const visibleText = (node) => Array.isArray(node) ? node.map(visibleText).join(' ')
  : node && typeof node === 'object' ? visibleText(node.props?.children) : String(node || '');
const all = (node, predicate) => Array.isArray(node) ? node.flatMap((value) => all(value, predicate))
  : node && typeof node === 'object' ? [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)] : [];
const render = (feedback, sessionStatus = 'running') => ExecutionFeedback({feedback, sessionStatus, t: (key) => key});

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

test('current live text is visible in a conversation log and never exposes model reasoning', () => {
  const chat = {nodes: [request(1, '制作六道题'), assistant(2, '正在读取场景')], runningCalls: [],
    partial: {turn: 1, step: 2, blocks: [{kind: 'reasoning', text: 'PRIVATE_STREAM_REASONING'},
      {kind: 'text', text: '已经选好'}, {kind: 'text', text: '相机视角'}]}};
  const feedback = conversationFeedback(chat, state());
  const view = render(feedback);
  assert.equal(feedback.request, '制作六道题');
  assert.equal(feedback.entries.at(-1).text, '已经选好相机视角');
  assert.equal(feedback.entries.at(-1).live, true);
  assert.match(visibleText(view), /制作六道题.*正在读取场景.*已经选好相机视角/);
  assert.doesNotMatch(visibleText(view), /PRIVATE_/);
  const log = all(view, (node) => node.props?.role === 'log');
  assert.equal(log.length, 1);
  assert.equal(log[0].props['aria-live'], 'polite');
  assert.equal(all(view, (node) => node.props?.['data-feedback-live'] === 'true').length, 1);
  assert.equal(all(view, (node) => node.props?.['data-awaiting-feedback']).length, 0);
});

test('the newest human request bounds feedback and errors even when runtime notices follow it', () => {
  const chat = {runningCalls: [], nodes: [request(1, '旧需求'), assistant(2, '旧轮结论'),
    {kind: 'turn-error', seq: 3, time: 3000, message: '旧轮失败'},
    request(4, '更改相机位置', 'steering'),
    {kind: 'user', seq: 5, source: {kind: 'runtime-context'}, content: [{type: 'text', text: '系统提示'}]},
    assistant(6, '正在按新的要求调整'), {kind: 'turn-error', seq: 7, time: 7000, message: '当前相机错误'}]};
  const feedback = conversationFeedback(chat, state());
  assert.equal(feedback.request, '更改相机位置');
  assert.equal(feedback.entries.length, 2);
  const view = visibleText(render(feedback, 'failed'));
  assert.match(view, /正在按新的要求调整.*当前相机错误/);
  assert.doesNotMatch(view, /旧轮结论|旧轮失败|系统提示/);
});

test('a transcript submission echo immediately replaces old final feedback before its durable user node', () => {
  const feedback = conversationFeedback({nodes: [request(1, '旧需求'), assistant(2, '旧轮已完成')],
    runningCalls: [], partial: {turn: 1, step: 1, blocks: [{kind: 'text', text: '旧流式回复'}]}},
  state({pendingSubmissions: [{placement: 'queued', text: '后续排队'}, {placement: 'transcript', text: '刚提交的新要求'}]}));
  assert.equal(feedback.request, '刚提交的新要求');
  assert.equal(feedback.pending, true);
  assert.equal(feedback.entries.length, 0);
  const view = render(feedback, 'submitting');
  assert.match(visibleText(view), /submissionEcho.*刚提交的新要求.*awaitingFeedback/);
  assert.doesNotMatch(visibleText(view), /旧轮已完成|旧流式回复|后续排队/);
});

test('native tool feedback follows preparing, executing, and actual PTC subcall results', () => {
  const chat = {nodes: [request(1, '开始生产')], runningCalls: [running('parent', 'preparing')]};
  let feedback = conversationFeedback(chat, state());
  assert.equal(feedback.entries[0].state, 'preparing');
  assert.equal(feedback.entries[0].args, '');
  assert.match(visibleText(render(feedback)), /pipeline_run.*toolPreparing/);
  chat.runningCalls = [running('parent', 'start', {subCalls: [running('child', 'start', {name: 'scene_capture', time: 4000})]})];
  feedback = conversationFeedback(chat, state());
  assert.equal(feedback.entries.length, 2);
  assert.ok(feedback.entries.every((row) => row.state === 'running'));
  assert.equal(all(render(feedback), (node) => node.props?.['data-native-tool']).length, 2);
  chat.nodes.push(result(8, 'parent', 'pipeline_run', '场景完成', {subCalls: [result(7, 'child', 'scene_capture', '相机渲染失败',
    {isError: true, error: {reason: 'camera missing'}})]}));
  chat.runningCalls = [];
  feedback = conversationFeedback(chat, state({running: false}));
  assert.equal(feedback.entries.find((row) => row.id === 'parent').state, 'completed');
  assert.equal(feedback.entries.find((row) => row.id === 'child').state, 'failed');
  assert.match(visibleText(render(feedback, 'idle')), /scene_capture.*failed.*相机渲染失败.*camera missing.*pipeline_run.*completed.*场景完成/);
});

test('stream snapshots replace live text and completed calls instead of appending duplicate entries', () => {
  const chat = {nodes: [request(1, '当前需求')], runningCalls: [running('one', 'start')],
    partial: {turn: 1, step: 1, blocks: [{kind: 'text', text: '正在'}]}};
  assert.equal(conversationFeedback(chat, state()).entries.filter((row) => row.live).length, 1);
  chat.partial.blocks[0].text = '正在渲染场景';
  let feedback = conversationFeedback(chat, state());
  assert.equal(feedback.entries.filter((row) => row.live).length, 1);
  assert.equal(feedback.entries.at(-1).text, '正在渲染场景');
  chat.nodes.push(assistant(5, '正在渲染场景'), result(6, 'one', 'pipeline_run', '产物已保存'));
  chat.partial = null;
  chat.runningCalls = [];
  feedback = conversationFeedback(chat, state({running: false}));
  assert.equal(feedback.entries.filter((row) => row.kind === 'assistant').length, 1);
  assert.equal(feedback.entries.filter((row) => row.id === 'one').length, 1);
  assert.equal(feedback.entries.some((row) => row.live), false);
});
