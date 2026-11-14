import assert from 'node:assert/strict';
import test from 'node:test';
import {sessionFamilyReader} from '../host/sessions/parallel_sessions.js';

test('parent catalog and immutable headers scope children without scanning session history', async () => {
  const calls = [], residents = new Map([['session-good', {header: {parentSession: 'session-parent'}}],
    ['session-forged', {header: {parentSession: 'session-other'}}]]);
  const entries = [
    {id: 'session-good', label: '标注提取器修复'}, {id: 'session-cold', label: '题目生成器修复'},
    {id: 'session-forged', label: 'unrelated'}, {id: 'session-corrupt'}];
  const services = {
    sessions: {get: (id) => residents.get(id)},
    sessionQuery: {observeSession: async (id, options) => {
      if (id === 'session-parent') return {projections: {values: {subagentCatalog: entries}}, [Symbol.dispose]() {}};
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
  const observe = services.sessionQuery.observeSession;
  services.sessionQuery.observeSession = async id => id === 'session-parent' ? observe(id) : ({
    header: {parentSession: 'session-other'}, projections: {values: {subagentTiming: {active: false}}},
    [Symbol.dispose]() {},
  });
  assert.ok(!(await family('session-parent')).some((row) => row.id === 'session-good'));
});

test('normal workbench remains available without a subagent provider', async () => {
  assert.deepEqual(await sessionFamilyReader({get: () => undefined})('session-parent'), []);
});

test('more than eight children retain active residents and newest work without opening the historical corpus', async () => {
  const entries = Array.from({length: 12}, (_, index) => ({id: 'session-child-' + index,
    createdAt: Date.UTC(2026, 10, 5, 0, index)})).reverse();
  const calls = [], residents = new Map(['session-child-10', 'session-child-11'].map((id) =>
    [id, {header: {parentSession: 'session-parent'}}]));
  const services = {
    sessions: {get: (id) => residents.get(id)},
    sessionQuery: {observeSession: async (id, options) => {
      if (id === 'session-parent') return {projections: {values: {subagentCatalog: entries}}, [Symbol.dispose]() {}};
      calls.push({id, options});
      return {header: {parentSession: 'session-parent'},
        projections: {values: {subagentTiming: {active: id === 'session-child-11'}}}, [Symbol.dispose]() {}};
    }},
  };
  const family = sessionFamilyReader({get: (name) => services[name]});
  const first = await family('session-parent');
  assert.deepEqual(first.map((row) => row.id), [11, 10, 9, 8, 7, 6, 5, 4].map((index) => 'session-child-' + index));
  assert.equal(first[0].state, 'running');
  assert.ok(first.slice(1).every((row) => row.state === 'inactive'));
  assert.equal(calls.length, 8);
  assert.equal(calls.find((row) => row.id === 'session-child-9').options.projectionMode, 'none');
  for (let index = 12; index < 22; index++) {
    const entry = {id: 'session-child-' + index, createdAt: new Date(Date.UTC(2026, 10, 5, 0, index)).toISOString()};
    entries.push(entry); residents.set(entry.id, {header: {parentSession: 'session-parent'}});
  }
  const second = await family('session-parent');
  assert.equal(second[0].id, 'session-child-11', 'a running resident must survive newer inactive resident entries');
  assert.equal(second[0].state, 'running');
  assert.equal(second.length, 8);
  assert.equal(calls.length, 16, 'each poll must remain bounded to eight exact child observations');
  assert.ok(calls.every((row) => !['session-child-0', 'session-child-1', 'session-child-2', 'session-child-3'].includes(row.id)));
});
