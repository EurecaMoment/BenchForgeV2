import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createWorkbenchHandler} from '../ui/index.js';

const bundle = await fs.readFile(new URL('../ui/client.js', import.meta.url), 'utf8');
const clientExport = /return \{\s+ProductionEnvironment, Workbench, dictionaries, apply, \.\.\.helpers, \.\.\.components\s+\};/;
assert.match(bundle, clientExport, 'the built client exposes its UI factory result');
const source = bundle.replace(clientExport,
  'return {PlanProduct: components.PlanProduct, planMarkdown: helpers.planMarkdown, planEditInstruction: helpers.planEditInstruction, ProductionEnvironment, Workbench, dictionaries, apply, ...helpers, ...components};');
let registration;
vm.runInNewContext(source, {window: {__ModuleLoader__: {load: (value) => registration = value}}, encodeURIComponent});
let hooks=[],hookIndex=0;
const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}),
  useState(initial){const index=hookIndex++;if(!(index in hooks))hooks[index]=initial;
    return [hooks[index],value=>hooks[index]=typeof value==='function' ? value(hooks[index]) : value];},
  useRef(initial){return hooks[hookIndex++] ||= {current:initial};}};
const {PlanProduct, planMarkdown, planEditInstruction} = registration.factory(() => React);
const find = (node, predicate) => Array.isArray(node) ? node.map((child) => find(child, predicate)).find(Boolean)
  : node && typeof node === 'object' ? predicate(node) ? node : find(node.props?.children, predicate) : null;
const text = (node) => Array.isArray(node) ? node.map(text).join(' ') : node && typeof node === 'object'
  ? text(node.props?.children) : String(node ?? '');

