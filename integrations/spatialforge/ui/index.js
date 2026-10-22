import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createInterface} from 'node:readline';
import {DatabaseSync} from 'node:sqlite';
import path from 'node:path';
import z from '@deepseek-ai/schemastery';

export const name = 'benchforge-spatialforge-ui';
export const inject = ['connection', 'workspaceRegistry'];
export const Config = z.object({
  workspacePaths: z.array(z.string()).default([]),
  maxRuns: z.natural().min(1).max(200).default(60),
  maxArtifacts: z.natural().min(1).max(1000).default(300),
});

const STATUSES = ['draft', 'candidate', 'verified', 'rejected', 'superseded'];
const PUBLIC_FIELDS = ['item_id', 'id', 'task_id', 'template_id', 'protocol_id', 'protocol_version',
  'measurement_variant', 'primary_operation', 'catalog_capability_links', 'provided_information',
  'scene_group_id', 'split', 'question', 'choices', 'media', 'output_schema', 'reference_frame', 'history_access_mode'];
const QUALITY_FIELDS = ['requested', 'accepted', 'shortfall', 'per_template', 'requested_per_template',
  'split', 'scene_groups', 'rejections', 'source', 'benchmark_approved', 'capability_scope', 'state'];

class ApiError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}
const pick = (row, fields) => Object.fromEntries(fields.filter((key) => key in row).map((key) => [key, row[key]]));
const token = (root, relative) => Buffer.from(JSON.stringify([root.id, relative])).toString('base64url');
const counts = () => Object.fromEntries(STATUSES.map((key) => [key, 0]));

