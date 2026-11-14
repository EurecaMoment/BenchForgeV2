import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {nativeCaptureAssociations, createCaptureAssociations} from '../host/capture/capture_associations.mjs';

const events=[{type:'tool/call',data:{name:'benchforge_capture',callId:'native-1',arguments:'{"request_key":"office-custom"}'}},
  {type:'tool/result',time:123,data:{message:{toolCallId:'native-1',content:[{type:'text',text:'{"run_id":"sf_office","task_id":"sf_office.scene0"}'}]}}}];

test('custom keys retain ownership only through their paired native tool result',()=>{
  assert.equal(nativeCaptureAssociations(events)[0].run_id,'sf_office');
  const forged=[{type:'user/message',data:{message:{content:[{type:'text',text:'{"run_id":"sf_other"}'}]}}}];
  assert.deepEqual(nativeCaptureAssociations(forged),[]);
  assert.deepEqual(nativeCaptureAssociations([events[0],{...events[1],data:{message:{...events[1].data.message,isError:true}}}]),[]);
});

test('backfill runs once and records are isolated to the admitted parent workspace',async t=>{
  const root=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'native-capture-association-')));
  t.after(async()=>{assert.ok(path.basename(root).startsWith('native-capture-association-'));await fs.rm(root,{recursive:true,force:true});});
  let reads=0;
  // Native session headers have cwd/origin; the admitted runtime owns the ID.
  const agent={id:'session-parent',session:{header:{cwd:root},snapshotEvents:()=>{reads++;return events;}}};
  const associations=createCaptureAssociations({roots:()=>[root],ctx:{get:()=>new Map([[agent.id,agent]])}});
  await associations.warm(agent.id);await associations.warm(agent.id);await associations.record(agent,events);
  const file=path.join(root,'.benchforge','capture-associations','session-parent.json');
  const saved=JSON.parse(await fs.readFile(file,'utf8'));assert.equal(reads,1);assert.equal(saved.captures.length,1);
  assert.equal(saved.context.session_id,agent.id);
  const foreign={id:'session-foreign',session:{header:{id:'session-foreign',cwd:path.dirname(root)}}};
  await associations.record(foreign,events);
  await assert.rejects(fs.readFile(path.join(root,'.benchforge','capture-associations','session-foreign.json')),/ENOENT/);
});
