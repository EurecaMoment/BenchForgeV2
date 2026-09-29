import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { inspectDeliveryFiles, createDeliveryFileReview, fileReviewKind } from '../plugin/delivery_files.mjs';

const signal = new AbortController().signal;
test('renamed delivered images are reported and metadata repair clears findings without editing source', async () => {
  const cwd=await fs.mkdtemp(path.join(os.tmpdir(),'sf-delivery-'));
  try {
    const root=path.join(cwd,'final'),views=path.join(root,'views');await fs.mkdir(views,{recursive:true});
    const original={frame_id:'view_0',image:'view_0.png',image_size:{width:10,height:10}};
    await fs.writeFile(path.join(cwd,'view_0.json'),JSON.stringify(original));
    await fs.writeFile(path.join(views,'view_0.json'),JSON.stringify(original));
    await fs.writeFile(path.join(views,'overview.png'),'image');
    const files=[{path:'final/README.md'},{path:'final/views/overview.png'}];
    const result=await inspectDeliveryFiles(files,cwd,signal);
    assert.equal(result.views,1);assert.equal(result.issues.length,1);
    assert.equal(result.issues[0].target,path.join(views,'view_0.png'));
    await fs.writeFile(path.join(views,'view_0.json'),JSON.stringify({...original,image:'overview.png'}));
    assert.deepEqual(await inspectDeliveryFiles(files,cwd,signal),{views:1,issues:[]});
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(cwd,'view_0.json'))),original);
    assert.deepEqual(await inspectDeliveryFiles([{path:'README.md'}],cwd,signal),{views:0,issues:[]});
  } finally { await fs.rm(cwd,{recursive:true,force:true}); }
});

test('actual delivery feedback works after capture review and across turns; unchanged findings do not loop', async () => {
  const events=[{type:'tool/call',data:{name:'spatialforge_capture'}},
    {type:'user/message',data:{source:{kind:'spatialforge-delivery-review',capture_call_id:'c1'}}},
    {type:'deliverables/presented',data:{turn:2,callId:'p1',files:[{path:'final/README.md'}]}}];
  const messages=[];let result={views:1,issues:[{metadata:'view_0.json',problem:'image_not_found'}]};
  const review=createDeliveryFileReview({createMessage:x=>x,inspect:async()=>result});
  const agent={session:{header:{cwd:'/task'},snapshotEvents:()=>events},steer:m=>{messages.push(m);events.push({type:'user/message',data:m});}};
  await review({agent,turn:2,signal});await review({agent,turn:2,signal});
  assert.equal(messages.length,1);assert.equal(messages[0].source.kind,fileReviewKind);
  result={views:1,issues:[]};await review({agent,turn:2,signal});assert.equal(messages.length,1);
  await review({agent,turn:3,signal});assert.equal(messages.length,1);
});

test('ordinary file presentations and scene turns without present are not inspected', async () => {
  let calls=0;const review=createDeliveryFileReview({createMessage:x=>x,inspect:async()=>{calls++;}});
  for (const events of [[{type:'deliverables/presented',data:{turn:1,files:[]}}],
    [{type:'tool/call',data:{name:'spatialforge_capture'}}]]) {
    await review({agent:{session:{snapshotEvents:()=>events}},turn:1,signal});
  }
  assert.equal(calls,0);
});
