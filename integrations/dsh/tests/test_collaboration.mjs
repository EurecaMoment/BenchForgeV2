import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {apply} from '../tools.mjs';

test('learning tools declare supported nested object schemas and expose exclusions',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'benchforge-learning-'));
  const toolsDir=path.join(root,'packages/core/tools/lib');
  await fs.mkdir(toolsDir,{recursive:true});
  await fs.writeFile(path.join(toolsDir,'package.json'),JSON.stringify({type:'module'}));
  await fs.writeFile(path.join(toolsDir,'index.js'),'export function defineTool(value){return value;}');
  const includeTools=['spatial_catalog','spatial_generate','spatial_export','spatial_evaluate','curriculum','spatial_train','spatial_experiment','training_monitor'];
  const registered=new Map();
  try {
    await apply({tools:{register:tool=>registered.set(tool.name,tool)}},{dshRoot:root,includeTools});
    assert.equal(registered.size,includeTools.length);
    function check(schema,label) {
      if(schema.type==='object') assert.equal(typeof schema.additionalProperties,'boolean',label);
      for(const [name,child] of Object.entries(schema.properties || {})) check(child,`${label}.${name}`);
      if(schema.items) check(schema.items,`${label}[]`);
    }
    for(const tool of registered.values()) for(const [name,schema] of Object.entries(tool.parameters)) check(schema,`${tool.name}.${name}`);
    assert.ok(registered.get('benchforge_spatial_generate').parameters.exclude_template_ids);
  } finally {await fs.rm(root,{recursive:true,force:true});}
});

test('collaboration handoffs are append-only and readable by another agent',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'benchforge-collab-'));
  const dsh=path.join(root,'dsh');
  const toolsDir=path.join(dsh,'packages/core/tools/lib');
  await fs.mkdir(toolsDir,{recursive:true});
  await fs.writeFile(path.join(toolsDir,'package.json'),JSON.stringify({type:'module'}));
  await fs.writeFile(path.join(toolsDir,'index.js'),'export function defineTool(value){return value;}');
  const registered=new Map();
  await apply({tools:{register:tool=>registered.set(tool.name,tool)}},{dshRoot:dsh,python:'python',configPath:path.join(root,'config.json')});
  const tool=registered.get('benchforge_collaboration');
  assert.ok(tool);
  const exec={agent:{session:{id:'agent-a'}}};
  const first=await tool.execute({workspace:root,action:'publish',role:'planner',status:'ready',summary:'Reference and task split prepared',artifacts:['plan.json'],next_actions:['build scene']},exec);
  const second=await tool.execute({workspace:root,action:'publish',handoff_id:'h2',role:'visual-review',status:'blocked',summary:'View 2 needs a wider camera',findings:['composition is cropped'],blockers:['capture queue'],parent_handoff_id:first.handoff_id},{agent:{session:{id:'agent-b'}}});
  const reply=await tool.execute({workspace:root,action:'publish',handoff_id:'h2',role:'visual-review',status:'ready',summary:'Wider camera prepared',reply_to:first.handoff_id,related_handoff_ids:[first.handoff_id],decision:'use view 2',confidence:.8},{agent:{session:{id:'agent-b'}}});
  const rows=(await tool.execute({workspace:root,action:'list',history:true,filter:{role:'visual-review'}},exec)).handoffs;
  assert.equal(rows.length,2); assert.equal(rows[0].parent_handoff_id,first.handoff_id); assert.equal(rows[0].status,'blocked');
  assert.equal(rows[1].reply_to,first.handoff_id); assert.equal(rows[1].status,'ready');
  assert.equal((await tool.execute({workspace:root,action:'read',handoff_id:'h2'},exec)).summary,reply.summary);
  assert.equal((await tool.execute({workspace:root,action:'read',handoff_id:'h2'},exec)).reply_to,first.handoff_id);
  assert.equal((await tool.execute({workspace:root,action:'list',filter:{status:'ready'}},exec)).handoffs.length,2);
  assert.deepEqual((await tool.execute({workspace:root,action:'list',filter:{status:'blocked'}},exec)).handoffs,[]);
  assert.deepEqual((await tool.execute({workspace:root,action:'list',filter:{role:'visual-review'}},exec)).handoffs,[reply]);
  const completed=await tool.execute({workspace:root,action:'publish',handoff_id:'h2',role:'delivery',status:'done',summary:'Integrated',artifacts:['scene.usda']},exec);
  assert.deepEqual((await tool.execute({workspace:root,action:'list',filter:{agent:'agent-b'}},exec)).handoffs,[]);
  assert.deepEqual((await tool.execute({workspace:root,action:'list',filter:{role:'visual-review'}},exec)).handoffs,[]);
  assert.deepEqual((await tool.execute({workspace:root,action:'list',filter:{status:'done'}},exec)).handoffs,[completed]);
  assert.equal((await tool.execute({workspace:root,action:'list',history:true,filter:{status:'blocked'}},exec)).handoffs.length,1);
  assert.match((await fs.readFile(path.join(root,'.benchforge/collaboration/handoffs.jsonl'),'utf8')).trim(),/visual-review/);
});
