import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {loadServiceConfig, parseStrictJson} from '../shared/config.mjs';
import {readAssessmentTemplate, readTaskTemplates} from '../shared/resources.mjs';

async function fixture(t, {mode = 'production', policy = {enabled: true, enforce_realism: true}} = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'spatialforge-config-'));
  t.after(() => fs.rm(root, {recursive: true, force: true}));
  const configDir = path.join(root, 'config');
  await fs.mkdir(configDir);
  if (policy) await fs.writeFile(path.join(configDir, 'scene-policy.json'), JSON.stringify(policy));
  const serverConfig = path.join(configDir, 'spatialforge-server.local.json');
  await fs.writeFile(serverConfig, JSON.stringify({
    port: 3941, operator_token_env: 'SPATIALFORGE_TEST_TOKEN', execution_mode: mode,
    ...(policy ? {scene_policy_path: 'scene-policy.json'} : {}),
  }));
  const clientConfig = path.join(configDir, 'spatialforge.local.json');
  await fs.writeFile(clientConfig, JSON.stringify({service_config: 'spatialforge-server.local.json'}));
  const getEnvironmentValue = async name => name === 'SPATIALFORGE_TEST_TOKEN' ? 'fixture-token' : undefined;
  return {root, serverConfig, clientConfig, getEnvironmentValue};
}

test('service config reference resolves relative values and env-backed credentials', async t => {
  const f = await fixture(t);
  const result = await loadServiceConfig(f.clientConfig, {getEnvironmentValue: f.getEnvironmentValue});
  assert.equal(result.serviceUrl, 'http://127.0.0.1:3941');
  assert.equal(result.operatorToken, 'fixture-token');
  assert.equal(result.executionMode, 'production');
  assert.equal(result.scenePolicyPath, path.join(path.dirname(f.serverConfig), 'scene-policy.json'));
});

test('explicit service overrides resolve environment references and conflicting references fail', async t => {
  const f = await fixture(t, {mode: 'exploration', policy: null});
  await fs.writeFile(f.clientConfig, JSON.stringify({service_config: 'spatialforge-server.local.json', port: 3942}));
  await assert.rejects(loadServiceConfig(f.clientConfig, {getEnvironmentValue: f.getEnvironmentValue}), /port.*conflicts/);
  await fs.writeFile(f.clientConfig, JSON.stringify({service_config: 'spatialforge-server.local.json'}));
  const result = await loadServiceConfig(f.clientConfig, {getEnvironmentValue: f.getEnvironmentValue});
  assert.equal(result.executionMode, 'exploration');
  assert.equal(result.scenePolicyPath, null);
});

test('configured execution mode rejects a conflicting environment override', async t => {
  const f = await fixture(t);
  const getEnvironmentValue = async name => name === 'SPATIALFORGE_EXECUTION_MODE' ? 'exploration' : f.getEnvironmentValue(name);
  await assert.rejects(loadServiceConfig(f.clientConfig, {getEnvironmentValue}), /conflicts with configured execution_mode/);
});

test('strict JSON rejects duplicate keys at every object level', () => {
  assert.throws(() => parseStrictJson('{"outer":{"name":1,"name":2}}'), /Duplicate JSON key: name/);
});

test('package-local task and assessment templates are readable', async () => {
  const tasks = await readTaskTemplates();
  const assessment = await readAssessmentTemplate();
  assert.ok(Array.isArray(tasks.tasks) && tasks.tasks.length > 0);
  assert.equal(typeof assessment, 'object');
});
