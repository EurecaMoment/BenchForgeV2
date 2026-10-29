import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { validateJsonSchemaValue } from '@deepseek-ai/dsh-tools';
import { apply, Config } from '../plugin/tools.mjs';

async function fixture(t,{saveImage=async()=>({id:'fixture-image'})}={}){
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'sf-plugin-contract-'));
  const replies=new Map(),requests=[];
  const server=http.createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({path:req.url,args:JSON.parse(body),authorization:req.headers.authorization});
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify(replies.get(req.url)??{}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await fs.rm(root,{recursive:true,force:true});});
  const serviceConfig=path.join(root,'service.json');
  await fs.writeFile(serviceConfig,JSON.stringify({service_url:`http://127.0.0.1:${server.address().port}`,operator_token:'test-token'}));
  const tools=new Map();
  const ctx={
    tools:{register:tool=>tools.set(tool.name,tool)},on(){},
    llm:{resolveModelInfo:async()=>({inputModalities:['image']})},
    attachments:{saveImage},
    get(name){return this[name];},
  };
  await apply(ctx,Config({serviceConfig,dshRoot:'/ignored/legacy/source/path'}));
  const exec=(signal=new AbortController().signal)=>({signal,callId:'fixture-call',agent:{session:{id:'fixture-session',requestHeader:()=>({config:{provider:'fixture',model:'fixture'}})},options:{}}});
  return {root,tools,replies,requests,exec};
}

test('Config rejects missing or mistyped service config and accepts the legacy preset field',async(t)=>{
  assert.throws(()=>Config({}),/serviceConfig/);
  assert.throws(()=>Config({serviceConfig:12}),/serviceConfig/);
  const f=await fixture(t);
  assert.equal(f.tools.size,21);
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