test('saved assessment reaches the authenticated plan API while private payload fields are excluded', async () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'assessment-plan-api-'));
  try {
    const script = `
import json
import sys
from benchforge_core.pipelines.assessment import assessment_template
from benchforge_core.runtime import Runtime

def fill(value):
    if isinstance(value, dict):
        return {key: fill(child) for key, child in value.items()}
    if isinstance(value, list):
        return [fill(child) for child in value]
    return 'Fixture design condition' if value == '' else value

assessment = fill(assessment_template()['assessment'])
assessment['objectives'][0]['id'] = 'distance'
counts = [('C01-T01', 3), ('C01-T02', 2)]
assessment['coverage'] = [
    {'objective_id': 'distance', 'template_id': template, 'count': count,
     'difficulty': 'medium', 'conditions': 'Calibrated public geometry',
     'selection_reason': 'Measure the declared distance protocol'}
    for template, count in counts
]
assessment['scenes'].update(allow_new_scenes=True, target_scene_count=2)
assessment['dataset'].update(target_items=5, seed=1030)
assessment['scoring']['metrics'] = [
    {'template_id': template, 'metric': 'absolute error', 'unit': 'm',
     'tolerance': '0.02 m', 'aggregation': 'per-template mean'}
    for template, _count in counts
]
assessment['delivery']['artifacts'] = [
    {'stage': stage, 'path': stage + '/artifact.json', 'format': 'json',
     'contents': 'Viewable stage artifact'}
    for stage in ('S1', 'S2', 'S3', 'S4', 'S5')
]
arguments = {
    'objective': 'Distance assessment',
    'selections': [{'template_ids': [template for template, _count in counts],
                    'count': 5, 'reason': 'Distance protocols'}],
    'inputs': {'seed': 1030, 'target_items': 5},
    'assessment': assessment,
}
plans = {}
for name, session in (('with_markdown', None), ('plain', 'session-assessment-plain')):
    runtime = Runtime(sys.argv[1])
    try:
        if session is not None:
            runtime.dsh_context = {'session_id': session}
        plans[name] = runtime.call('pipeline_plan', arguments)
    finally:
        runtime.close()
print(json.dumps(plans))
`;
    const plans = JSON.parse(execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-c', script, directory],
      {cwd: root, env: {...process.env, PYTHONPATH: path.join(root, 'src'), BENCHFORGE_DSH_SESSION_ID: 'session-assessment-api'}, encoding: 'utf8'}));
    const result=plans.with_markdown;
    const plain=plans.plain;
    const saved = JSON.parse(await fs.readFile(result.plan, 'utf8'));
    saved.assessment.questions.authority = {answer: 'private fixture answer'};
    saved.assessment.questions.api_key = 'private fixture credential';
    saved.assessment.questions.correct_answer = 'private fixture correct answer';
    saved.assessment.questions.ground_truth = 'private fixture ground truth';
    saved.user_markdown = '# 评测计划\n\n保留完整计划正文。\n\n```assessment-yaml\n' + JSON.stringify(saved.assessment, null, 2) + '\n```\n';
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
    assert.equal(summary.plan.assessment.questions.correct_answer, undefined);
    assert.equal(summary.plan.assessment.questions.ground_truth, undefined);
    assert.match(summary.plan.user_markdown, /保留完整计划正文/);
    assert.doesNotMatch(summary.plan.user_markdown, /private fixture/);
    assert.equal((await read('summary', 'session-unrelated')).plan, null);
    const assessment=structuredClone(summary.plan.assessment);
    assessment.coverage[0].count=4;assessment.dataset.target_items=6;
    const markdown='# 用户修改后的完整计划\n\n追加公开视图说明。\n\n```assessment-yaml\n'+JSON.stringify(assessment,null,2)+'\n```\n';
    const edit={plan_path:result.plan,markdown,base_markdown:summary.plan.user_markdown,split:'dev'};
    const post=async(body,session='session-assessment-api')=>handler(new Request('http://dsh.test/api/benchforge/workbench?'+
      new URLSearchParams({view:'plan_edit',workspace_path:directory,session_id:session}),{method:'POST',body:JSON.stringify(body)}));
    assert.equal((await post(edit,'session-unrelated')).status,403);
    for (const invalid of ['```assessment-yaml\ninvalid: [\n```\n', markdown + markdown])
      assert.equal((await post({...edit,markdown:invalid})).status,400,'invalid Markdown is rejected before creating a revision');
    const accepted=await post(edit);assert.equal(accepted.status,200,await accepted.clone().text());
    const edited=await accepted.json();
    assert.equal((await read('summary')).plan_source.plan_path,edited.plan);
    const raw=JSON.parse(await fs.readFile(edited.plan,'utf8'));
    assert.equal(raw.assessment.questions.authority.answer,'private fixture answer');
    assert.equal(raw.assessment.questions.correct_answer,'private fixture correct answer');
    assert.equal(raw.assessment.questions.ground_truth,'private fixture ground truth');
    assert.equal(raw.user_markdown,markdown);
    assert.equal(await fs.readFile(raw.user_markdown_path,'utf8'),markdown);
    assert.equal(raw.inputs.target_items,6);
    assert.equal(raw.inputs.split,'dev');
    assert.equal((await post(edit)).status,400,'stale edit cannot replace the active revision');
    const plainBaseline='# '+plain.pipeline_id+'\n\n```assessment-yaml\n'+JSON.stringify(JSON.parse(await fs.readFile(plain.plan,'utf8')).assessment,null,2)+'\n```\n';
    const plainEdit={plan_path:plain.plan,markdown:'# Distance assessment\n\n将数据集调整为 6 题。\n',base_markdown:plainBaseline,split:'dev'};
    const plainAccepted=await post(plainEdit,'session-assessment-plain');
    assert.equal(plainAccepted.status,200,await plainAccepted.clone().text());
    const plainRevision=JSON.parse(await fs.readFile((await plainAccepted.json()).plan,'utf8'));
    assert.equal(plainRevision.edit_revision.markdown_normalization,true);
    assert.equal(plainRevision.user_markdown,plainEdit.markdown);
    assert.equal(plainRevision.assessment.dataset.target_items,5,'the production agent resolves prose after save');
  } finally {await fs.rm(directory, {recursive: true, force: true});}
});

