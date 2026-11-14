import assert from 'node:assert/strict';
import {test} from 'node:test';
import {apply} from '../../tools/core.mjs';
import {validateJsonSchemaValue} from '@deepseek-ai/dsh-tools';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

test('pipeline tools expose exact template selection and composable recipe schemas',async()=>{
  const tools=new Map();
  const includeTools=['pipeline_catalog','pipeline_plan','pipeline_run','pipeline_status','pipeline_artifacts','pipeline_repair_plan','pipeline_evaluate'];
  await apply({tools:{register:tool=>tools.set(tool.name,tool)},effect(){},get(){}},{includeTools});
  assert.equal(tools.size,7);
  const tool=tools.get('benchforge_pipeline_plan');
  assert.deepEqual(validateJsonSchemaValue(tool.parameters,{workspace:'/workspace',request_path:'plan/request.json',validate_only:true},''),[]);
  assert.deepEqual(validateJsonSchemaValue(tool.parameters,{workspace:'/workspace',assessment_path:'plan/assessment.json'},''),[]);
  const request={workspace:'/workspace',objective:'距离和面积数据',selections:[{template_ids:['C01-T01','P001-T01'],count:30,reason:'separate measurement'}],steps:[{id:'capture',uses:'pipeline',pipeline_id:'scene.capture',arguments:{scene_program_path:'/workspace/scene.json'}}]};
  assert.deepEqual(validateJsonSchemaValue(tool.parameters,request,''),[]);
  const numericResolution={...request,user_markdown:'# Plan\n\n改为7题。',markdown_resolution:[
    {path:'dataset.target_items',before:5,after:7,instruction:'改为7题。'}]};
  assert.deepEqual(validateJsonSchemaValue(tool.parameters,numericResolution,''),[]);
  assert.ok(tool.parameters.properties.markdown_resolution.items.properties.before.oneOf.some(({type})=>type==='number'));
  assert.notDeepEqual(validateJsonSchemaValue(tool.parameters,{workspace:'/workspace',selections:[{template_ids:['C01-T01'],count:30}]},''),[]);
  assert.ok(tools.get('benchforge_pipeline_run').parameters.properties.bindings);
  assert.ok(tools.get('benchforge_pipeline_catalog').parameters.properties.capability);
  assert.ok(tools.get('benchforge_pipeline_artifacts').parameters.properties.status);
  assert.ok(tools.get('benchforge_pipeline_repair_plan').parameters.properties.failure_code);
});

test('pipeline invocation forwards the actual DSH execution session without model-controlled arguments', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-session-'));
  let spawned;
  const tools = new Map();
  const subprocess = {resolveExecutable: async () => 'python', spawn: (options) => {
    spawned = options;
    return {done: Promise.resolve({exitCode: 0}), terminate() {}, waitForExit: async () => {},
      collected: {stdout: {readFrom: () => ({text: JSON.stringify({operation_id: 'op', artifact_dir: workspace}), lossy: false})},
        stderr: {readFrom: () => ({text: ''})}}};
  }};
  try {
    await apply({subprocess, tools: {register: (tool) => tools.set(tool.name, tool)}, effect() {}, get() {}}, {includeTools: ['pipeline_plan']});
    await tools.get('benchforge_pipeline_plan').execute({workspace, objective: 'Current work'},
      {agent: {session: {id: 'session-current'}}, callId: 'call-current', signal: new AbortController().signal});
    assert.equal(spawned.env.BENCHFORGE_DSH_SESSION_ID, 'session-current');
    assert.equal(spawned.env.BENCHFORGE_DSH_CALL_ID, 'call-current');
  } finally {await fs.rm(workspace, {recursive: true, force: true});}
});
