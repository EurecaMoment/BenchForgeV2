import assert from 'node:assert/strict';
import {test} from 'node:test';
import {apply} from '../tools.mjs';
import {validateJsonSchemaValue} from '@deepseek-ai/dsh-tools';

test('pipeline tools expose exact template selection and composable recipe schemas',async()=>{
  const tools=new Map();
  const includeTools=['pipeline_catalog','pipeline_plan','pipeline_run','pipeline_status','pipeline_evaluate'];
  await apply({tools:{register:tool=>tools.set(tool.name,tool)},effect(){},get(){}},{includeTools});
  assert.equal(tools.size,5);
  const tool=tools.get('benchforge_pipeline_plan');
  const request={workspace:'/workspace',objective:'距离和面积数据',selections:[{template_ids:['C01-T01','P001-T01'],count:30,reason:'separate measurement'}],steps:[{id:'capture',uses:'pipeline',pipeline_id:'scene.capture',arguments:{scene_program_path:'/workspace/scene.json'}}]};
  assert.deepEqual(validateJsonSchemaValue(tool.parameters,request,''),[]);
  assert.notDeepEqual(validateJsonSchemaValue(tool.parameters,{workspace:'/workspace',selections:[{template_ids:['C01-T01'],count:30}]},''),[]);
  assert.ok(tools.get('benchforge_pipeline_run').parameters.properties.bindings);
  assert.ok(tools.get('benchforge_pipeline_catalog').parameters.properties.capability);
});
