import assert from 'node:assert/strict';
import {apply} from '../plugin/tools.mjs';
const registered=[];
apply({tools:{register:tool=>registered.push(tool)}});
const requests=[];
globalThis.fetch=async(url,options)=>{
  requests.push({url,body:JSON.parse(options.body)});
  return {ok:true,text:async()=>JSON.stringify({state:'accepted',run_id:'isolated-test'})};
};
const mutations=['spatialforge_diffusion','spatialforge_sam3','spatialforge_sam3d','spatialforge_depth','spatialforge_mesh_import',
                 'spatialforge_capture','spatialforge_layout','spatialforge_run','spatialforge_asset','spatialforge_extend','spatialforge_dataset','spatialforge_refine'];
const exec={agent:{session:{id:'session-a'}},callId:'call-a',signal:new AbortController().signal};
const inputs={
  spatialforge_diffusion:{prompt:'fixture'},spatialforge_sam3:{source_image:'source.png'},
  spatialforge_sam3d:{source_image:'source.png',objects:[]},spatialforge_depth:{source_image:'source.png'},
  spatialforge_mesh_import:{source_mesh:'source.glb',label:'fixture'},spatialforge_capture:{scene_program_path:'scene.json'},
  spatialforge_layout:{name:'fixture',description:'fixture',layout:{mode:'generate',prompt:'fixture'}},
  spatialforge_run:{intents:[{name:'fixture',description:'fixture',split:'dev'}]},
  spatialforge_asset:{intent:{name:'fixture',description:'fixture'}},spatialforge_extend:{parent_task_id:'fixture.scene0',name:'fixture',description:'fixture'},
  spatialforge_dataset:{intent:{}},spatialforge_refine:{parent_task_id:'fixture.scene0',name:'fixture',description:'fixture'}
};
for(const name of mutations){
  const tool=registered.find(t=>t.name===name);
  assert(tool,name);
  assert(!tool.parameters.required?.includes('request_key'),name);
  const args=Object.freeze(inputs[name]);const before=JSON.stringify(args);
  await tool.execute(args,exec);
  assert.equal(requests.at(-1).body.request_key,'dsh:session-a:call-a',name);
  assert.equal(JSON.stringify(args),before);
}
const tool=registered.find(t=>t.name==='spatialforge_layout');
const layout=inputs.spatialforge_layout;
await tool.execute({...layout,request_key:'user-key'},exec);assert.equal(requests.at(-1).body.request_key,'user-key');
await tool.execute(layout,exec);const first=requests.at(-1).body.request_key;
await tool.execute(layout,exec);assert.equal(requests.at(-1).body.request_key,first);
await tool.execute(layout,{...exec,callId:'call-a:ptc:0'});const nested=requests.at(-1).body.request_key;
await tool.execute(layout,{...exec,callId:'call-a:ptc:1'});assert.notEqual(requests.at(-1).body.request_key,nested);
await tool.execute(layout,{...exec,agent:{session:{id:'session-b'}}});assert.notEqual(requests.at(-1).body.request_key,first);
await registered.find(t=>t.name==='spatialforge_status').execute({run_id:'existing'},exec);
assert(!('request_key' in requests.at(-1).body));
console.log('request identity: 12 submission tools, explicit keys, repeated calls and PTC identities passed');
