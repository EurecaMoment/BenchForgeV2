import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import { validateJsonSchemaValue } from '@deepseek-ai/dsh-tools';
import { apply, Config } from '../plugin/tools.mjs';
import {createObservationBridge, projectObservationSnapshot} from '../plugin/observation_bridge.mjs';

async function fixture(t,{saveImage=async()=>({id:'fixture-image'}),scenePolicy=false,tokenConfig={},launchEnvironment}={}){
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'sf-plugin-contract-'));
  const replies=new Map(),statuses=new Map(),requests=[];
  const server=http.createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({path:req.url,args:JSON.parse(body),authorization:req.headers.authorization});
    res.statusCode=statuses.get(req.url) || 200;
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify(replies.get(req.url)??{}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await fs.rm(root,{recursive:true,force:true});});
  if(scenePolicy){
    await fs.mkdir(path.join(root,'scene-library'));
    await fs.writeFile(path.join(root,'scene-library','policy.json'),JSON.stringify({enabled:true,enforce_realism:true,excluded_tasks:[]}));
  }
  const serviceConfig=path.join(root,'service.json');
  await fs.writeFile(serviceConfig,JSON.stringify({service_url:`http://127.0.0.1:${server.address().port}`,operator_token:'test-token',execution_mode:scenePolicy?'production':'exploration',...(scenePolicy?{scene_policy_path:'scene-library/policy.json'}:{}),artifacts:root,...tokenConfig}));
  const tools=new Map();
  const ctx={
    tools:{register:tool=>tools.set(tool.name,tool)},on(){},
    llm:{resolveModelInfo:async()=>({inputModalities:['image']})},
    attachments:{saveImage},launchEnvironment,
    get(name){return this[name];},
  };
  const policyConfig=scenePolicy ? {scenePolicyWorkspace:root,policyPython:process.env.PYTHON || 'python'} : {};
  await apply(ctx,Config({serviceConfig,dshRoot:'/ignored/legacy/source/path',policyPython:process.env.PYTHON || 'python',...policyConfig}));
  const exec=(signal=new AbortController().signal)=>({signal,callId:'fixture-call',agent:{session:{id:'fixture-session',requestHeader:()=>({config:{provider:'fixture',model:'fixture'}})},options:{}}});
  return {root,tools,replies,statuses,requests,exec};
}

test('legacy observation report error reads one fresh snapshot and retains failed acceptance evidence',async(t)=>{
  const f=await fixture(t);
  const folder=path.join(f.root,'r.scene0','revision_0');
  await fs.mkdir(path.join(folder,'capture'),{recursive:true});
  await fs.writeFile(path.join(folder,'capture','report.json'),JSON.stringify({status:'captured',frames:1,renderable:true,errors:[]}));
  await fs.writeFile(path.join(folder,'capture','view_0.png'),'fixture-pixels');
  await fs.writeFile(path.join(folder,'capture','view_0.json'),'{"frame_id":"view_0","camera":{"position":[-0.0,1,2],"target":[0,0,0]},"objects":[]}');
  f.replies.set('/inspect',{state:'FAILED_FINAL',tasks:[{id:'r.scene0',state:'FAILED_FINAL',
    unit:{phase:'review',revision:0,workflow:'scene',intent:{capture_only:true}},
    failure:{error:'AcceptanceError',detail:'Physical support failed'},result:{directory:folder}}]});
  for(const [name,route,issue] of [
    ['spatialforge_status','/observe','物体悬空'],['spatialforge_wait','/wait','修订后仍存在支撑间隙']]){
    await fs.writeFile(path.join(folder,'scene_review.json'),JSON.stringify({passed:false,
      visual_realism:{status:'needs_improvement'},interaction_requested:false,issues:[issue]}));
    f.statuses.set(route,400);f.replies.set(route,{error:'KeyError',detail:"'report'"});
    const before=f.requests.length;
    const tool=f.tools.get(name),value=await tool.execute({run_id:'r'},f.exec());
    assert.deepEqual(f.requests.slice(before).map(request=>request.path),[route,'/inspect']);
    assert.deepEqual(f.requests.at(-1).args,{run_id:'r'});
    assert.deepEqual(validateJsonSchemaValue(tool.output.schema,value,''),[]);
    assert.equal(value.state,'FAILED_FINAL');assert.equal(value.terminal,true);
    assert.equal(value.tasks[0].quality.scene_quality_passed,false);
    assert.deepEqual(value.tasks[0].quality.feedback.issues,[issue]);
    assert.equal(value.tasks[0].next_action,'inspect_quality_gaps');
    assert.equal(value.tasks[0].failure.detail,'Physical support failed');
    assert.equal(value.tasks[0].result.report.available,true);
    assert.equal(value.tasks[0].result.report.frames,1);
    assert.deepEqual(value.tasks[0].evidence.captured_revisions,[{revision:0,views:1,action_traces:0}]);
    assert.equal(value.cursor,undefined);
    assert.equal(Object.is(value.tasks[0].result.views[0].camera.position[0],-0),false);
    assert.equal(JSON.stringify(value).includes('test-token'),false);
  }
});

