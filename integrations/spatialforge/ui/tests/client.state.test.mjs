import assert from 'node:assert/strict';
import test from 'node:test';
import {createWorkbenchState} from '../client/state.js';

const state = createWorkbenchState({STAGES: [{id: 'S1'}, {id: 'S2'}], sceneName: (name) => name});

test('new production requests carry an explicit execution and quantity contract', () => {
  const request = state.productionRequest({objective: 'Compare object visibility', count: '24', mode: 'new',
    executionMode: 'exploration', quantityContract: 'best_effort', capability: '', sceneCount: '', storageBudget: ''}, null);
  assert.match(request, /execution_mode=exploration/);
  assert.match(request, /quantity_contract=best_effort/);
  assert.match(request, /target_items=24/);
  assert.match(request, /不得把执行完成表述为数量达标或质量验收通过/);
});

test('conversation and background production states remain independent', () => {
  assert.equal(state.backgroundProductionState({pipelines: [{state: 'completed'}]}), 'idle');
  assert.equal(state.backgroundProductionState({pipelines: [{state: 'running'}]}), 'running');
  assert.equal(state.backgroundProductionState({}), 'unknown');
});
