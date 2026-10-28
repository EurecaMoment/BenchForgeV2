import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import vm from 'node:vm';
import {createWorkbenchHandler} from '../ui/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const fixtureCode = [
  'import json,sys',
  'from pathlib import Path',
  'from benchforge_core.runtime import Runtime',
  'root=Path(sys.argv[1])',
  'r=Runtime(root)',
  'outputs=[]',
  'for seed,count in [(101,30),(202,3)]:',
  ' p=r.call("pipeline_plan",{"template_ids":["C01-T01"],"target_items":count,"seed":seed})',
  ' outputs.append(r.call("pipeline_run",{"plan":p["plan"]}))',
  'r.close()',
  'print(json.dumps(outputs))',
].join('\n');

test('real persisted pipelines: session-workspace isolation, public pagination, contracts and no mutation', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-'));
  const otherDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-other-'));
  try {
    const outputs = JSON.parse(execFileSync(python, ['-c', fixtureCode, directory], {
      cwd: ROOT, env: {...process.env, PYTHONPATH: path.join(ROOT, 'src')}, encoding: 'utf8',
    }));
    const dbStat = await fs.stat(path.join(directory, 'runs.sqlite'));
    const handler = createWorkbenchHandler({}, () => [
      {id: 'registered-workspace', path: directory, title: 'Actual fixture'},
      {id: 'other-workspace', path: otherDirectory, title: 'Other environment'},
    ]);
    const request = async (params) => {
      const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({workspace_path: directory, ...params})));
      assert.equal(response.status, 200, await response.clone().text());
      return response.json();
    };
    const summary = await request({view: 'summary'});
    assert.deepEqual(summary.sources.map((source) => source.workspace), ['Actual fixture']);
    assert.equal(summary.runs.length, 2);
    assert.equal(summary.datasets.length, 2);
    assert.equal(summary.counts.verified, 0);
    assert.ok(summary.counts.candidate > 0);
    const version = summary.datasets.find((x) => x.report.accepted === 30);
    const small = summary.datasets.find((x) => x.report.accepted === 3);
    assert.notEqual(version.id, small.id);
    const otherSummary = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({view: 'summary', workspace_path: otherDirectory})));
    assert.deepEqual((await otherSummary.json()).runs, []);
    const unscopedSummary = await handler(new Request('http://dsh.test/api/benchforge/workbench?view=summary'));
    assert.deepEqual((await unscopedSummary.json()).runs, []);
    const secondPage = await request({view: 'dataset', dataset: version.id, page: 2, page_size: 24});
    assert.equal(secondPage.total, 30);
    assert.equal(secondPage.items.length, 6);
    assert.equal(secondPage.items[0].item_id, 'item_00000024');
    assert.equal(secondPage.authority_exposed, false);
    const other = await request({view: 'dataset', dataset: small.id});
    assert.equal(other.total, 3);
    const crossWorkspace = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({
      view: 'dataset', dataset: version.id, workspace_path: otherDirectory,
    })));
    assert.equal(crossWorkspace.status, 404);
    const filtered = await request({view: 'dataset', dataset: version.id, q: 'item_00000024', template: 'C01-T01', split: 'train'});
    assert.equal(filtered.total, 1);
    assert.equal(filtered.items[0].item_id, 'item_00000024');
    const media = await handler(new Request('http://dsh.test/' + filtered.items[0].media[0]));
    assert.equal(media.status, 200);
    assert.match(media.headers.get('content-type'), /^image\//);
    const details = await request({view: 'run', run: version.run_id});
    assert.ok(details.artifacts.every((x) => x.status === 'candidate'));
    assert.equal(details.plan.steps[0].uses, 'templates.produce');
    assert.equal((await fs.stat(path.join(directory, 'runs.sqlite'))).mtimeMs, dbStat.mtimeMs);

    // A public allowlist still removes accidentally added authority fields.
    const questions = path.join(outputs[0].outputs.questions.dataset, 'questions.jsonl');
    const lines = (await fs.readFile(questions, 'utf8')).trim().split('\n');
    const row = JSON.parse(lines[0]);
    row.answer = 'PRIVATE_ORACLE_SENTINEL';
    row.authority = {oracle: 'PRIVATE_ORACLE_SENTINEL'};
    lines[0] = JSON.stringify(row);
    await fs.writeFile(questions, lines.join('\n') + '\n');
    const response = await request({view: 'dataset', dataset: version.id});
    assert.ok(!JSON.stringify(response).includes('PRIVATE_ORACLE_SENTINEL'));
    const escape = Buffer.from(JSON.stringify(['registered-workspace', '..'])).toString('base64url');
    const workspaceParam = 'workspace_path=' + encodeURIComponent(directory);
    assert.equal((await handler(new Request('http://dsh.test/api/benchforge/workbench?view=dataset&dataset=' + escape + '&' + workspaceParam))).status, 403);
    const invalidPage = await handler(new Request('http://dsh.test/api/benchforge/workbench?view=dataset&dataset=' + version.id + '&page=-1&' + workspaceParam));
    assert.equal(invalidPage.status, 400);
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
    await fs.rm(otherDirectory, {recursive: true, force: true});
  }
});

