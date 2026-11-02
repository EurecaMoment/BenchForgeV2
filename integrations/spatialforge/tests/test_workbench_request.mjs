import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

test('workbench submits full production once and requires visible consent for preserved composer content', async () => {
  let registration;
  const source = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
    .replace(/return \{\s+inject:/, 'return {Workbench}; return {inject:');
  const hooks = [];
  let index = 0;
  const React = {
    createElement: (type, props, ...children) => ({type, props: {...props, children}}),
    useState: (initial) => {
      const slot = index++;
      if (!(slot in hooks)) hooks[slot] = typeof initial === 'function' ? initial() : initial;
      return [hooks[slot], (value) => {hooks[slot] = typeof value === 'function' ? value(hooks[slot]) : value;}];
    },
    useRef: (initial) => {
      const slot = index++;
      return hooks[slot] ||= {current: initial};
    },
    useEffect() {},
  };
  vm.runInNewContext(source, {window: {__ModuleLoader__: {load: (value) => {registration = value;}}},
    localStorage: {getItem: () => null, setItem() {}}, URLSearchParams, Date});
  const {Workbench} = registration.factory(() => React);
  assert.equal(typeof Workbench, 'function', 'test seam must expose the actual component');
  const native = {draft: '保留的原草稿', attachmentIds: ['existing-attachment'], phase: 'plain', queue: []};
  let insertions = 0;
  const submissions = [];
  const props = {t: (key) => key, sessionId: 'request-fixture', canSubmit: true,
    useSessions: (read) => read({byId: {'request-fixture': {cwd: '/fixture'}}}),
    useSession: (read) => read({running: false, openState: 'open', pendingSubmissions: []}),
    useConversation: (read) => read({views: new Map([['chat', {legacy: {nodes: [], runningCalls: []}}]])}),
    useInput: (read) => read(native),
    inputActions: {
      captureInsertion: () => ({start: 0, end: 0, draftRev: 1}),
      insertText: (text) => {insertions++; native.draft = text + native.draft; return true;},
      submit: () => {submissions.push({text: native.draft, attachments: [...native.attachmentIds]}); native.draft = ''; native.attachmentIds = [];},
    }};
  const find = (node, predicate) => Array.isArray(node) ? node.map((value) => find(value, predicate)).find(Boolean)
    : node && typeof node === 'object' ? predicate(node) ? node : find(node.props?.children, predicate) : null;
  const render = () => {index = 0; return find(Workbench(props), (node) => node.type?.name === 'DemandForm');};
  let form = render();
  assert.equal(form.props.demand.objective, '');
  assert.equal(form.props.demand.count, '100');
  form.props.change({objective: '制作室内相对位置评测集', capability: '相对位置', count: '6'});
  form = render();
  form.props.send();
  assert.equal(insertions, 0, 'preserved draft must not be changed before consent');
  assert.equal(native.draft, '保留的原草稿');
  assert.equal(submissions.length, 0);
  form = render();
  assert.equal(form.props.error, 'draftConsentRequired');
  const visibleForm = form.type(form.props);
  assert.ok(find(visibleForm, (node) => node.type?.name === 'DraftReview'), 'draft disclosure is mounted beside the request');
  form.props.onInclude(true);
  props.canSubmit = false;
  form = render();
  form.props.send();
  assert.equal(insertions, 0, 'permission preparation blocks insertion and submission');
  props.canSubmit = true;
  form = render();
  const click = form.props.send;
  click(); click();
  assert.equal(insertions, 1);
  assert.equal(submissions.length, 1, 'a double click calls the official submission API once');
  assert.match(submissions[0].text, /完整完成五阶段/);
  assert.match(submissions[0].text, /目标题量：6 条/);
  assert.match(submissions[0].text, /不要只写计划/);
  assert.match(submissions[0].text, /保留的原草稿/);
  assert.deepEqual(submissions[0].attachments, ['existing-attachment']);
  form = render();
  assert.equal(form.props.demand.objective, '');
  assert.equal(form.props.demand.mode, 'append');
});