async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
async function exists(file) {
  try { await fs.access(file); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}
async function inside(root, file) {
  const resolved = await fs.realpath(path.resolve(root.path, file));
  const relative = path.relative(root.path, resolved);
  if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
    throw new ApiError('Path is outside the registered workspace', 403);
  }
  return resolved;
}
async function resolveToken(id, roots) {
  let parts;
  try { parts = JSON.parse(Buffer.from(id || '', 'base64url').toString()); }
  catch { throw new ApiError('Invalid record identity'); }
  if (!Array.isArray(parts) || parts.length !== 2 || parts.some((x) => typeof x !== 'string')) throw new ApiError('Invalid record identity');
  const root = roots.find((item) => item.id === parts[0]);
  if (!root) throw new ApiError('Workspace is no longer registered', 404);
  return {root, directory: await inside(root, parts[1])};
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

async function workspaceRoots(config, registered, requestedPath) {
  const roots = new Map();
  const inputs = [...registered, ...(config.workspacePaths || []).map((p) => ({id: 'path:' + p, path: p, title: path.basename(p)}))];
  for (const input of inputs) {
    try {
      const directory = await fs.realpath(input.path);
      if (!roots.has(directory)) roots.set(directory, {id: String(input.id), path: directory, title: input.title || path.basename(directory)});
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const values = [...roots.values()];
  if (!requestedPath) return [];
  let resolved;
  try { resolved = await fs.realpath(requestedPath); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  return values.filter((root) => root.path === resolved);
}

async function discover(roots, config, signal) {
  const runs = new Map(), datasets = new Map(), sources = [];
  const addDataset = async (root, directory, producer, runId) => {
    if (!directory) return;
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
      operations = db.prepare("SELECT id,tool,state,artifact,error FROM operations WHERE tool IN ('pipeline_run','pipeline_status','pipeline_artifacts','pipeline_repair_plan','build') ORDER BY rowid DESC LIMIT ?").all(config.maxRuns + 1);
    } catch (error) {
      sources.push({workspace: root.title, status: 'index_error', error: error.message}); continue;
    } finally { db?.close(); }
    sources.push({workspace: root.title, status: 'indexed', limit: config.maxRuns, truncated: operations.length > config.maxRuns});
    for (const operation of operations.slice(0, config.maxRuns)) {
      try {
        const artifact = await inside(root, operation.artifact);
        const request = await readJson(path.join(artifact, 'request.json')) || {};
        const result = await readJson(path.join(artifact, 'result.json')) || {};
        if (operation.tool === 'build') {
          await addDataset(root, artifact, operation.id, null); continue;
        }
        const requested = request.arguments?.run || result.run || path.join(artifact, 'pipeline_run');
        if (!await exists(path.resolve(root.path, requested, 'state.json'))) continue;
        const directory = await inside(root, requested);
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
    counts: manifests ? byStatus : null, manifest_runs: manifests, sources,
    scope: 'indexed_operations_only', snapshot_at: new Date().toISOString()};
}

async function readRun(id, roots, config, signal) {
  const {root, directory} = await resolveToken(id, roots);
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
    plan: plan ? {pipeline_id: plan.pipeline_id, version: plan.version, steps: (plan.steps || []).map((step) => pick(step, ['id', 'uses', 'pipeline_id', 'artifact_type', 'await_terminal']))} : null,
    artifacts: artifacts.artifacts, artifact_total: artifacts.total, artifact_counts: artifacts.counts,
    artifacts_truncated: artifacts.truncated, repairs: repairs.rows, repair_total: repairs.total};
}

async function datasetFiles(id, roots) {
  const {root, directory} = await resolveToken(id, roots);
  let publicRoot = directory, questions = path.join(directory, 'questions.jsonl');
  if (!await exists(questions)) { publicRoot = path.join(directory, 'public'); questions = path.join(publicRoot, 'items.jsonl'); }
  if (!await exists(questions)) throw new ApiError('Public questions were not found', 404);
  await inside(root, questions);
  return {root, directory, publicRoot, questions};
}
function integer(value, fallback, maximum) {
  if (value === null) return fallback;
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1 || number > maximum) throw new ApiError('Invalid pagination');
  return number;
}
function mediaReferences(row, id, index, workspacePath) {
  return (Array.isArray(row.media) ? row.media : []).map((_, media) => {
    const params = new URLSearchParams({view: 'media', dataset: id, item: String(index), media: String(media)});
    if (workspacePath) params.set('workspace_path', workspacePath);
    return 'api/benchforge/workbench?' + params;
  });
}
async function readDataset(url, roots, signal) {
  const id = url.searchParams.get('dataset');
  const {directory, questions} = await datasetFiles(id, roots);
  const page = integer(url.searchParams.get('page'), 1, 1000000);
  const pageSize = integer(url.searchParams.get('page_size'), 24, 96);
  const template = url.searchParams.get('template') || '', split = url.searchParams.get('split') || '';
  const query = (url.searchParams.get('q') || '').toLocaleLowerCase();
  const workspacePath = url.searchParams.get('workspace_path') || '';
  const items = [], templates = new Set(), splits = new Set();
  let total = 0, all = 0;
  for await (const {row, index} of jsonLines(questions, signal)) {
    all++;
    if (row.template_id) templates.add(row.template_id);
    if (row.split) splits.add(row.split);
    if (template && row.template_id !== template || split && row.split !== split) continue;
    if (query && ![row.item_id, row.id, row.question, row.task_id, row.template_id].some((value) => String(value || '').toLocaleLowerCase().includes(query))) continue;
    if (total >= (page - 1) * pageSize && items.length < pageSize) {
      items.push({...pick(row, PUBLIC_FIELDS), row_index: index, media: mediaReferences(row, id, index, workspacePath)});
    }
    total++;
  }
  const report = await readJson(path.join(directory, 'quality_report.json'));
  return {id, items, total, all, page, page_size: pageSize, pages: Math.ceil(total / pageSize),
    facets: {templates: [...templates].sort(), splits: [...splits].sort()}, report: report ? pick(report, QUALITY_FIELDS) : null,
    authority_exposed: false};
}
async function readMedia(url, roots, signal) {
  const id = url.searchParams.get('dataset');
  const {root, publicRoot, questions} = await datasetFiles(id, roots);
  const item = Number(url.searchParams.get('item')), media = Number(url.searchParams.get('media'));
  if (![item, media].every((v) => Number.isSafeInteger(v) && v >= 0)) throw new ApiError('Invalid media reference');
  let reference;
  for await (const record of jsonLines(questions, signal)) if (record.index === item) {
    reference = record.row.media?.[media]; break;
  }
  if (typeof reference !== 'string' || !/^media[\\/]/.test(reference)) throw new ApiError('Only declared public media can be read', 403);
  const file = await inside(root, path.resolve(publicRoot, reference));
  const mediaRoot = await fs.realpath(path.join(publicRoot, 'media'));
  const relative = path.relative(mediaRoot, file);
  if (relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) throw new ApiError('Media escapes public media directory', 403);
  const types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.gif': 'image/gif'};
  const type = types[path.extname(file).toLowerCase()];
  if (!type) throw new ApiError('Preview supports public images only', 415);
  return new Response(await fs.readFile(file, {signal}), {headers: {'content-type': type, 'cache-control': 'private, max-age=60',
    'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox", 'x-content-type-options': 'nosniff'}});
}

export function createWorkbenchHandler(config, registered = () => []) {
  const limits = {maxRuns: 60, maxArtifacts: 300, ...config};
  return async (request) => {
    try {
      const url = new URL(request.url), view = url.searchParams.get('view') || 'summary';
      const roots = await workspaceRoots(limits, registered(), url.searchParams.get('workspace_path') || '');
      let value;
      if (view === 'summary') value = await discover(roots, limits, request.signal);
      else if (view === 'run') value = await readRun(url.searchParams.get('run'), roots, limits, request.signal);
      else if (view === 'dataset') value = await readDataset(url, roots, request.signal);
      else if (view === 'media') return await readMedia(url, roots, request.signal);
      else throw new ApiError('Unsupported workbench view');
      return Response.json(value, {headers: {'cache-control': 'no-store'}});
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      return Response.json({error: error.message}, {status: error.status || (error.code === 'ENOENT' ? 404 : 500), headers: {'cache-control': 'no-store'}});
    }
  };
}
export function apply(ctx, config) {
  const dispose = ctx.connection.fetch.register({path: '/api/benchforge/workbench', methods: ['GET'], requestBody: 'buffered',
    fetch: createWorkbenchHandler(config, () => ctx.workspaceRegistry.list())});
  ctx.effect(() => dispose, 'benchforge-spatialforge-ui: authenticated read API');
}

