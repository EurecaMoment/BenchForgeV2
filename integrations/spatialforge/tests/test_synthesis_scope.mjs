import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {createWorkbenchHandler} from '../ui/stage_products.js';

test('native preparation is bound to the saved current-parent plan',async () => {
  const root=await fs.mkdtemp(path.join(await fs.realpath(os.tmpdir()),'benchforge-synthesis-scope-'));
  try {
    const operation=path.join(root,'operations','plan');
    await fs.mkdir(operation,{recursive:true});
    const plan=path.join(operation,'plan.json');
    await fs.writeFile(plan,'{}');
    await fs.writeFile(path.join(operation,'request.json'),JSON.stringify({context:{session_id:'session-parent'}}));
    const calls=[];
    const controller={start:async value => {calls.push(value);return {state:'accepted',acceptedCount:1};},
      read:async value => ({...value,state:'accepted',acceptedCount:1})};
    const handler=createWorkbenchHandler({},() => [{id:'workspace',path:root}],async () => [],directory => {
      assert.equal(directory,root);return controller;
    });
    const request=(params={},headers={}) => new Request('http://dsh.test/api/benchforge/workbench?'+new URLSearchParams({
      workspace_path:root,session_id:'session-parent',view:'synthesis_start',...params}),{
      method:'POST',headers,body:JSON.stringify({plan_path:plan,batch_key:'repairs',tasks:[{key:'annotation'}]})});
    const accepted=await handler(request());
    assert.equal(accepted.status,200,await accepted.clone().text());
    assert.equal((await accepted.json()).state,'accepted');
    assert.equal(calls[0].parentId,'session-parent');
    assert.equal((await handler(request({session_id:'session-other'}))).status,403);
    assert.equal((await handler(request({scope:'workspace'}))).status,400);
    assert.equal((await handler(request({}, {'sec-fetch-site':'cross-site'}))).status,403);
    assert.equal(calls.length,1);
    const status=await handler(new Request('http://dsh.test/api/benchforge/workbench?'+new URLSearchParams({
      workspace_path:root,session_id:'session-parent',view:'synthesis_status',batch_key:'repairs'})));
    assert.equal(status.status,200);
    assert.equal((await status.json()).parentId,'session-parent');
  } finally {await fs.rm(root,{recursive:true,force:true});}
});
