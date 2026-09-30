import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDeliveryVisuals } from '../plugin/delivery_visuals.mjs';

test('visual feedback resolves both images from the latest task and revision, without guessing paths', async () => {
  const requests = [];
  const blocks = [{type:'image',attachment:{name:'reference.png'}},{type:'image',attachment:{name:'view_0.png'}},{type:'image',attachment:{name:'view_1.png'}},{type:'image',attachment:{name:'view_2.png'}}];
  const create = createDeliveryVisuals({
    api: async (_route, args) => { requests.push(args); return {source_path:'/resolved/' + args.file}; },
    images: async paths => { assert.deepEqual(paths, ['/resolved/layout/reference.png','/resolved/capture/view_0.png','/resolved/capture/view_1.png','/resolved/capture/view_2.png']); return blocks; },
  });
  const content = await create({task:{id:'sf_latest.scene0',unit:{revision:3,intent:{layout:{mode:'reference',design_task_id:'sf_design.scene0'}}},result:{report:{frames:3}}}});
  assert.deepEqual(requests.map(r=>[r.task_id,r.revision,r.file]),[['sf_latest.scene0',3,'layout/reference.png'],['sf_latest.scene0',3,'capture/view_0.png'],['sf_latest.scene0',3,'capture/view_1.png'],['sf_latest.scene0',3,'capture/view_2.png']]);
  assert.deepEqual(content.filter(c=>c.type==='image'),blocks);
  assert.match(content[2].text,/Latest capture view_0/);
});

test('standalone diffusion followed by capture still supplies actual renders without guessing a reference', async () => {
  const requests = [];
  const create = createDeliveryVisuals({
    api: async (_route, args) => { requests.push(args); return {source_path:args.file}; },
    images: async paths => paths.map(name => ({type:'image',attachment:{name}})),
  });
  const content = await create({task:{id:'sf_duplex.scene0',unit:{revision:0,intent:{}},result:{report:{frames:10}}}});
  assert.deepEqual(requests.map(r=>r.file),Array.from({length:10},(_,i)=>`capture/view_${i}.png`));
  assert.equal(content.filter(c=>c.type==='image').length,10);
  assert.match(content[0].text,/no linked design reference/);
  assert.match(content[0].text,/source_image/);
  assert.match(content[0].text,/without a reference needs no reference/);
  assert.match(content.at(-2).text,/Latest capture view_9/);
});

test('text-only routes keep the source paths without pretending to show images', async () => {
  const create = createDeliveryVisuals({api:async(_route,args)=>({source_path:args.file}),images:async()=>[]});
  const content=await create({task:{id:'sf_latest.scene0',unit:{revision:0,intent:{layout:{mode:'generate'}}}}});
  assert.equal(content.length,2);
  assert.ok(content.every(c=>c.type==='text'));
  assert.match(content[0].text,/layout\/reference.png/);
  assert.match(content[1].text,/capture\/view_0.png/);
});
