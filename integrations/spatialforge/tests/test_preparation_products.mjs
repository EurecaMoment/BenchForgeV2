import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createWorkbenchHandler} from '../ui/stage_products.js';

async function fixture(t) {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-preparation-products-'));
  const workspace = path.join(temporary, 'workspace');
  await fs.mkdir(workspace);
  const root = await fs.realpath(workspace), records = path.join(root, '.benchforge', 'synthesis-sessions');
  await fs.mkdir(records, {recursive: true});
  t.after(async () => {
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(temporary));
    assert.ok(relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative));
    assert.ok(path.basename(temporary).startsWith('benchforge-preparation-products-'));
    await fs.rm(temporary, {recursive: true, force: true});
  });
  const children = [
    {id: 'session-questions', label: '题目准备', state: 'running'},
    {id: 'session-annotations', label: '标注准备', state: 'inactive'},
  ];
  const plan = async (key, parentId = 'session-parent') => {
    const directory = path.join(root, 'operations', key);
    await fs.mkdir(directory, {recursive: true});
    await fs.writeFile(path.join(directory, 'request.json'), JSON.stringify({context: {session_id: parentId}}));
    const file = path.join(directory, 'plan.json');
    await fs.writeFile(file, JSON.stringify({schema: 'spatialforge.pipeline/v1', objective: '办公室距离评测'}));
    return fs.realpath(file);
  };
  const frozenPlan = await plan('current-plan');
  const task = async (key, childId, label) => {
    const outputDirectory = path.join(root, 'work', key);
    await fs.mkdir(outputDirectory, {recursive: true});
    return {key, childId, label, prompt: 'Prepare only the assigned code.', outputDirectory: await fs.realpath(outputDirectory), state: 'accepted'};
  };
  const saved = new Map();
  const batch = async (batchKey, tasks, overrides = {}) => {
    const parentId = 'session-parent';
    const identity = {parentId, batchKey, workspacePath: root, planPath: frozenPlan,
      tasks: tasks.map(({childId, state, ...assigned}) => assigned)};
    const record = {schema: 'benchforge.synthesis-sessions/v1', parentId, batchKey, workspacePath: root,
      planPath: frozenPlan, identity, createdAt: Date.now(), tasks,
      reasoningSelection: {provider: 'fixture', model: 'fixture', selectedEffort: 'high'}, ...overrides};
    const recordPath = path.join(records, 'batch-' + Buffer.from(batchKey).toString('base64url') + '.json');
    await fs.writeFile(recordPath, JSON.stringify(record));
    saved.set(batchKey, {record, recordPath});
    return {record, recordPath};
  };
  const controller = {read: async ({parentId, batchKey}) => ({parentId, batchKey,
    recordPath: saved.get(batchKey)?.recordPath, state: 'accepted', tasks: saved.get(batchKey)?.record.tasks || []})};
  const handler = createWorkbenchHandler({}, () => [{id: 'workspace', path: root}],
    async parentId => parentId === 'session-parent' ? children : [], () => controller);
  const request = (params = {}) => handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({
    workspace_path: root, session_id: 'session-parent', view: 'progress', ...params})));
  const open = (batchKey, childId, file, extras = {}) => request({view: 'run_product', product: 'preparation',
    batch_key: batchKey, child_id: childId, file, ...extras});
  return {temporary, root, records, children, frozenPlan, task, plan, batch, request, open};
}

test('native worker scripts and summaries are visible and openable before any pipeline acceptance', async t => {
  const f = await fixture(t);
  const questions = await f.task('questions', 'session-questions', '题目准备');
  const annotations = await f.task('annotations', 'session-annotations', '标注准备');
  await fs.writeFile(path.join(questions.outputDirectory, 'gen_items.py'), 'print("<script>draft</script>")\n# 使用公开距离条件生成题面\n');
  await fs.writeFile(path.join(annotations.outputDirectory, 'summary.md'), '# 标注准备摘要\n\n将相机与可见框逐帧对齐；缺少真实采集，尚未验收。\n');
  await fs.writeFile(path.join(annotations.outputDirectory, 'manifest.json'), JSON.stringify({status: 'completed',
    summary: '已准备标注读取脚本，等待真实采集。', checks: {syntax: 'checked', correct_answer: 'PRIVATE_PREPARATION_SENTINEL'},
    answers: ['PRIVATE_PREPARATION_SENTINEL'], missing_inputs: ['真实采集'], unresolved: []}));
  await f.batch('current-preparation', [questions, annotations]);
  await f.request({view: 'synthesis_status', batch_key: 'current-preparation'});
  for (let i = 0; i < 2; i++) {
    const response = await f.request();
    assert.equal(response.status, 200, await response.clone().text());
    const progress = await response.json();
    assert.deepEqual(progress.pipelines, []);
    assert.equal(progress.parallel_tasks[0].state, 'running');
    assert.equal(progress.parallel_tasks[0].artifact_count, 1);
    assert.equal(progress.parallel_tasks[1].state, 'inactive');
    assert.equal(progress.parallel_tasks[1].artifact_count, 2);
    assert.ok(progress.parallel_tasks.every(row => row.preparation.accepted === false));
    assert.ok(progress.parallel_tasks.flatMap(row => row.public_artifacts).every(file => file.kind === 'preparation' && !file.accepted && !('source' in file)));
  }
  const script = await f.open('current-preparation', 'session-questions', 'gen_items.py');
  assert.equal(script.status, 200);
  assert.match(script.headers.get('content-type'), /text\/html/);
  assert.match(script.headers.get('content-security-policy'), /default-src 'none'/);
  const scriptBody = await script.text();
  assert.ok(scriptBody.includes('使用公开距离条件生成题面'));
  assert.ok(scriptBody.includes('尚未完成场景采集、标注或题目验收'));
  assert.ok(scriptBody.includes('&lt;script&gt;draft&lt;/script&gt;'));
  assert.ok(!scriptBody.includes('<script>'));
  const summary = await f.open('current-preparation', 'session-annotations', 'summary.md');
  assert.ok((await summary.text()).includes('将相机与可见框逐帧对齐'));
  const manifest = await f.open('current-preparation', 'session-annotations', 'manifest.json');
  const manifestBody = await manifest.text();
  assert.ok(manifestBody.includes('等待真实采集'));
  assert.ok(!manifestBody.includes('PRIVATE_PREPARATION_SENTINEL'));
});