test('plan view displays saved model content, exports it and sends changes only after an action', async () => {
  const template = JSON.parse(await fs.readFile(new URL('../../benchforge_core/pipelines/assessment_template.json', import.meta.url), 'utf8'));
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
  assert.equal(view.props['data-assessment-document'], 'benchforge.assessment/v1');
  assert.equal(requests.length, 0, 'viewing the plan must not submit production');
  assert.match(text(view), /公开两视图和标定求解/);
  assert.match(text(view), /桌子相对柜子在哪侧/);
  assert.match(text(view), /仿真回执与程序推导/);
  for (const {key} of template.sections) assert.ok(find(view, (node) => node.props?.['data-plan-section'] === key));
  const download = find(view, (node) => node.props?.download === 'assessment-plan.json');
  assert.deepEqual(JSON.parse(decodeURIComponent(download.props.href.split(',').slice(1).join(','))), plan);
  assert.match(planMarkdown(plan), /质量检查与验收/);
  assert.match(planMarkdown(plan), /桌子相对柜子在哪侧/);
  assert.doesNotMatch(planMarkdown(plan), /```assessment-yaml/,'new documents only contain readable Markdown');
  for (const {title} of template.sections) assert.ok(planMarkdown(plan).includes('## '+title));
  const yamlBlock=JSON.stringify(document,null,2);
  const applyInstruction=planEditInstruction('/fixture/edited/plan.json');
  for (const phrase of ['Markdown 正文','edit_revision.base_plan','markdown_normalization=false','markdown_normalization=true',
    'markdown_resolution','{path, before, after, instruction}','逐字引用正文','assessment、selections、inputs',
    'split 与场景选择保持锁定','request_path=','plan_request_cli.py','重复应用不重开阶段窗口']) assert.ok(applyInstruction.includes(phrase),phrase);
  assert.doesNotMatch(applyInstruction,/_plan_edit\.base_plan/);
  const savedMarkdown='# Saved user plan\n\n## Body\n\nExact authored Markdown';
  assert.equal(planMarkdown({...plan,user_markdown:savedMarkdown}),savedMarkdown);
  hooks=[];hookIndex=0;
  const savedView=PlanProduct({...props,plan:{...plan,user_markdown:savedMarkdown+'\n\n- 用户增加的采集要求\n\n```assessment-yaml\n'+yamlBlock+'\n```\n'}});
  assert.ok(find(savedView,node=>node.props?.['data-plan-markdown-view']));
  assert.equal(text(find(savedView,node=>node.type==='h1')),'Saved user plan');
  assert.match(text(savedView),/Exact authored Markdown/);
  assert.match(text(find(savedView,node=>node.type==='li')),/用户增加的采集要求/);
  assert.ok(find(savedView,node=>node.type==='details' && text(node).includes('可执行计划数据')));
  hooks=[];hookIndex=0;
  find(render(), (node) => node.props?.['data-plan-revise']).props.onClick();
  assert.equal(requests.length,0,'editing begins on the document without sending a model request');
  let editing=render();
  const editor=find(editing,node=>node.props?.['data-plan-markdown-editor']);
  assert.equal(editor.type,'textarea');
  assert.doesNotMatch(editor.props.value,/```assessment-yaml/);
  assert.equal(find(editing,node=>node.props?.['data-plan-execution-config']),undefined);
  editor.props.onChange({target:{value:'用户直接编辑：公开图像必须包含方向标记\n\n'+editor.props.value}});
  find(editing,node=>node.props?.['data-plan-cancel']).props.onClick();
  assert.equal(edited,undefined);
  find(render(),node=>node.props?.['data-plan-revise']).props.onClick();editing=render();
  const fullDocument=find(editing,node=>node.props?.['data-plan-markdown-editor']);
  const revised=fullDocument.props.value.replace('100 题','50 题').replace('仅从公开两视图和标定求解',
    '公开图像必须包含方向标记')+'\n## 用户补充\n\n只生成白天有自然光的场景。\n';
  fullDocument.props.onChange({target:{value:revised}});
  await find(editing,node=>node.props?.['data-plan-save']).props.onClick();
  assert.match(edited.markdown,/公开图像必须包含方向标记/);
  assert.equal(edited.markdown,revised,'the complete authored Markdown is sent unchanged');
  assert.match(edited.markdown,/50 题/);
  assert.equal(edited.plan_path,'/fixture/current-plan.json');
  assert.equal(edited.split,'train');
  assert.equal(edited.base_markdown,planMarkdown(plan),'the edit baseline is captured before the user changes the document');
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

test('question page keeps a thumbnail grid when opening and closing details, including saved table routes', async () => {
  let registration,layout='table';
  let script=await fs.readFile(new URL('../ui/client.js',import.meta.url),'utf8');
  const start=script.indexOf('    function useRecord('),end=script.indexOf('    function usePanelVisible(',start);
  script=script.slice(0,start)+'    function useRecord(params) {return {value:params ? window.records[params.view] || null : null,loading:false};}\n'+script.slice(end);
  script=script.replace(/return \{\s+inject:/,'return {Workbench}; return {inject:');
  const records={summary:{runs:[],datasets:[{id:'dataset-existing',report:{accepted:1}}],
    plan:{selections:[{template_ids:['C24-T01'],count:1,reason:'Direction'}],template_contracts:[{id:'C24-T01',title:'固定方向判断'}]}},
    progress:{pipelines:[],scenes:{runs:[]}},dataset:{items:[{row_index:0,item_id:'private-looking-id',template_id:'C24-T01',split:'test',question:'图中椅子相对桌子在哪侧？',
      question_presentation:{stem:'看图1，椅子在桌子的哪一侧？',context:['图中名称对应真实物体。'],conditions:['以画面为参照，按中心标记判断。'],options:['左侧','右侧'],response:'提交一个方向标签。',media_labels:[]},media:[]}],
      facets:{templates:['C24-T01'],splits:['test']},total:1,all:1,pages:1}};
  const state=[];let index=0;
  const react={createElement:React.createElement,useEffect(){},useState(initial){const slot=index++;
    if(!(slot in state))state[slot]=typeof initial==='function' ? initial() : initial;
    return [state[slot],value=>state[slot]=typeof value==='function' ? value(state[slot]) : value];},
    useRef(value){return state[index++] ||= {current:value};}};
  vm.runInNewContext(script,{window:{records,__ModuleLoader__:{load:value=>registration=value}},
    localStorage:{getItem:key=>key.startsWith('bfw:benchforge:') ? JSON.stringify({version:3,stage:'S4',dataset:'dataset-existing',layout}) : null},
    URLSearchParams,encodeURIComponent,Date});
  const {Workbench}=registration.factory(()=>react);
  const props={t:key=>key,sessionId:'existing',canSubmit:true,renderFactorySlot(){},inputActions:{},
    useSessions:read=>read({byId:{existing:{cwd:'/fixture'}}}),
    useSession:read=>read({running:false,openState:'open',pendingSubmissions:[]}),
    useInput:read=>read({draft:'',attachmentIds:[],queue:[],phase:'plain'})};
  for(layout of ['table','grid']){
    state.length=0;
    const render=()=>{index=0;return Workbench(props);};
    const view=render();
    const browser=find(view,node=>node.props?.['data-dataset-browser']);
    assert.ok(find(browser,node=>node.props?.['data-question-grid']));
    assert.equal(find(browser,node=>node.type==='table'),undefined);
    assert.match(text(browser),/固定方向判断/);
    assert.match(text(browser),/看图1，椅子在桌子的哪一侧/);
    assert.doesNotMatch(text(browser),/按中心标记判断/,'the grid shows the short stem');
    find(browser,node=>node.props?.['data-sample-row']==='0').props.onClick();
    const opened=render();
    assert.ok(find(opened,node=>node.props?.['data-question-grid']),'opening details must retain the grid');
    const dialog=find(opened,node=>typeof node.type==='function' && node.type.name==='QuestionDialog');
    assert.ok(dialog,'a question opens in a dialog');
    const detail=dialog.type(dialog.props);
    assert.match(text(detail),/以画面为参照，按中心标记判断/);
    assert.ok(find(detail,node=>node.props?.['data-question-section']==='conditions'),'required conditions stay visible');
    dialog.props.close();
    const closed=render();
    assert.ok(find(closed,node=>node.props?.['data-question-grid']));
    assert.equal(find(closed,node=>typeof node.type==='function' && node.type.name==='QuestionDialog'),undefined);
  }
});
