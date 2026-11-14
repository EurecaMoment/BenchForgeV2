import {createSceneQueries} from '../tools/scene/queries.mjs';
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createInterface} from 'node:readline';
import {DatabaseSync} from 'node:sqlite';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import z from '@deepseek-ai/schemastery';
import {sessionFamilyReader} from '../host/session_family.mjs';
import {createPreparationProducts} from './projections/preparation_products.mjs';
import {ApiError, assertSessionDirectory, exists, inside, matchesSession, readJson, resolveToken, scopeOf,
  scopeParams, token, workspaceRoots} from '../host/session_scope.mjs';
import {createDatasetReader, createPublicArtifactProjector, PUBLIC_FIELDS, QUALITY_FIELDS} from './projections/public_artifacts.mjs';
import {createWorkbenchReadRoutes} from './projections/routes.mjs';
import {WorkbenchRemote} from '../remote/lib/types/index.js';
import {TYPERT} from '../remote/lib/typert.host.js';
import {readAssessmentTemplate, readTaskTemplates} from './resources.mjs';

export const name = 'benchforge-ui';
export const inject = ['connection', 'typert', 'workspaceRegistry', 'benchforgeCapture', 'benchforgeSessions'];
export const Config = z.object({
  workspacePaths: z.array(z.string()).default([]),
  maxRuns: z.natural().min(1).max(200).default(60),
  maxArtifacts: z.natural().min(1).max(1000).default(300),
  uiRevision: z.string().default('live-production-v1'),
  productionConfig: z.string().default(''),
  productionPython: z.string().default('python3'),
});

const STATUSES = ['draft', 'candidate', 'verified', 'rejected', 'superseded'];
const pick = (row, fields) => Object.fromEntries(fields.filter((key) => key in row).map((key) => [key, row[key]]));
const counts = () => Object.fromEntries(STATUSES.map((key) => [key, 0]));
const execute = promisify(execFile);
const STAGE_OPERATIONS = [
  ['S1', /^(plan|pipeline_plan|brief|design|literature)/],
  ['S2', /^(acquire|collect|capture|scene|asset|reference|(?:benchforge|spatialforge)\.(start|capture|asset|refine))/],
  ['S3', /^(annotat|normaliz|structur|evidence|trajectory|(?:benchforge|spatialforge)\.(observe|evidence|task_code))/],
  ['S4', /^(build|synthesi|templates\.produce|dataset|produce)/],
  ['S5', /^(score|screen|evaluat|verif|quality|report|package|(?:templates|data)\.package)/],
];
const stageOf = (operation) => STAGE_OPERATIONS.find(([, pattern]) => pattern.test(operation || ''))?.[0] || null;
function workbenchUrl(params, workspacePath) {
  const query = new URLSearchParams(params);
  if (workspacePath) query.set('workspace_path', workspacePath);
  return 'api/benchforge/workbench?' + query;
}

const taskTemplates = await readTaskTemplates();
const {publicPlan, publicReport} = createPublicArtifactProjector({pick, taskTemplates});
const {readDataset, readMedia, mediaReferences} = createDatasetReader({exists, readJson, pick, publicFields: PUBLIC_FIELDS});
const {sceneLibrary, sceneArtifacts, sceneMedia, scheduleSceneMovies, associatedCaptures} =
  createSceneQueries({workbenchUrl, pipelineSceneIds});
const dispatchWorkbenchRead = createWorkbenchReadRoutes({discover: (...args) => discover(...args),
  productionProgress: (...args) => productionProgress(...args), readRun: (...args) => readRun(...args),
  sceneArtifacts: (...args) => sceneArtifacts(...args), sceneMedia: (...args) => sceneMedia(...args), readDataset, readMedia});

async function deliveryScenePreviews(root, dataset, previews, scope, itemCount = Number.MAX_SAFE_INTEGER) {
  if (typeof dataset !== 'string' || !Array.isArray(previews)) return [];
  if (!Number.isSafeInteger(itemCount) || itemCount < 1) return [];
  const directory = await inside(root, dataset);
  await assertSessionDirectory(root, directory, scope);
  const targets = previews.slice(0, 3).filter((row) => Number.isSafeInteger(row.row_index) &&
    row.row_index >= 0 && row.row_index < itemCount && Number.isSafeInteger(row.media_index) && row.media_index >= 0);
  if (!targets.length) return [];
  const wanted = new Set(targets.map((row) => row.row_index)), rows = new Map();
  const stream = createReadStream(path.join(directory, 'questions.jsonl'), {encoding: 'utf8'});
  const lines = createInterface({input: stream, crlfDelay: Infinity});
  let index = 0;
  try {
    for await (const line of lines) {
      if (!line.trim()) continue;
      if (wanted.has(index)) rows.set(index, JSON.parse(line));
      if (++index > Math.max(...wanted)) break;
    }
  } finally {lines.close(); stream.destroy();}
  const datasetId = token(root, path.relative(root.path, directory));
  return targets.flatMap((row) => {
    const item = rows.get(row.row_index);
    const url = item && mediaReferences(item, datasetId, row.row_index, root.path, scope)[row.media_index];
    return url ? [{title: String(row.title || '场景'), url: '/' + url}] : [];
  });
}