test('legacy observation bridge preserves unrelated HTTP errors without snapshot fallback',async(t)=>{
  const f=await fixture(t);
  const cases=[
    ['spatialforge_status','/observe',{run_id:'r'},400,{error:'KeyError',detail:"'other'"}],
    ['spatialforge_status','/observe',{run_id:'r'},500,{error:'KeyError',detail:"'report'"}],
    ['spatialforge_wait','/wait',{run_id:'r'},401,{error:'Unauthorized'}],
    ['spatialforge_wait','/wait',{run_id:'r'},400,{error:'ValueError',detail:"'report'"}],
    ['spatialforge_status','/inspect',{run_id:'r',detail:true},400,{error:'KeyError',detail:"'report'"}],
  ];
  for(const [name,route,args,status,response] of cases){
    f.statuses.set(route,status);f.replies.set(route,response);
    const before=f.requests.length;
    await assert.rejects(f.tools.get(name).execute(args,f.exec()),error=>{
      assert.equal(error.status,status);assert.deepEqual(error.response,response);
      assert.equal(error.message,JSON.stringify(response));return true;
    });
    assert.deepEqual(f.requests.slice(before).map(request=>request.path),[route]);
  }
});

test('legacy observation packaged bridge uses the service module when repository source is absent',async(t)=>{
  const f=await fixture(t);
  const packageFolder=path.join(f.root,'npm','prefix','package','plugin');
  const moduleFolder=path.join(f.root,'service-env','spatialforge');
  await fs.mkdir(packageFolder,{recursive:true});await fs.mkdir(moduleFolder,{recursive:true});
  const bridgeFile=path.join(packageFolder,'observation_bridge.mjs');
  await fs.copyFile(new URL('../plugin/observation_bridge.mjs',import.meta.url),bridgeFile);
  await fs.writeFile(path.join(moduleFolder,'__init__.py'),'');
  await fs.copyFile(new URL('../../../components/spatialforge/src/spatialforge/observation.py',import.meta.url),path.join(moduleFolder,'observation.py'));
  const packaged=await import(pathToFileURL(bridgeFile).href);
  const project=()=>{
    const previousPythonPath=process.env.PYTHONPATH;
    process.env.PYTHONPATH=path.join(f.root,'service-env')+(previousPythonPath?path.delimiter+previousPythonPath:'');
    try{return packaged.projectObservationSnapshot({state:'FAILED_FINAL',tasks:[]},
      {runId:'r',artifacts:f.root,policyPython:process.env.PYTHON || 'python'});}
    finally{if(previousPythonPath===undefined)delete process.env.PYTHONPATH;else process.env.PYTHONPATH=previousPythonPath;}
  };
  const value=await project();
  assert.equal(value.state,'FAILED_FINAL');assert.equal(value.terminal,true);
  assert.equal(value.cursor,undefined);
  await fs.writeFile(path.join(moduleFolder,'__init__.py'),"raise ImportError('fixture service projection unavailable')\n");
  await assert.rejects(project(),/Native observation projection unavailable/);
});