test('missing manifest counts remain unknown and an empty index is not invented as verified data', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'benchforge-ui-empty-'));
  try {
    const handler = createWorkbenchHandler({workspacePaths: [directory]});
    const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({workspace_path: directory})));
    const summary = await response.json();
    assert.equal(summary.counts, null);
    assert.deepEqual(summary.runs, []);
    assert.equal(summary.sources[0].status, 'no_index');
  } finally { await fs.rm(directory, {recursive: true, force: true}); }
});

test('evaluation launcher is gated to SpatialForge and opens its right-side session panel', async () => {
  let registration;
  vm.runInNewContext(await fs.readFile(path.join(ROOT, 'integrations/spatialforge/ui/client.js'), 'utf8'),
    {window: {__ModuleLoader__: {load: (value) => registration = value}}});
  assert.equal(registration.id, '@eurecamoment/benchforge-spatialforge-ui');
  const plugin = registration.factory((id) => {
    assert.equal(id, 'react');
    return {createElement: (type, props, ...children) => ({type, props: props || {}, children})};
  });
  const seats = [], disposed = [], opened = [], components = new Map();
  let definition;
  plugin.apply({
    locale: {register: (_ns, dictionaries) => {
      assert.deepEqual(Object.keys(dictionaries.zh), Object.keys(dictionaries.en));
      return () => disposed.push('locale');
    }, bind: () => (key) => key},
    effect: (effect) => { const cleanup = effect(); disposed.push(cleanup); },
    sidebarRight: {openTab: (kind) => opened.push(kind)},
    sidebarRightTabs: {register: (value) => { definition = value; return () => {}; }},
    slots: {inject: (seat, callback) => { seats.push(seat); callback(); }, register: (options, component) => {
      components.set(options.id || options.key, component);
      return () => {};
    }},
  });
  assert.deepEqual(seats, ['sidebar.right.pane.tab', 'conversation.session.header.utilities']);
  assert.equal(definition.kind, 'benchforge-spatialforge-evaluation');
  assert.equal(definition.guide, undefined);
  const launcher = components.get('spatialforge-evaluation-launcher');
  assert.equal(launcher({useProjection: () => 'benchforgev2'}), null);
  const spatialForgeButton = launcher({useProjection: () => 'spatialforge-standard-ptc'});
  assert.equal(spatialForgeButton.type, 'button');
  spatialForgeButton.props.onClick();
  assert.deepEqual(opened, ['benchforge-spatialforge-evaluation']);
  assert.equal(components.get('benchforge-spatialforge-evaluation')({useProjection: () => 'benchforgev2'}), null);
  disposed.find((entry) => typeof entry === 'function')();
  assert.ok(disposed.includes('locale'));
});

test('template selector pages the real catalog and filters by capability without exposing oracle fields', async () => {
  const handler = createWorkbenchHandler({});
  const query = async (params) => {
    const response = await handler(new Request('http://dsh.test/api/benchforge/workbench?' + new URLSearchParams({view: 'catalog', ...params})));
    assert.equal(response.status, 200);
    return response.json();
  };
  const first = await query({});
  const second = await query({page: '2'});
  assert.equal(first.task_count, 89);
  assert.equal(first.template_count, 267);
  assert.equal(first.items.length, 12);
  assert.notEqual(first.items[0].id, second.items[0].id);
  const selected = await query({q: 'C01-T01', capability: 'N01'});
  assert.equal(selected.total, 1);
  assert.equal(selected.items[0].id, 'C01-T01');
  assert.ok(!('effective_oracle' in selected.items[0]));
  const mismatch = await query({q: 'C01-T01', capability: 'N27'});
  assert.equal(mismatch.total, 0);
});

