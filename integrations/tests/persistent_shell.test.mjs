import assert from 'node:assert/strict';
import test from 'node:test';
import {Config,apply} from '../dsh/persistent-shell.mjs';

test('persistent shell config validates and preserves official deployment controls',()=>{
  const result=Config['~standard'].validate({shell:'pwsh',backendType:'custom',timeoutMs:1200,
    maxOutputChars:2048,description:'Configured shell',dshRoot:'/legacy/path'});
  assert.equal(result.issues,undefined);
  assert.equal(result.value.backendType,'custom');
  assert.equal(result.value.timeoutMs,1200);
  assert.equal(result.value.maxOutputChars,2048);
  assert.ok(Config['~standard'].validate({shell:'unsupported'}).issues);
});

test('both official persistent tools retain registration and disposal ownership',async()=>{
  for(const shell of ['bash','pwsh']){
    const registered=[];
    const dispose=[];
    const ctx={
      tools:{register(definition){registered.push(definition);}},
      effect(setup){dispose.push(setup());},
      terminals:{list(){return [];},async kill(){throw new Error('no shell was spawned');}},
    };
    const parsed=Config['~standard'].validate({shell,backendType:'custom',timeoutMs:1200,
      maxOutputChars:2048,description:'Configured shell'});
    assert.equal(parsed.issues,undefined);
    await apply(ctx,parsed.value);
    assert.equal(registered.length,1);
    assert.equal(registered[0].name,`persistent_${shell}`);
    assert.equal(registered[0].description,'Configured shell');
    assert.equal(dispose.length,1);
    await Promise.all(dispose.map(cleanup=>cleanup()));
  }
});