async function runProducts(id, root, directory, state, plan, scope) {
  const items = [], saved = publicPlan(plan);
  const link = (product, step = '') => workbenchUrl({view: 'run_product', run: id, product, step, ...scopeParams(scope)}, root.path);
  if (saved) {
    items.push({stage: 'S1', title: '评测计划', kind: 'json', data: saved, url: link('plan')});
    items.push({stage: 'S4', title: '评测配置', kind: 'json',
      data: {pipeline_id: saved.pipeline_id, inputs: saved.inputs, selections: saved.selections,
        template_contracts: saved.template_contracts}, url: link('config')});
  }
  for (const [stepId, step] of Object.entries(state.steps || {})) {
    const result = step.result || {};
    const receipt = result.delivery_receipt || result.summary;
    const hasDeliveryReceipt = receipt && ['quantity_contract', 'target_items', 'target_reached', 'delivery_satisfied', 'delivery_status']
      .some((key) => key in receipt);
    const candidates = [
      ...(hasDeliveryReceipt ? [{report: receipt, file: 'release/complete.json'}] : []),
      {file: path.join(directory, 'release', 'collection_report.json')},
      {file: path.join(directory, 'release', 'complete.json')},
      ...[result.report, result.quality_report,
        typeof result.dataset === 'string' ? path.join(result.dataset, 'quality_report.json') : null]
        .map((file) => ({file})),
    ];
    for (const candidate of candidates) {
      if (!candidate.report && (typeof candidate.file !== 'string' || !candidate.file.endsWith('.json'))) continue;
      try {
        const file = candidate.report ? '' : await inside(root, path.resolve(directory, candidate.file));
        const report = candidate.report || await readJson(file);
        if (!report || typeof report !== 'object') continue;
        const delivery = candidate.file?.includes('release') || path.basename(file) === 'delivery_report.json';
        const data = publicReport(report);
        if (delivery && report.scene_previews) data.scene_previews = await deliveryScenePreviews(root, result.dataset, report.scene_previews, scope, report.accepted ?? report.total);
        items.push({stage: 'S5', title: delivery ? '数据生产与质检报告' : path.basename(file) === 'quality_report.json' ? '数据质量报告' : '评测报告',
          ...(delivery ? {file: 'release/collection_report.json'} : {}),
          kind: 'json', step_id: stepId, artifact_id: step.artifact?.artifact_id,
          data, url: link('report', stepId)});
        break;
      } catch (error) { if (!['ENOENT'].includes(error.code) && !(error instanceof ApiError)) throw error; }
    }
  }
  return items;
}

