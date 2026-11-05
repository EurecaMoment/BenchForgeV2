import assert from 'node:assert/strict';
import test from 'node:test';
import {sessionFamilyReader} from '../ui/parallel_sessions.js';

test('parent catalog and immutable headers scope children without scanning session history', async () => {
  const calls = [], residents = new Map([['session-good', {header: {parentSession: 'session-parent'}}],
    ['session-forged', {header: {parentSession: 'session-other'}}]]);
  const services = {
    subagents: {listChildren: async () => [
      {id: 'session-good', label: '标注提取器修复'}, {id: 'session-cold', label: '题目生成器修复'},
      {id: 'session-forged', label: 'unrelated'}, {id: 'session-corrupt'}]},
    sessions: {get: (id) => residents.get(id)},
    sessionQuery: {observeSession: async (id, options) => {
      calls.push({id, options});
      if (id === 'session-corrupt') throw Error('unreadable');
      return {header: {parentSession: id === 'session-forged' ? 'session-other' : 'session-parent'},
        projections: {values: {subagentTiming: {active: id === 'session-good'}}},
        [Symbol.dispose]: () => calls.push({disposed: id})};
    }},
  };
  const family = sessionFamilyReader({get: (name) => services[name]});
  const children = await family('session-parent');
  assert.deepEqual(children.map((row) => [row.id, row.state]), [
    ['session-good', 'running'], ['session-cold', 'inactive']]);
  assert.equal(calls.find((row) => row.id === 'session-cold').options.projectionMode, 'none');
  assert.equal(calls.filter((row) => row.disposed).length, 3);
  await family('session-parent');
  assert.equal(calls.filter((row) => row.id === 'session-cold').length, 1);
  residents.set('session-good', {header: {parentSession: 'session-other'}});
  services.sessionQuery.observeSession = async () => ({
    header: {parentSession: 'session-other'}, projections: {values: {subagentTiming: {active: false}}},
    [Symbol.dispose]() {},
  });
  assert.ok(!(await family('session-parent')).some((row) => row.id === 'session-good'));
});

test('normal workbench remains available without a subagent provider', async () => {
  assert.deepEqual(await sessionFamilyReader({get: () => undefined})('session-parent'), []);
});