test('legacy observation bridge preserves cancellation across snapshot and native projection',async(t)=>{
  const f=await fixture(t);
  const legacy=Object.assign(new Error('legacy projection'),{status:400,response:{error:'KeyError',detail:"'report'"}});
  for(const boundary of ['/observe','/inspect']){
    const abort=new AbortController(),reason=new Error('canceled at '+boundary),calls=[];
    let projections=0;
    const read=createObservationBridge({artifacts:f.root,api:async(route)=>{
      calls.push(route);if(route===boundary)abort.abort(reason);
      if(route==='/observe')throw legacy;
      return {state:'FAILED_FINAL',tasks:[]};
    },project:async()=>{projections++;return {};}});
    await assert.rejects(read('/observe',{run_id:'r'},abort.signal),error=>error===reason);
    assert.deepEqual(calls,boundary==='/observe'?['/observe']:['/observe','/inspect']);
    assert.equal(projections,0);
  }
  const abort=new AbortController(),reason=new Error('cancel native projection');
  const pending=projectObservationSnapshot({state:'FAILED_FINAL',tasks:[]},
    {runId:'r',artifacts:f.root,policyPython:process.env.PYTHON || 'python',signal:abort.signal});
  abort.abort(reason);
  await assert.rejects(pending,error=>error===reason);
});

test('explicit token environment agrees with service precedence over inline token',async(t)=>{
  const launchEnvironment={getFrom:(name)=>name==='OPERATOR_TOKEN'?{value:'environment-token'}:undefined};
  for(const explicit of [false,true]){
    const f=await fixture(t,{tokenConfig:explicit?{operator_token_env:'OPERATOR_TOKEN'}:{},launchEnvironment});
    f.replies.set('/inspect',{run_id:'r',state:'SUCCEEDED',tasks:[]});
    await f.tools.get('spatialforge_status').execute({run_id:'r',detail:true},f.exec());
    assert.equal(f.requests.at(-1).authorization,'Bearer '+(explicit?'environment-token':'test-token'));
  }
});

test('scene policy rejects cube capture and unchecked generation before any service request',async(t)=>{
  const f=await fixture(t,{scenePolicy:true});
  await fs.writeFile(path.join(f.root,'scene-library/policy.json'),JSON.stringify({enabled:true,enforce_realism:true,excluded_tasks:['sf_removed.scene0']}));
  const scenePlan=path.join(f.root,'scene-plan.json');
  await fs.writeFile(scenePlan,JSON.stringify({assessment:{schema:'spatialforge.assessment/v1',scenes:{designs:[{
    id:'fixture-design',name:'桌边座椅测试场景',
    summary:'一把椅子置于稳定地面上，椅腿有明确支撑，周边留出观察空间。',
    hard_requirements:['椅子保持直立并由地面支撑'],
    physical_assumptions:['静态重力下检查接触和稳定性'],
    object_roles:[{object_id:'chair',role:'供人坐下休息的椅子'},{object_id:'ground',role:'承托椅子的地面'}],
    relations:[{type:'supported_by',source:'chair',target:'ground',description:'椅腿由地面稳定支撑'}],
  }]}}}));
  const program=path.join(f.root,'program.json');
  const sceneProgram={scene_id:'fixture-scene',objects:[{id:'chair',kind:'box'},{id:'ground',kind:'mesh'}],
    provenance:{sources:[{kind:'scene_plan',path:scenePlan,scene_design_id:'fixture-design'}]}};
  await fs.writeFile(program,JSON.stringify(sceneProgram));
  await assert.rejects(f.tools.get('spatialforge_capture').execute({scene_program_path:program},f.exec()),/Scene rejected/);
  await assert.rejects(f.tools.get('spatialforge_run').execute({intents:[{name:'living room',description:'Indoor scene',split:'train'}]},f.exec()),/unchecked default planner/);
  await assert.rejects(f.tools.get('spatialforge_dataset').execute({intent:{source_task_id:'sf_removed.scene0'}},f.exec()),/removed by the user/);
  assert.equal(f.requests.length,0);
  sceneProgram.objects[0].kind='mesh';
  await fs.writeFile(program,JSON.stringify(sceneProgram));
  f.replies.set('/capture',{run_id:'r',task_id:'r.scene0',state:'accepted'});
  assert.deepEqual(await f.tools.get('spatialforge_capture').execute({scene_program_path:program},f.exec()),
    {run_id:'r',task_id:'r.scene0',state:'accepted'});
  assert.deepEqual(f.requests.map(request=>request.path),['/capture']);
});

test('Config rejects missing or mistyped service config and accepts the legacy preset field',async(t)=>{
  assert.throws(()=>Config({}),/serviceConfig/);
  assert.throws(()=>Config({serviceConfig:12}),/serviceConfig/);
  const f=await fixture(t);
  assert.equal(f.tools.size,23);
  assert.ok(f.tools.has('spatialforge_trellis'));
  assert.ok(f.tools.has('spatialforge_sam3d'));
});

