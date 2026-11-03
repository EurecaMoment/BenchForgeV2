import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createWorkbenchHandler} from '../ui/index.js';

const source = (await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8'))
  .replace(/return \{\s+inject:/, 'return {PlanProduct, planMarkdown}; return {inject:');
let registration;
vm.runInNewContext(source, {window: {__ModuleLoader__: {load: (value) => registration = value}}, encodeURIComponent});
let hooks=[],hookIndex=0;
const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
  useState(initial){const index=hookIndex++;if(!(index in hooks))hooks[index]=initial;
    return [hooks[index],value=>hooks[index]=typeof value==='function' ? value(hooks[index]) : value];},
  useRef(initial){return hooks[hookIndex++] ||= {current:initial};}};
const {PlanProduct, planMarkdown} = registration.factory(() => React);
const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
  : node && typeof node === 'object' ? predicate(node) ? node : find(node.props?.children, predicate) : null;
const text = (node) => Array.isArray(node) ? node.map(text).join(' ') : node && typeof node === 'object'
  ? text(node.props?.children) : String(node ?? '');

test('saved assessment reaches the authenticated plan API while private payload fields are excluded', async () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'assessment-plan-api-'));
  try {
    const script = ['import json,sys', 'sys.path.insert(0,"tests")', 'from test_assessment_plan import assessment_fixture',
      'from benchforge_core.runtime import Runtime', 'r=Runtime(sys.argv[1])',
      'p=r.call("pipeline_plan",{"objective":"Distance assessment", "selections":[{"template_ids":["C01-T01","C01-T02"],"count":5,"reason":"Distance protocols"}], "inputs":{"seed":1030,"target_items":5}, "assessment":assessment_fixture()})',
      'r.close()', 'print(json.dumps(p))'].join('\n');
    const result = JSON.parse(execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-c', script, directory],
      {cwd: root, env: {...process.env, PYTHONPATH: path.join(root, 'src'), BENCHFORGE_DSH_SESSION_ID: 'session-assessment-api'}, encoding: 'utf8'}));
    const saved = JSON.parse(await fs.readFile(result.plan, 'utf8'));
    saved.assessment.questions.authority = {answer: 'private fixture answer'};
    saved.assessment.questions.api_key = 'private fixture credential';
    await fs.writeFile(result.plan, JSON.stringify(saved));
    const handler = createWorkbenchHandler({}, () => [{id: 'assessment-workspace', path: directory}]);
    const read = async (view, session = 'session-assessment-api') => {
      const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' +
        new URLSearchParams({view, workspace_path: directory, session_id: session})));
      assert.equal(response.status, 200);
      return response.json();
    };
    assert.equal((await read('plan_template')).sections.length, 11);
    const summary = await read('summary');
    assert.equal(summary.plan_source.plan_path, result.plan);
    assert.equal(summary.plan.assessment.dataset.target_items, 5);
    assert.equal(summary.plan.assessment.annotations.authority_source, saved.assessment.annotations.authority_source);
    assert.equal(summary.plan.assessment.questions.authority, undefined);
    assert.equal(summary.plan.assessment.questions.api_key, undefined);
    assert.equal((await read('summary', 'session-unrelated')).plan, null);
    const edit={plan_path:result.plan,assessment:summary.plan.assessment,split:'dev'};
    edit.assessment.coverage[0].count=4;edit.assessment.dataset.target_items=6;
    const post=async(body,session='session-assessment-api')=>handler(new Request('http://dsh.test/api/benchforge/workbench?'+
      new URLSearchParams({view:'plan_edit',workspace_path:directory,session_id:session}),{method:'POST',body:JSON.stringify(body)}));
    assert.equal((await post(edit,'session-unrelated')).status,403);
    const accepted=await post(edit);assert.equal(accepted.status,200,await accepted.clone().text());
    const edited=await accepted.json();
    assert.equal((await read('summary')).plan_source.plan_path,edited.plan);
    const raw=JSON.parse(await fs.readFile(edited.plan,'utf8'));
    assert.equal(raw.assessment.questions.authority.answer,'private fixture answer');
    assert.equal(raw.inputs.target_items,6);
    assert.equal(raw.inputs.split,'dev');
    assert.equal((await post(edit)).status,400,'stale edit cannot replace the active revision');
  } finally {await fs.rm(directory, {recursive: true, force: true});}
});