test('current native receipt wins over historical records and parent plan child identities remain mandatory', async t => {
  const f = await fixture(t);
  const questions = await f.task('questions', 'session-questions', '题目准备');
  await fs.writeFile(path.join(questions.outputDirectory, 'gen_items.py'), '# actual current preparation\n');
  const older = await f.batch('older-preparation', [questions]);
  await f.batch('current-preparation', [questions]);
  await fs.utimes(older.recordPath, new Date('2027-01-01'), new Date('2027-01-01'));
  await f.request({view: 'synthesis_status', batch_key: 'current-preparation'});
  const progress = await (await f.request()).json();
  assert.ok(progress.parallel_tasks[0].public_artifacts[0].url.includes('batch_key=current-preparation'));
  const otherPlan = await f.plan('other-plan', 'session-other');
  const wrongParent = await f.batch('wrong-parent', [questions]);
  wrongParent.record.parentId = wrongParent.record.identity.parentId = 'session-other';
  await fs.writeFile(wrongParent.recordPath, JSON.stringify(wrongParent.record));
  const wrongPlan = await f.batch('wrong-plan', [questions], {planPath: otherPlan});
  wrongPlan.record.identity.planPath = otherPlan;
  await fs.writeFile(wrongPlan.recordPath, JSON.stringify(wrongPlan.record));
  const wrongOutput = await f.batch('wrong-output', [questions]);
  wrongOutput.record.tasks[0].outputDirectory = f.root;
  await fs.writeFile(wrongOutput.recordPath, JSON.stringify(wrongOutput.record));
  for (const key of ['wrong-parent', 'wrong-plan', 'wrong-output']) {
    const response = await f.open(key, 'session-questions', 'gen_items.py');
    assert.equal(response.status, 403, await response.clone().text());
  }
  assert.equal((await f.open('current-preparation', 'session-alien', 'gen_items.py')).status, 403);
  assert.equal((await f.open('current-preparation', 'session-questions', 'gen_items.py', {session_id: 'session-other'})).status, 403);
});

test('realpath escapes and arbitrary dataset reads cannot turn worker output into an unrestricted preview', async t => {
  const f = await fixture(t);
  const questions = await f.task('questions', 'session-questions', '题目准备');
  await fs.writeFile(path.join(questions.outputDirectory, 'gen_items.py'), '# preparation\n');
  await fs.writeFile(path.join(questions.outputDirectory, 'dataset.jsonl'), 'PRIVATE_DATASET_SENTINEL\n');
  await f.batch('bound-output', [questions]);
  assert.equal((await f.open('bound-output', 'session-questions', '../plan.json')).status, 403);
  assert.equal((await f.open('bound-output', 'session-questions', 'dataset.jsonl')).status, 404);
  const outside = path.join(f.temporary, 'outside');
  await fs.mkdir(outside);
  await fs.writeFile(path.join(outside, 'gen_items.py'), 'PRIVATE_OUTSIDE_SENTINEL\n');
  const moved = questions.outputDirectory + '-saved';
  assert.ok(path.relative(f.root, moved) && !path.relative(f.root, moved).startsWith('..'));
  await fs.rename(questions.outputDirectory, moved);
  await fs.symlink(outside, questions.outputDirectory, process.platform === 'win32' ? 'junction' : 'dir');
  const escaped = await f.open('bound-output', 'session-questions', 'gen_items.py');
  assert.equal(escaped.status, 403);
  assert.ok(!(await escaped.text()).includes('PRIVATE_OUTSIDE_SENTINEL'));
});
