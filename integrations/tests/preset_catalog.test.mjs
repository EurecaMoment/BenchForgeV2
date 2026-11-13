import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import AgentPreset from '@deepseek-ai/dsh-agent-preset';
import {applyEntryPatches} from '@deepseek-ai/cordis-plugin-include';
import {presetDisplayText} from '@deepseek-ai/dsh-agent-preset-registry/display';
import {Config as businessConfig, apply as applyBusinessTools} from '../dsh/tools.mjs';
import {Config as spatialConfig} from '../spatialforge/plugin/tools.mjs';
import {Config as workbenchConfig, createWorkbenchHandler} from '../spatialforge/ui/index.js';
import {Config as shellConfig} from '../dsh/persistent-shell.mjs';

const integrations = path.resolve(import.meta.dirname, '..');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const source = [
  'import json,sys',
  'from pathlib import Path',
  'sys.path.insert(0, str(Path("dsh").resolve()))',
  'from build_preset import Loader',
  'import yaml',
  'print(json.dumps(yaml.load(Path("cordis.patch.yml").read_text(encoding="utf-8"), Loader=Loader)))',
].join('\n');
const catalog = JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', source], {cwd: integrations, encoding: 'utf8'}));

test('unified model settings apply through the real DSH overlay contract', () => {
  const modelSource = [
    'import json,sys,tempfile',
    'from pathlib import Path',
    'sys.path.insert(0, str(Path("dsh").resolve()))',
    'from build_preset import model_patches',
    'with tempfile.TemporaryDirectory() as folder:',
    '    config = Path(folder)/"models.json"',
    '    config.write_text(json.dumps({"model_roles":{"dsh":"qwen"}, "models":{"qwen":{"url":"https://fixture/v1","model":"fixture-vlm","token_env":"FIXTURE_KEY"}}}), encoding="utf8")',
    '    print(json.dumps(model_patches(config)))',
  ].join('\n');
  const patches = JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', modelSource],
    {cwd: integrations, encoding: 'utf8'}));
  const warnings = [];
  const base = [
    {id: 'llm-pi-ai', name: '@deepseek-ai/dsh-llm-pi-ai'},
    {id: 'agent-default-model', name: '@deepseek-ai/dsh-agent-default-model',
      config: {provider: 'deepseek-official', model: 'deepseek-flash'}},
    {id: 'historical-workbench', config: {workspace: 'retained'}},
  ];
  const result = applyEntryPatches(base, patches, (...warning) => warnings.push(warning));
  assert.deepEqual(warnings, []);
  assert.equal(result[0].config.providers['benchforge-models'].baseURL, 'https://fixture/v1');
  assert.deepEqual(result[1].config, {provider: 'benchforge-models', model: 'fixture-vlm'});
  assert.deepEqual(result[2], base[2]);
  assert.equal(base[1].config.model, 'deepseek-flash');
});

test('shipped custom preset configurations validate against installed DSH and plugin schemas', () => {
  const schemas = new Map([
    ['@deepseek-ai/dsh-agent-preset', AgentPreset.Config],
    ['@eurecamoment/benchforge-dsh/benchforge-tools', businessConfig],
    ['@eurecamoment/benchforge-dsh/spatialforge-tools', spatialConfig],
    ['@eurecamoment/benchforge-dsh/spatialforge-ui', workbenchConfig],
    ['@eurecamoment/benchforge-dsh/persistent-shell', shellConfig],
  ]);
  const checked = [];
  function walk(rows) {
    for (const row of rows) {
      const schema = schemas.get(row.name);
      if (schema) {
        const result = schema['~standard'].validate(row.config || {});
        assert.equal(result.issues, undefined, row.id + ': ' + JSON.stringify(result.issues));
        checked.push(row.id);
      }
      if (row.config?.plugins) walk(row.config.plugins);
      if (Array.isArray(row.config)) walk(row.config);
    }
  }
  walk(catalog.flatMap(patch => patch.insert || []));
  assert.equal(checked.filter(id => id.startsWith('preset-')).length, 2);
  assert.equal(checked.filter(id => id === 'benchforge-workbench-ui').length, 1);
  assert.equal(checked.filter(id => id === 'spatialforge-tools').length, 2);
});

test('DSH resolves a retained SpatialForge session identity to the new visible name', () => {
  const session = {id: 'session-existing', projectionValues: {agentPreset: 'spatialforge-standard-ptc'}};
  const original = structuredClone(session);
  const presets = catalog.flatMap(patch => patch.insert || [])
    .filter(row => row.name === '@deepseek-ai/dsh-agent-preset').map(row => row.config);
  assert.deepEqual(presets.map(preset => preset.name), ['BenchForgeV2', 'BenchForgeV2_UI']);
  const selected = presets.find(preset => preset.id === session.projectionValues.agentPreset);
  assert.equal(presetDisplayText(selected, key => key).name, 'BenchForgeV2_UI');
  assert.deepEqual(session, original);
});

test('workbench adoption reports the loaded revision without accessing conversation data', async () => {
  const handler = createWorkbenchHandler({uiRevision: 'new-reader'}, () => {throw new Error('unexpected workspace scan');});
  const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?view=runtime'));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), {ui_revision: 'new-reader',
    preset_id: 'spatialforge-standard-ptc', preset_name: 'BenchForgeV2_UI'});
});

test('each preset registers its declared tool set without starting services or processes', async () => {
  const presets = catalog.flatMap(patch => patch.insert || [])
    .filter(row => row.name === '@deepseek-ai/dsh-agent-preset');
  for (const preset of presets) {
    const business = preset.config.plugins.find(row => ['benchforge-tools', 'spatial-learning-tools'].includes(row.id));
    const tools = [], cleanup = [];
    await applyBusinessTools({get: () => undefined, tools: {register: tool => tools.push(tool)},
      effect: fn => cleanup.push(fn()), subprocess: {}, attachments: {}}, business.config);
    assert.deepEqual(tools.map(tool => tool.name).sort(), business.config.includeTools.map(id => 'benchforge_' + id).sort());
    assert.ok(tools.some(tool => tool.name === 'benchforge_pipeline_run'));
    for (const dispose of cleanup.reverse()) if (typeof dispose === 'function') await dispose();
  }
});

test('the business plugin omits retired tools even with no configured include list', async () => {
  const tools = [], cleanup = [];
  await applyBusinessTools({get: () => undefined, tools: {register: tool => tools.push(tool)},
    effect: fn => cleanup.push(fn()), subprocess: {}, attachments: {}}, {});
  const retired = ['method', 'annotate', 'kinship', 'images', 'compile', 'synthesize', 'screen', 'diagnose'];
  assert.ok(tools.some(tool => tool.name === 'benchforge_pipeline_run'));
  assert.ok(tools.every(tool => !retired.includes(tool.name.replace(/^benchforge_/, ''))));
  for (const dispose of cleanup.reverse()) if (typeof dispose === 'function') await dispose();
});