test('HTTP routing uses the configured operator token and stable output families',async(t)=>{
  const f=await fixture(t);
  const cases=[
    ['spatialforge_run','/start',{intents:[{name:'fixture',description:'fixture',split:'train'}]},{run_id:'r',state:'accepted',program_handoff:['planner']}],
    ['spatialforge_capture','/capture',{scene_program_path:'/fixture/program.json'},{run_id:'r',task_id:'r.scene0',state:'accepted',operation:'capture_only'}],
    ['spatialforge_layout','/layout',{name:'fixture',description:'fixture'},{run_id:'r',state:'accepted',workflow:'layout',gt_source:false}],
    ['spatialforge_asset','/asset',{intent:{name:'fixture',description:'fixture'}},{run_id:'r',state:'accepted'}],
    ['spatialforge_dataset','/dataset',{intent:{recipe:'fixture'}},{run_id:'r',state:'accepted'}],
    ['spatialforge_status','/observe',{run_id:'r'},{run_id:'r',state:'SUCCEEDED',tasks:[],cursor:'ignored',terminal:true}],
    ['spatialforge_status','/inspect',{run_id:'r',detail:true},{run_id:'r',state:'SUCCEEDED',tasks:[],gallery_url:'/gallery/r'}],
    ['spatialforge_wait','/wait',{run_id:'r'},{run_id:'r',state:'SUCCEEDED',tasks:[],cursor:'ignored',changed:true}],
    ['spatialforge_retry','/retry',{task_id:'r.scene0'},{task_id:'r.scene0',revision:1,phase:'PLAN'}],
    ['spatialforge_cancel','/cancel',{run_id:'r'},{cancel_requested:true}],
  ];
  for(const [name,url,args,response] of cases){
    f.replies.set(url,response);
    const tool=f.tools.get(name),value=await tool.execute(args,f.exec());
    assert.deepEqual(validateJsonSchemaValue(tool.output.schema,value,''),[],name);
    assert.equal(f.requests.at(-1).authorization,'Bearer test-token');
    assert.equal(tool.output.schema.additionalProperties,true);
    if(response.cursor)assert.equal(value.cursor,undefined);
  }
  assert.notDeepEqual(validateJsonSchemaValue(f.tools.get('spatialforge_capture').output.schema,{run_id:'r',state:'accepted'},''),[]);
  assert.notDeepEqual(validateJsonSchemaValue(f.tools.get('spatialforge_run').output.schema,{state:'accepted'},''),[]);
});

test('collaboration observes cancellation and read-only list does not create directories',async(t)=>{
  const f=await fixture(t),tool=f.tools.get('spatialforge_collaboration');
  const workspace=path.join(f.root,'new-workspace');
  assert.deepEqual(await tool.execute({workspace,action:'list'},f.exec()),{handoffs:[]});
  await assert.rejects(fs.stat(workspace),{code:'ENOENT'});
  const abort=new AbortController();abort.abort();
  await assert.rejects(tool.execute({workspace,action:'publish',role:'fixture',summary:'fixture'},f.exec(abort.signal)),{name:'AbortError'});
  await assert.rejects(fs.stat(workspace),{code:'ENOENT'});
  const record=await tool.execute({workspace,action:'publish',role:'fixture',summary:'fixture'},f.exec());
  assert.equal((await tool.execute({workspace,action:'read',handoff_id:record.handoff_id},f.exec())).summary,'fixture');
});

test('image attachment owned work is awaited and cancellation does not return a successful image',async(t)=>{
  const abort=new AbortController();let settled=false;
  const f=await fixture(t,{saveImage:async()=>{abort.abort();await new Promise(resolve=>setTimeout(resolve,15));settled=true;return {id:'image'};}});
  const image=path.join(f.root,'view_0.png');await fs.writeFile(image,'fixture-pixels');
  f.replies.set('/evidence',{task_id:'r.scene0',state:'SUCCEEDED',image_path:image});
  await assert.rejects(f.tools.get('spatialforge_evidence').execute({task_id:'r.scene0',file:'capture/view_0.png'},f.exec(abort.signal)),{name:'AbortError'});
  assert.equal(settled,true);
});
