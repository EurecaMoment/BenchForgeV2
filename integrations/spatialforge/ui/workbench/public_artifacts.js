import fs from 'node:fs/promises';
import path from 'node:path';
import {createReadStream} from 'node:fs';
import {createInterface} from 'node:readline';
import {Readable} from 'node:stream';
import {ApiError, assertSessionDirectory, inside, resolveToken, scopeOf, scopeParams, token} from './scope.js';

export const PUBLIC_FIELDS = ['item_id', 'id', 'task_id', 'template_id', 'protocol_id', 'protocol_version',
  'measurement_variant', 'primary_operation', 'catalog_capability_links', 'provided_information', 'scene_group_id', 'split',
  'question', 'question_presentation', 'choices', 'media', 'assets', 'output_schema', 'reference_frame', 'history_access_mode'];
export const QUALITY_FIELDS = ['requested', 'accepted', 'shortfall', 'per_template', 'requested_per_template', 'split',
  'requested_split', 'preserve_source_splits', 'per_partition', 'per_template_partitions', 'sft_split', 'sft_items',
  'training_bundle_eligible', 'public_asset_count', 'scene_groups', 'rejections', 'source', 'benchmark_approved',
  'capability_scope', 'state', 'quantity_contract', 'target_items', 'target_reached', 'delivery_satisfied', 'delivery_status'];
export const REPORT_FIELDS = [...QUALITY_FIELDS, 'model_api_calls', 'scope', 'metrics', 'total', 'count', 'success_rate',
  'missing', 'status', 'capabilities', 'limitations', 'body_markdown', 'public_verified_count', 'contract_eligible_count',
  'source_scene_count', 'captured_view_count'];

export function createPublicArtifactProjector({pick, taskTemplates}) {
  const planTemplateTitles = new Map((taskTemplates?.tasks || [])
    .flatMap((task) => task.templates.map((row) => [row.id, row.title])));
  const stripPrivate = (value, allowAuthoritySource = false) => Array.isArray(value) ? value.map((child) => stripPrivate(child)) :
    value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).filter(([key]) =>
      allowAuthoritySource && key === 'authority_source' || !/^(?:answers?|answer_?key|correct_?answer|reference_?answer|ground_?truth|gt|authority|gold|oracle|token|password|api_?key|solution)(?:_|$)/i.test(key))
      .map(([key, child]) => [key, stripPrivate(child)])) : value;

  function publicPlan(plan) {
    if (!plan) return null;
    const assessment = plan.assessment ? stripPrivate(plan.assessment, true) : undefined;
    const markdown = typeof plan.user_markdown === 'string' ? plan.user_markdown.replace(
      /^```assessment-yaml\s*\r?\n[\s\S]*?^```\s*$/gm,
      () => '```assessment-yaml\n' + JSON.stringify(assessment || {}, null, 2) + '\n```\n') : undefined;
    return {...pick(plan, ['pipeline_id', 'version', 'objective', 'edit_revision', 'applies_edit', 'user_markdown_path']),
      ...(markdown === undefined ? {} : {user_markdown: markdown}), assessment,
      selections: (plan.selections || []).map((row) => pick(row, ['template_ids', 'count', 'reason'])),
      inputs: pick(plan.inputs || {}, ['seed', 'split', 'preserve_source_splits', 'target_items']),
      template_contracts: (plan.template_contracts || []).map((row) => ({...pick(row, ['id', 'task_id', 'task_name',
        'protocol_id', 'parameters', 'effective_measurement_conditions', 'output_schema', 'catalog_capability_links', 'execution']),
      title: planTemplateTitles.get(row.id) || row.task_name})),
      steps: (plan.steps || []).map((step) => pick(step, ['id', 'uses', 'pipeline_id', 'artifact_type', 'await_terminal']))};
  }

  function publicReport(report) { return report ? stripPrivate(pick(report, REPORT_FIELDS)) : null; }
  return {publicPlan, publicReport};
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

async function datasetFiles(id, roots, scope, exists) {
  const {root, directory} = await resolveToken(id, roots);
  await assertSessionDirectory(root, directory, scope);
  let publicRoot = directory, questions = path.join(directory, 'questions.jsonl');
  if (!await exists(questions)) { publicRoot = path.join(directory, 'public'); questions = path.join(publicRoot, 'items.jsonl'); }
  if (!await exists(questions)) throw new ApiError('Public questions were not found', 404);
  await inside(root, questions);
  return {root, directory, publicRoot, questions};
}