test('plan view displays saved model content, exports it and sends changes only after an action', async () => {
  const template = JSON.parse(await fs.readFile(new URL('../../../src/benchforge_core/pipelines/assessment_template.json', import.meta.url), 'utf8'));
  const document = {...template.assessment, title: '遮挡与相对位置评测设计', summary: '100 题，5 个室内场景；目标值尚未验收。',
    questions: {...template.assessment.questions, answerability: '仅从公开两视图和标定求解', example: '以图像右方向为正，桌子相对柜子在哪侧？'},
    annotations: {...template.assessment.annotations, authority_source: '仿真回执与程序推导'}};
  const plan = {objective: 'Produce an assessment', assessment: document};
  const requests = [];
  hooks=[];hookIndex=0;let edited;
  const props={plan, source: {plan_path: '/fixture/current-plan.json'}, artifacts: [], t: (key) => key,
    request: (request) => requests.push(request),save:async(value)=>{edited=value;return {state:'planned',plan:'/fixture/edited/plan.json'};},
    applyEdit:async(path)=>{requests.push('apply '+path);return true;}};
  const render=()=>{hookIndex=0;return PlanProduct(props);};
  const view = render();
  assert.equal(view.props['data-assessment-document'], 'spatialforge.assessment/v1');
  assert.equal(requests.length, 0, 'viewing the plan must not submit production');
  assert.match(text(view), /公开两视图和标定求解/);
  assert.match(text(view), /桌子相对柜子在哪侧/);
  assert.match(text(view), /仿真回执与程序推导/);
  for (const {key} of template.sections) assert.ok(find(view, (node) => node.props?.['data-plan-section'] === key));
  const download = find(view, (node) => node.props?.download === 'assessment-plan.json');
  assert.deepEqual(JSON.parse(decodeURIComponent(download.props.href.split(',').slice(1).join(','))), plan);
  assert.match(planMarkdown(plan), /质量检查与验收/);
  assert.match(planMarkdown(plan), /桌子相对柜子在哪侧/);
  find(view, (node) => node.props?.['data-plan-revise']).props.onClick();
  assert.equal(requests.length,0,'editing begins on the document without sending a model request');
  let editing=render();
  const field=find(editing,node=>node.props?.['data-plan-field']==='questions.answerability');
  assert.ok(field.props.contentEditable);
  field.props.onInput({currentTarget:{textContent:'用户直接编辑：公开图像必须包含方向标记'}});
  find(editing,node=>node.props?.['data-plan-cancel']).props.onClick();
  assert.equal(edited,undefined);
  find(render(),node=>node.props?.['data-plan-revise']).props.onClick();editing=render();
  find(editing,node=>node.props?.['data-plan-field']==='questions.answerability').props.onInput({currentTarget:{textContent:'用户直接编辑：公开图像必须包含方向标记'}});
  await find(editing,node=>node.props?.['data-plan-save']).props.onClick();
  assert.match(edited.assessment.questions.answerability,/用户直接编辑/);
  assert.match(requests[0],/apply .*edited/);
  hooks=[];hookIndex=0;
  find(PlanProduct({...props,save:undefined}), (node) => node.props?.['data-plan-continue']).props.onClick();
  assert.match(requests[1], /不要重复提交/);
  assert.match(requests[1], /\/fixture\/current-plan.json/);
  hooks=[];hookIndex=0;
  const legacy = PlanProduct({plan: {objective: 'Old execution summary'}, artifacts: [], t: (key) => key, request() {}});
  assert.match(text(legacy), /legacyPlan/);
  assert.equal(find(legacy, (node) => node.props?.['data-plan-continue']), undefined);
});