// Frequent reads use only bounded index rows and small state files, never scan datasets/manifests.
async function productionProgress(roots, config, url, signal) {
  const operations = [], pipelines = [], sources = [], remoteIds = new Set();
  for (const id of config._captureIds || []) remoteIds.add(id);
  let unassociatedRecords = 0;
  const scope = scopeOf(url, config._sessionIds);
  const seen = new Set();
  for (const root of roots) {
    const database = path.join(root.path, 'runs.sqlite');
    if (!await exists(database)) {sources.push({workspace: root.title, status: 'no_index'}); continue;}
    let db, rows;
    try {
      db = new DatabaseSync(database, {readOnly: true});
      rows = db.prepare('SELECT id,tool,state,artifact,error FROM operations ORDER BY rowid DESC LIMIT ?').all(config.maxRuns);
    } catch (error) {sources.push({workspace: root.title, status: 'index_error', error: error.message}); continue;}
    finally {db?.close();}
    sources.push({workspace: root.title, status: 'indexed', limit: config.maxRuns});
    for (const row of rows) {
      signal?.throwIfAborted();
      try {
        const directory = await inside(root, row.artifact);
        const request = await readJson(path.join(directory, 'request.json')) || {};
        if (!matchesSession(request.context, scope)) { if (!request.context?.session_id) unassociatedRecords++; continue; }
        operations.push({...pick(row, ['id', 'tool', 'state', 'error']), stage: stageOf(row.tool),
          workspace: root.title, session_id: request.context?.session_id, started_at: request.time || null});
        if (!['pipeline_run', 'pipeline_status', 'pipeline_artifacts', 'pipeline_repair_plan'].includes(row.tool)) continue;
        const result = await readJson(path.join(directory, 'result.json')) || {};
        const requested = request.arguments?.run || result.run || path.join(directory, 'pipeline_run');
        if (!await exists(path.resolve(root.path, requested, 'state.json'))) continue;
        const folder = await inside(root, requested), id = token(root, path.relative(root.path, folder));
        if (!scope.history) {
          try { await assertSessionDirectory(root, folder, scope); }
          catch (error) { if (error.status === 403) continue; throw error; }
        }
        if (seen.has(id)) continue;
        seen.add(id);
        const state = await readJson(path.join(folder, 'state.json'));
        const plan = await readJson(path.join(folder, 'plan.json'));
        const planned = plan?.steps || [];
        const steps = planned.map((step) => {
          const actual = state.steps?.[step.id];
          if (actual?.result?.run_id?.startsWith('sf_')) remoteIds.add(actual.result.run_id);
          const captureWait = ['benchforge.observe', 'spatialforge.observe'].includes(step.uses) && step.await_terminal && planned.some((producer) =>
            ['benchforge.capture', 'spatialforge.capture'].includes(producer.uses) && step.arguments?.run_id === '$' + producer.id + '.run_id');
          return {id: step.id, uses: step.uses,
            stage: ['S1','S2','S3','S4','S5'].includes(step.review_stage) ? step.review_stage : captureWait ? 'S2' : stageOf(step.uses),
            state: actual?.state || 'unknown',
            error: actual?.error || null};
        });
        const completed = steps.filter((step) => step.state === 'completed').length;
        // The runner persists results after a step; an unrecorded step is not a measured execution.
        const current = steps.find((step) => step.id === state.step) || steps.find((step) => step.state !== 'completed');
        pipelines.push({id, label: path.relative(root.path, folder).split(path.sep).join('/'),
          session_id: request.context?.session_id,
          state: state.state, completed, total: plan ? planned.length : null, current,
          next: state.next, missing_binding: state.missing_binding, steps,
          updated_at: (await fs.stat(path.join(folder, 'state.json'))).mtime.toISOString()});
      } catch (error) {
        if (error.name === 'AbortError') throw error;
        sources.push({workspace: root.title, operation_id: row.id, status: 'record_error', error: error.message});
      }
    }
  }
  let scenes = {status: 'not_configured', runs: []};
  const session = url.searchParams.get('session_id') || '';
  if (config.productionConfig && roots.length && /^session-[a-zA-Z0-9-]+$/.test(session)) {
    try {
      const helper = 'pipelines.benchmark.progress.production_observer';
      const {stdout} = await execute(config.productionPython, ['-B', '-m',helper, '--config', config.productionConfig,
        '--session', session, '--sessions', JSON.stringify(config._sessionIds || []),
        '--workspace', roots[0].path,
        '--run-ids', JSON.stringify([...remoteIds].slice(0, 12))],
      {signal, timeout: 12000, maxBuffer: 2 * 1024 * 1024});
      scenes = JSON.parse(stdout);
      const removed=new Set();
      for(const root of roots) {
        const policy=await readJson(path.join(root.path,'scene-library','policy.json'));
        if(policy?.enabled)for(const id of policy.excluded_tasks || [])removed.add(id);
      }
      scenes.runs=(scenes.runs || []).map(row=>({...row,tasks:(row.tasks || []).filter(task=>!removed.has(task.id))})).filter(row=>row.tasks.length);
      scheduleSceneMovies(config, session, scenes.runs || [], [...remoteIds].slice(0, 12));
    } catch (error) {
      if (signal?.aborted) throw error;
      scenes = {status: 'unavailable', error: 'Production observer could not read the service (' + (error.code || error.name) + ')', runs: []};
    }
  }
  const preparation = new Map();
  for (const root of roots) {
    const drafts = await config._preparation.read(root, session, config._family || [], signal);
    for (const [childId, draft] of drafts) preparation.set(childId, {root, ...draft});
  }
  const parallel_tasks = (config._family || []).map((child, index) => {
    const owned = operations.filter((row) => row.session_id === child.id);
    const saved = pipelines.filter((row) => row.session_id === child.id);
    const draft = preparation.get(child.id);
    const public_artifacts = [...(draft?.files || []).map((file) => ({
      title: file.title, kind: 'preparation', accepted: false, revision: file.revision,
      url: workbenchUrl({view: 'run_product', product: 'preparation', batch_key: draft.batchKey,
        child_id: child.id, file: file.file, session_id: session}, draft.root.path),
    })), ...saved.filter((row) => row.completed > 0).map((row) => ({
      title: (child.label || '子任务') + '计划', url: workbenchUrl({view: 'run_product', product: 'plan', run: row.id, session_id: session}, roots[0]?.path),
      revision: row.steps.filter((step) => step.state === 'completed').map((step) => step.id).join(','),
    }))];
    return {id: child.id, display_name: child.label || '子任务 ' + (index + 1), state: child.state || 'unknown',
      stage: owned.find((row) => row.stage)?.stage || (/标注|annotation/i.test(child.label || '') ? 'S3' :
        /题目|question/i.test(child.label || '') ? 'S4' : /场景|scene/i.test(child.label || '') ? 'S2' : null),
      artifact_count: public_artifacts.length, public_artifacts,
      ...(draft ? {preparation: {status: 'preparing', accepted: false, artifact_count: draft.files.length,
        reasoningSelection: draft.reasoningSelection}} : {})};
  });
  const {current_collection = null, generation = null, ...observedScenes} = scenes;
  return {operations, pipelines, scenes: observedScenes, current_collection, generation, parallel_tasks, sources, snapshot_at: new Date().toISOString(),
    scope: scope.history ? 'explicit_workspace_history' : 'current_conversation_only',
    association: scope.session_id ? config._sessionIds?.length ? 'parent_and_verified_child_context' : 'exact_session_context' : 'no_session',
    unassociated_records: unassociatedRecords};
}