export function createDatasetReader({exists, readJson, pick, publicFields = PUBLIC_FIELDS}) {
  function integer(value, fallback, maximum) {
    if (value === null) return fallback;
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 1 || number > maximum) throw new ApiError('Invalid pagination');
    return number;
  }
  const mediaTypes = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
    '.svg': 'image/svg+xml', '.gif': 'image/gif', '.json': 'application/json', '.md': 'text/markdown; charset=utf-8', '.npy': 'application/octet-stream'};
  function mediaReferences(row, id, index, workspacePath, scope, field = 'media') {
    return (Array.isArray(row[field]) ? row[field] : []).map((_, media) => {
      const params = new URLSearchParams({view: 'media', dataset: id, item: String(index),
        [field === 'assets' ? 'asset' : 'media']: String(media), ...scopeParams(scope)});
      if (workspacePath) params.set('workspace_path', workspacePath);
      return 'api/benchforge/workbench?' + params;
    });
  }
  async function readDataset(url, roots, signal, sessions = []) {
    const id = url.searchParams.get('dataset'), scope = scopeOf(url, sessions);
    const {directory, questions} = await datasetFiles(id, roots, scope, exists);
    const page = integer(url.searchParams.get('page'), 1, 1000000), pageSize = integer(url.searchParams.get('page_size'), 24, 96);
    const template = url.searchParams.get('template') || '', split = url.searchParams.get('split') || '';
    const query = (url.searchParams.get('q') || '').toLocaleLowerCase(), workspacePath = url.searchParams.get('workspace_path') || '';
    const items = [], templates = new Set(), splits = new Set();
    let total = 0, all = 0;
    for await (const {row, index} of jsonLines(questions, signal)) {
      all++;
      if (row.template_id) templates.add(row.template_id);
      if (row.split) splits.add(row.split);
      if (template && row.template_id !== template || split && row.split !== split) continue;
      if (query && ![row.item_id, row.id, row.question, row.task_id, row.template_id].some((value) => String(value || '').toLocaleLowerCase().includes(query))) continue;
      if (total >= (page - 1) * pageSize && items.length < pageSize) {
        const projected = pick(row, publicFields);
        if (projected.question_presentation) projected.question_presentation = pick(projected.question_presentation,
          ['schema', 'stem', 'context', 'conditions', 'options', 'response', 'media_labels']);
        items.push({...projected, row_index: index, media: mediaReferences(row, id, index, workspacePath, scope),
          assets: mediaReferences(row, id, index, workspacePath, scope, 'assets'),
          asset_names: (Array.isArray(row.assets) ? row.assets : []).map((reference) => typeof reference === 'string' ? path.basename(reference) : ''),
          media_types: (Array.isArray(row.media) ? row.media : []).map((reference) => typeof reference === 'string'
            ? mediaTypes[path.extname(reference).toLowerCase()] || 'application/octet-stream' : 'application/octet-stream')});
      }
      total++;
    }
    const report = await readJson(path.join(directory, 'quality_report.json'));
    return {id, items, total, all, page, page_size: pageSize, pages: Math.ceil(total / pageSize),
      facets: {templates: [...templates].sort(), splits: [...splits].sort()}, report: report ? pick(report, QUALITY_FIELDS) : null,
      authority_exposed: false};
  }

  async function readMedia(url, roots, signal, sessions = []) {
    const id = url.searchParams.get('dataset'), scope = scopeOf(url, sessions);
    const {root, publicRoot, questions} = await datasetFiles(id, roots, scope, exists);
    const field = url.searchParams.has('asset') ? 'assets' : 'media';
    if (url.searchParams.has('asset') && url.searchParams.has('media')) throw new ApiError('Invalid public file reference');
    const item = Number(url.searchParams.get('item')), media = Number(url.searchParams.get(field === 'assets' ? 'asset' : 'media'));
    if (![item, media].every((value) => Number.isSafeInteger(value) && value >= 0)) throw new ApiError('Invalid media reference');
    let reference;
    for await (const record of jsonLines(questions, signal)) if (record.index === item) { reference = record.row[field]?.[media]; break; }
    const prefix = field === 'assets' ? 'assets' : 'media';
    const declared = field === 'assets' ? /^assets[\\/]/ : /^media[\\/]/;
    if (typeof reference !== 'string' || !declared.test(reference)) throw new ApiError('Only declared public files can be read', 403);
    const file = await inside(root, path.resolve(publicRoot, reference));
    const mediaRoot = await fs.realpath(path.join(publicRoot, prefix)), relative = path.relative(mediaRoot, file);
    if (relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) throw new ApiError('Media escapes public media directory', 403);
    const type = mediaTypes[path.extname(file).toLowerCase()];
    if (!type) throw new ApiError('Preview supports declared public images and JSON only', 415);
    return new Response(await fs.readFile(file, {signal}), {headers: {'content-type': type, 'cache-control': 'private, max-age=60',
      'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox", 'x-content-type-options': 'nosniff'}});
  }
  return {readDataset, readMedia, mediaReferences};
}
