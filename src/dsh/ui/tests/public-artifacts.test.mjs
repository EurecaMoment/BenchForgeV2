import assert from 'node:assert/strict';
import test from 'node:test';
import {createPublicArtifactProjector} from '../../host/workbench/public_artifacts.js';

const pick = (value, fields) => Object.fromEntries(fields.filter((field) => field in value).map((field) => [field, value[field]]));
const project = createPublicArtifactProjector({pick, taskTemplates: {tasks: [{templates: [{id: 'T1', title: 'Visibility'}]}]}});

test('delivery fields survive public projection while private answers stay hidden', () => {
  const report = project.publicReport({quantity_contract: 'minimum', target_items: 20, accepted: 17, shortfall: 3,
    target_reached: false, delivery_satisfied: false, delivery_status: 'partial', ground_truth: 'private',
    nested: {answer_key: 'private'}, body_markdown: '17 accepted'});
  assert.deepEqual(report, {quantity_contract: 'minimum', target_items: 20, accepted: 17, shortfall: 3,
    target_reached: false, delivery_satisfied: false, delivery_status: 'partial', body_markdown: '17 accepted'});
});

test('plan titles resolve from the package-local catalog projection', () => {
  const plan = project.publicPlan({template_contracts: [{id: 'T1', task_name: 'fallback', answer_key: 'private'}]});
  assert.deepEqual(plan.template_contracts, [{id: 'T1', task_name: 'fallback', title: 'Visibility'}]);
});