function integer(value, fallback, maximum) {
  if (value === null) return fallback;
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1 || number > maximum) throw new ApiError('Invalid pagination');
  return number;
}

async function templateCatalog(url, catalog) {
  const query = (url.searchParams.get('q') || '').trim().toLocaleLowerCase();
  const capability = url.searchParams.get('capability') || '';
  const page = integer(url.searchParams.get('page'), 1, 1000000);
  const size = integer(url.searchParams.get('page_size'), 12, 48);
  const templates = catalog.tasks.flatMap((task) => task.templates.map((template) => ({
    ...pick(template, ['id', 'task_id', 'title', 'prompt_template', 'measurement_variant', 'output_kind',
      'effective_measurement_conditions', 'status']),
    task_name: task.name, family: task.family,
    capabilities: task.catalog_capability_links.map((node) => node.id),
  })));
  const filtered = templates.filter((row) => (!capability || row.capabilities.includes(capability)) &&
    (!query || [row.id, row.title, row.task_name, row.family, ...row.capabilities].join(' ').toLocaleLowerCase().includes(query)));
  return {source: catalog.meta.version, task_count: catalog.tasks.length, template_count: templates.length,
    capabilities: [...new Set(templates.flatMap((row) => row.capabilities))].sort(),
    total: filtered.length, page, pages: Math.max(1, Math.ceil(filtered.length / size)),
    items: filtered.slice((page - 1) * size, page * size), execution_status: 'catalog_design; check adapters before production'};
}

async function* jsonLines(file, signal) {
  const stream = createReadStream(file, {encoding: 'utf8', signal});
  const lines = createInterface({input: stream, crlfDelay: Infinity});
  let index = 0;
  try {
    for await (const line of lines) {
      signal?.throwIfAborted();
      if (line.trim()) yield {row: JSON.parse(line), index: index++};
    }
  } finally { lines.close(); stream.destroy(); }
}
async function manifest(directory, limit, signal) {
  const file = path.join(directory, 'artifacts.jsonl');
  if (!await exists(file)) return {artifacts: [], counts: null, total: null, truncated: false};
  const byStatus = counts(), artifacts = [];
  let total = 0;
  for await (const {row} of jsonLines(file, signal)) {
    total++;
    if (row.status in byStatus) byStatus[row.status]++;
    if (limit) { artifacts.push(row); if (artifacts.length > limit) artifacts.shift(); }
  }
  return {artifacts, counts: byStatus, total, truncated: total > limit};
}
async function tailJsonl(file, limit, signal) {
  if (!await exists(file)) return {rows: [], total: 0};
  const rows = [];
  let total = 0;
  for await (const {row} of jsonLines(file, signal)) {
    total++; rows.push(row); if (rows.length > limit) rows.shift();
  }
  return {rows, total};
}

async function discover(roots, config, signal, scope) {
  const runs = new Map(), datasets = new Map(), sources = [];
  let latestPlan = null, planSource = null;
  let unassociatedRecords = 0;
  const addDataset = async (root, directory, producer, runId) => {
    if (!directory) return;
    const policy=await readJson(path.join(root.path,'scene-library','policy.json'));
    if(policy?.enabled && (policy.excluded_paths || []).some(folder=>directory===folder || directory.startsWith(folder+path.sep)))return;
    const resolved = await inside(root, directory);
    let questionFile = path.join(resolved, 'questions.jsonl');
    if (!await exists(questionFile)) questionFile = path.join(resolved, 'public', 'items.jsonl');
    if (!await exists(questionFile)) return;
    const id = token(root, path.relative(root.path, resolved));
    const report = await readJson(path.join(resolved, 'quality_report.json'));
    datasets.set(id, {id, workspace: root.title, workspace_id: root.id, name: path.basename(resolved),
      version: path.relative(root.path, resolved).split(path.sep).join('/'), producer, run_id: runId || null,
      report: report ? pick(report, QUALITY_FIELDS) : null, public_format: path.basename(questionFile),
      state: 'unassessed', updated_at: (await fs.stat(questionFile)).mtime.toISOString()});
  };
  for (const root of roots) {
    signal?.throwIfAborted();
    const database = path.join(root.path, 'runs.sqlite');
    if (!await exists(database)) { sources.push({workspace: root.title, status: 'no_index'}); continue; }
    let db, operations;
    try {
      db = new DatabaseSync(database, {readOnly: true});
      operations = db.prepare("SELECT id,tool,state,artifact,error FROM operations WHERE tool IN ('pipeline_plan','plan','pipeline_run','pipeline_status','pipeline_artifacts','pipeline_repair_plan','build') ORDER BY rowid DESC LIMIT ?").all(config.maxRuns + 1);
    } catch (error) {
      sources.push({workspace: root.title, status: 'index_error', error: error.message}); continue;
    } finally { db?.close(); }
    sources.push({workspace: root.title, status: 'indexed', limit: config.maxRuns, truncated: operations.length > config.maxRuns});
    for (const operation of operations.slice(0, config.maxRuns)) {
      try {
        const artifact = await inside(root, operation.artifact);
        const request = await readJson(path.join(artifact, 'request.json')) || {};
        if (!matchesSession(request.context, scope)) { if (!request.context?.session_id) unassociatedRecords++; continue; }
        const result = await readJson(path.join(artifact, 'result.json')) || {};
        if (['pipeline_plan', 'plan'].includes(operation.tool)) {
          if (operation.state === 'completed' && !latestPlan?.assessment) {
            const declared = operation.tool === 'pipeline_plan' ? result.plan : result.brief;
            const file = typeof declared === 'string' ? await inside(root, declared) : null;
            const saved = file ? await readJson(file) : null;
            if (saved) {
              const candidate = operation.tool === 'pipeline_plan' ? publicPlan(saved) :
                {objective: saved.objective || '', inputs: pick(saved, ['target_items']),
                  sources: saved.sources || [], notes: saved.notes || '', source: 'saved_benchmark_brief'};
              if (!latestPlan || candidate.assessment && !latestPlan.assessment || !latestPlan.assessment && !latestPlan.selections?.some((row) => row.template_ids?.length) &&
                  candidate.selections?.some((row) => row.template_ids?.length)) {
                latestPlan = candidate;
                planSource = {operation_id: operation.id, tool: operation.tool,
                  plan_path: file,
                  updated_at: (await fs.stat(file)).mtime.toISOString()};
              }
            }
          }
          continue;
        }
        if (operation.tool === 'build') {
          await addDataset(root, artifact, operation.id, null); continue;
        }
        const requested = request.arguments?.run || result.run || path.join(artifact, 'pipeline_run');
        if (!await exists(path.resolve(root.path, requested, 'state.json'))) continue;
        const directory = await inside(root, requested);
        if (!scope.history) {
          try { await assertSessionDirectory(root, directory, scope); }
          catch (error) { if (error.status === 403) continue; throw error; }
        }
        const id = token(root, path.relative(root.path, directory));
        if (runs.has(id)) continue;
        const state = await readJson(path.join(directory, 'state.json'));
        const record = await manifest(directory, 0, signal);
        runs.set(id, {id, label: path.relative(root.path, directory).split(path.sep).join('/'), workspace: root.title,
          workspace_id: root.id, operation_id: operation.id, state: state.state,
          steps: Object.keys(state.steps || {}).length, artifact_counts: record.counts,
          artifact_total: record.total, updated_at: (await fs.stat(path.join(directory, 'state.json'))).mtime.toISOString()});
        for (const [stepId, step] of Object.entries(state.steps || {})) {
          await addDataset(root, step.result?.dataset, stepId, id);
          // Nested runs are explicit persisted references, not filesystem scans.
          if (step.result?.steps) for (const [childId, child] of Object.entries(step.result.steps)) {
            await addDataset(root, child.result?.dataset, stepId + '/' + childId, id);
          }
        }
      } catch (error) {
        if (error.name === 'AbortError') throw error;
        sources.push({workspace: root.title, operation_id: operation.id, status: 'record_error', error: error.message});
      }
    }
  }
  const byStatus = counts();
  let manifests = 0;
  for (const run of runs.values()) if (run.artifact_counts) {
    manifests++; for (const key of STATUSES) byStatus[key] += run.artifact_counts[key];
  }
  return {runs: [...runs.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    datasets: [...datasets.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    plan: latestPlan, plan_source: planSource,
    counts: manifests ? byStatus : null, manifest_runs: manifests, sources,
    scope: scope.history ? 'explicit_workspace_history' : 'current_conversation_only',
    association: scope.session_id ? 'exact_session_context' : 'no_session', unassociated_records: unassociatedRecords,
    snapshot_at: new Date().toISOString()};
}

async function readRun(id, roots, config, signal, scope) {
  const {root, directory} = await resolveToken(id, roots);
  await assertSessionDirectory(root, directory, scope);
  const state = await readJson(path.join(directory, 'state.json'));
  if (!state) throw new ApiError('Pipeline state was not found', 404);
  const [artifacts, repairs, plan] = await Promise.all([
    manifest(directory, config.maxArtifacts, signal),
    tailJsonl(path.join(directory, 'repair-plans.jsonl'), config.maxArtifacts, signal),
    readJson(path.join(directory, 'plan.json')),
  ]);
  return {id, label: path.relative(root.path, directory).split(path.sep).join('/'), workspace: root.title,
    state: pick(state, ['state', 'run_id', 'next', 'missing_binding', 'step']),
    steps: Object.entries(state.steps || {}).map(([key, value]) => ({id: key, state: value.state,
      error: value.error, artifact_id: value.artifact?.artifact_id})),
    plan: publicPlan(plan), scene_ids: pipelineSceneIds(state), stage_artifacts: await runProducts(id, root, directory, state, plan, scope),
    plan_source: plan ? {plan_path: path.join(directory, 'plan.json'), run_id: id} : null,
    artifacts: artifacts.artifacts, artifact_total: artifacts.total, artifact_counts: artifacts.counts,
    artifacts_truncated: artifacts.truncated, repairs: repairs.rows, repair_total: repairs.total};
}

function pipelineSceneIds(state) {
  const ids = new Set();
  const collect = (result) => {
    if (!result || ids.size >= 12) return;
    if (typeof result.run_id === 'string' && /^sf_[a-zA-Z0-9_-]+$/.test(result.run_id)) ids.add(result.run_id);
    for (const step of Object.values(result.steps || {})) collect(step.result);
  };
  for (const step of Object.values(state?.steps || {})) collect(step.result);
  return [...ids];
}

function createWorkbenchDispatcher(config, registered, family, synthesisFactory, execution, associations) {
  const limits = {maxRuns: 60, maxArtifacts: 300, productionPython:process.env.PYTHON || (process.platform==='win32' ? 'python' : 'python3'), ...config};
  limits._previewJobs = new Map(); limits._previewQueue = Promise.resolve(); limits._previewMedia = new Map();
  limits._libraryCache = new Map(); limits._libraryQueue = new Map();
  limits._preparation = createPreparationProducts({validatePlan: async (root, planPath, parentId) => {
    const file = await inside(root, planPath);
    await assertSessionDirectory(root, path.dirname(file), {session_id: parentId, session_ids: [], history: false});
    return file;
  }});
  return async (url, request) => {
    const view = url.searchParams.get('view') || 'summary';
    if (view === 'runtime') return {ui_revision: limits.uiRevision || '',
      preset_id: 'benchforge', preset_name: 'BenchForge'};
    const roots = await workspaceRoots(limits, registered(), url.searchParams.get('workspace_path') || '');
    const parentScope = scopeOf(url);
    const related = !view.startsWith('execution_') && !parentScope.history && /^session-[a-zA-Z0-9-]+$/.test(parentScope.session_id)
      ? await family(parentScope.session_id, request.signal) : [];
    const sessions = related.map((row) => row.id);
    const scope = scopeOf(url, sessions), scoped = {...limits, _sessionIds: sessions, _family: related};
    if (view === 'progress' || view === 'stage_artifacts' || view === 'stage_media')
      scoped._captureIds = await associatedCaptures(roots, scope, associations);
    let value;
    if (view === 'execution_status' || view === 'execution_control') {
      if(roots.length !== 1 || !scope.session_id || scope.history || !execution)
        throw new ApiError('Execution adjustment requires the current workspace and production parent',400);
      if(request.headers.get('sec-fetch-site') === 'cross-site')throw new ApiError('Cross-site execution control is not allowed',403);
      if(view === 'execution_status') {
        if(request.method !== 'GET')throw new ApiError('Execution status requires GET',405);
        value=await execution.observe(roots[0].path,scope.session_id);
      } else {
        if(request.method !== 'POST')throw new ApiError('Execution adjustment requires POST',405);
        const body=await request.text();
        if(body.length>2048)throw new ApiError('Execution adjustment is too large',413);
        let tuning;
        try {tuning=JSON.parse(body);}catch {throw new ApiError('Invalid execution adjustment JSON');}
        if(!tuning || typeof tuning!=='object' || Array.isArray(tuning) || Object.keys(tuning).some(key=>!['reasoning_effort','compact_history'].includes(key)) ||
          tuning.compact_history!==undefined && typeof tuning.compact_history!=='boolean')throw new ApiError('Invalid execution adjustment');
        value=await execution.arm(roots[0].path,scope.session_id,tuning,request.signal);
      }
    }
    else if (view === 'synthesis_start' || view === 'synthesis_status') {
      if (roots.length !== 1 || !scope.session_id || scope.history)
        throw new ApiError('Preparation requires the current workspace and parent conversation',400);
      if (request.headers.get('sec-fetch-site') === 'cross-site')
        throw new ApiError('Cross-site preparation is not allowed',403);
      if (!synthesisFactory) throw new ApiError('Native preparation service is unavailable',503);
      const controller=synthesisFactory(roots[0].path);
      if (view === 'synthesis_status') {
        if (request.method !== 'GET') throw new ApiError('Preparation status requires GET',405);
        value=await controller.read({parentId:scope.session_id,batchKey:url.searchParams.get('batch_key')});
      } else {
        if (request.method !== 'POST') throw new ApiError('Preparation startup requires POST',405);
        const body=await request.text();
        if (body.length > 512000) throw new ApiError('Preparation request is too large',413);
        let preparation;
        try {preparation=JSON.parse(body);} catch {throw new ApiError('Invalid preparation JSON');}
        if (!preparation || typeof preparation.plan_path !== 'string')
          throw new ApiError('Preparation needs the saved parent plan');
        const file=await inside(roots[0],preparation.plan_path);
        await assertSessionDirectory(roots[0],path.dirname(file),parentScope);
        value=await controller.start({parentId:scope.session_id,batchKey:preparation.batch_key,
          planPath:file,tasks:preparation.tasks},request.signal);
      }
      limits._preparation.remember(roots[0],scope.session_id,value);
    }
    else if (view === 'plan_edit') {
      if (request.method !== 'POST') throw new ApiError('Plan editing requires POST',405);
      if (roots.length !== 1 || !scope.session_id) throw new ApiError('A current workspace and conversation are required',400);
      if (request.headers.get('sec-fetch-site') === 'cross-site') throw new ApiError('Cross-site plan editing is not allowed',403);
      const body = await request.text();
      if (body.length > 512000) throw new ApiError('Plan edit is too large',413);
      let edit;
      try {edit=JSON.parse(body);} catch {throw new ApiError('Invalid plan edit JSON');}
      if (typeof edit?.plan_path !== 'string' ||
          !(typeof edit.markdown === 'string' && edit.markdown.trim() || edit.assessment && typeof edit.assessment === 'object'))
        throw new ApiError('A saved plan and complete edited Markdown document are required');
      const file=await inside(roots[0],edit.plan_path);
      await assertSessionDirectory(roots[0],path.dirname(file),parentScope);
      const helper='server.plan_edit_cli';
      const process=execute(limits.productionPython,['-B','-m',helper,'--workspace',roots[0].path,'--session',scope.session_id,'--plan',file],
        {signal:request.signal,timeout:20000,maxBuffer:256000});
      process.child.stdin.on('error',()=>{});
      process.child.stdin.end(JSON.stringify({assessment:edit.assessment,markdown:edit.markdown,
        base_markdown:edit.base_markdown,split:edit.split}));
      value=JSON.parse((await process).stdout);
      if (value.error) throw new ApiError(value.error,value.status_code || 400);
    }
    else if (view === 'stage_review') {
      if (roots.length !== 1 || !scope.session_id) throw new ApiError('A current workspace and conversation are required',400);
      if (request.headers.get('sec-fetch-site') === 'cross-site') throw new ApiError('Cross-site stage review is not allowed',403);
      const body = request.method === 'POST' ? await request.text() : '{}';
      if (body.length > 16000) throw new ApiError('Stage instruction is too large',413);
      const helper = 'server.stage_review_cli';
      const result = await execute(limits.productionPython,['-B','-m',helper,'--workspace',roots[0].path,'--session',scope.session_id,'--request',body],
        {signal:request.signal,timeout:12000,maxBuffer:128000});
      value = JSON.parse(result.stdout);
    }
    else if (request.method === 'POST') {
      if (view !== 'scene_selection') throw new ApiError('This workbench operation is read-only', 405);
      // DSH authorizes the connection before dispatch and constructs a virtual Request.
      // Its virtual origin is not the browser's origin; reject an explicit cross-site fetch instead.
      if (request.headers.get('sec-fetch-site') === 'cross-site') throw new ApiError('Cross-site scene selection is not allowed', 403);
      const body = await request.text();
      if (body.length > 128000) throw new ApiError('Scene selection is too large', 413);
      let selection;
      try {selection = JSON.parse(body);} catch {throw new ApiError('Invalid scene selection JSON');}
      if (!selection || typeof selection !== 'object' || Array.isArray(selection)) throw new ApiError('Invalid scene selection');
      value = await sceneLibrary(limits, roots, url, request.signal, selection);
    }
    else if (view === 'scene_library' || view === 'scene_selection') value = await sceneLibrary(limits, roots, url, request.signal);
    else if (view === 'catalog') value = await templateCatalog(url, taskTemplates);
    else if (view === 'plan_template') value = await readAssessmentTemplate();
    else if (view === 'run_product' && url.searchParams.get('product') === 'preparation') {
      if (roots.length !== 1 || !scope.session_id || scope.history)
        throw new ApiError('Preparation previews require the current workspace and parent conversation',400);
      return await limits._preparation.open(roots[0], scope.session_id, related, {
        batchKey: url.searchParams.get('batch_key'), childId: url.searchParams.get('child_id'), file: url.searchParams.get('file'),
      }, request.signal);
    }
    else if (['summary', 'progress', 'run', 'run_product', 'stage_artifacts', 'stage_media', 'dataset', 'media'].includes(view)) {
      const response = await dispatchWorkbenchRead({view, request, url, roots, limits, scoped, scope, sessions});
      if (response instanceof Response) return response;
      value = response;
    } else throw new ApiError('Unsupported workbench view');
    return value;
  };
}

function fetchWorkbench(dispatch) {
  return async (request) => {
    try {
      const value = await dispatch(new URL(request.url), request);
      return value instanceof Response ? value : Response.json(value, {headers: {'cache-control': 'no-store'}});
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      return Response.json({error: error.message}, {status: error.status || (error.code === 'ENOENT' ? 404 : 500), headers: {'cache-control': 'no-store'}});
    }
  };
}

export function createWorkbenchHandler(config, registered = () => [], family = async () => [], synthesisFactory, execution, associations) {
  return fetchWorkbench(createWorkbenchDispatcher(config, registered, family, synthesisFactory, execution, associations));
}

export function apply(ctx, config) {
  const {execution, preparation} = ctx.benchforgeSessions;
  const {associations} = ctx.benchforgeCapture;
  const dispatch = createWorkbenchDispatcher(config, () => ctx.workspaceRegistry.list(), sessionFamilyReader(ctx),
    preparation, execution, associations);
  ctx.provide('benchforgeWorkbench', new WorkbenchRemote(dispatch));
  // Local file overlays do not have a bare package row for the Typert loader.
  ctx.effect(() => ctx.typert.register(TYPERT), 'benchforge-workbench: Remote API');
  const dispose = ctx.connection.fetch.register({path: '/api/benchforge/workbench', methods: ['GET', 'POST'], requestBody: 'buffered',
    fetch: fetchWorkbench(dispatch)});
  ctx.effect(() => dispose, 'benchforge-ui: authenticated artifacts and scene selection API');
}

