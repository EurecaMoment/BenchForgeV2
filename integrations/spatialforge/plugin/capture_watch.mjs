import fs from 'node:fs/promises';
import path from 'node:path';

export function captureRunId(value) {
  return typeof value==='string' ? (/^(sf_[A-Za-z0-9_-]+)\.scene\d+$/.exec(value)?.[1] || value) : value;
}

// Machine notices share a boundary batch while production is running. A newer
// result replaces its still-pending notice, so stale failures cannot queue turns
// after the same capture has already succeeded. Human input is untouched.
export function deliverCaptureNotice(agent, record, createMessage) {
  const message = createMessage({source: {kind: 'spatialforge/capture-watch'}, content: [{type: 'text', text:
    '采集终态通知（不是用户指令）：' + JSON.stringify(record.observation ? {...record, observation:compactCaptureObservation(record.observation)} : record) + '\n继续原任务；失败仍未完成，按真实失败阶段处理。'}]});
  const pending = [...(agent.inbox?.nextTurn || []), ...(agent.inbox?.nextStep || [])];
  const matches = [];
  for (const old of pending) {
    if (old.source?.kind !== 'spatialforge/capture-watch') continue;
    try {
      const text = old.content.filter(row => row.type === 'text').map(row => row.text).join('\n');
      const value = JSON.parse(text.slice(text.indexOf('{')).split('\n')[0]);
      if (value.run_id === record.run_id) {
        if (value.started_at > record.started_at) return;
        matches.push(old);
      }
    } catch {}
  }
  if (matches.length && typeof agent.inbox?.replace === 'function') {
    for (const old of matches.slice(1)) agent.inbox.remove(old.id);
    if (agent.inbox.replace(matches[0].id, message)) return;
  }
  if (agent.status === 'running' && typeof agent.inbox?.append === 'function') {
    agent.inbox.append('next-step', message);
  } else {
    if (typeof agent.followup !== 'function') throw new Error('Native parent followup is unavailable; read the saved watch receipt');
    agent.followup(message);
  }
}

function fields(value, names) {
  return Object.fromEntries(names.filter(name => value?.[name] !== undefined).map(name => [name, value[name]]));
}

// Keep diagnostics verbatim, including their object/view location. Narrative,
// inventories and saved plans are read through explicit detail/evidence tools.
function diagnostics(value, source) {
  const rows = [], diagnosticKeys = new Set(['error','errors','issues','repair_suggestions']);
  const documents = new Set(['intent','scene_brief','program','submitted_program','scene_program']);
  function visit(value, location) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) {value.forEach((item, index) => visit(item, location + '[' + index + ']'));return;}
    const row = {source:location};
    for (const [key, item] of Object.entries(value)) {
      if (diagnosticKeys.has(key) && item != null && item !== '' && (!Array.isArray(item) || item.length)) row[key] = item;
      // All false/unknown acceptance checks remain visible even when a larger
      // review wrapper carries a contradictory lifecycle success state.
      if (/(^|_)(passed|accepted|acceptable|valid|stable|renderable|allowed|approved|complete|assessed)$/.test(key) &&
          (item === false || item === null)) row[key] = item;
      if (key === 'failed' && item === true) row[key] = item;
    }
    if (Object.keys(row).length > 1) rows.push({...fields(value,['index','view','observation','reason','type']),...row});
    for (const [key, item] of Object.entries(value)) {
      if (!diagnosticKeys.has(key) && !documents.has(key)) visit(item, location + '.' + key);
    }
  }
  visit(value, source);
  return rows;
}

export function compactCaptureObservation(value, {artifacts} = {}) {
  const summary = fields(value, ['run_id','state','terminal','changed','waited_seconds','next_poll_seconds','gallery_url','watch','detail_available']);
  if (summary.terminal === undefined && ['SUCCEEDED','FAILED_FINAL','CANCELED'].includes(value.state)) summary.terminal = true;
  summary.detail_available ??= {tool:'spatialforge_status',...fields(value,['run_id']),detail:true};
  summary.tasks = (value.tasks || []).map(task => {
    const row = fields(task, ['id','state','phase','revision','workflow','tool','next_action','failure','queue','evidence',
      'summary','downloads','asset_files','design_reference_ready','records','diagnostics']);
    // Observe packages can have no unit at all. Assigning an absent optional
    // field creates undefined, which the native tool transport rejects before
    // the caller can see the otherwise valid task status.
    for (const key of ['phase','revision','workflow']) {
      if (row[key] == null && task.unit?.[key] !== undefined) row[key] = task.unit[key];
    }
    // Quality failures contain the same complete scene review in failure and
    // result. Keep failure identity and actions, project its known review
    // wrapper, and retain every diagnostic below. Full evidence stays on disk.
    if (task.failure?.scene_review) row.failure = {...task.failure,
      scene_review:fields(task.failure.scene_review,['passed','acceptable','assessed','status','issues','errors','repair_suggestions','publication_status'])};
    if (task.progress) {
      row.progress = fields(task.progress, ['stage','phase','state','status','percent','percentage','progress_percent',
        'completed','total','current','frames_done','frames_total','objects_done','objects_total','updated_ns',
        'age_seconds','elapsed_seconds','interrupted','scene_acceptance','error','errors','next_action']);
      if (row.progress.scene_acceptance && typeof row.progress.scene_acceptance === 'object') {
        row.progress.scene_acceptance = fields(row.progress.scene_acceptance, ['passed','accepted','allowed','status','source_path','error','errors','issues']);
      }
    }
    if (task.quality) {
      row.quality = fields(task.quality, ['scene_quality_passed','visual_realism','interaction_passed','interaction_status',
        'publication_status','data_export_complete','data_target_reached','collection_acceptance','human_approved','benchmark_approved']);
      if (task.quality.feedback) row.quality.feedback = fields(task.quality.feedback, ['file','issues','repair_suggestions']);
    }
    const result = task.result;
    const scene = !row.workflow || row.workflow === 'scene';
    if (result && scene) {
      row.result = fields(result, ['operation','directory','scene_quality_assessed','data_exported','source_path']);
      if (result.report) row.result.report = fields(result.report, ['status','frames','renderable','errors','source_path','available']);
      if (result.views) row.result.views = result.views.map(view => {
        const image = fields(view, ['frame_id','source_path','metadata_path','visible_objects']);
        if (view.camera) image.camera = fields(view.camera, ['position','target']);
        return image;
      });
      const problems = [...diagnostics(task.failure, 'failure'), ...diagnostics(task.progress, 'progress'), ...diagnostics(result.scene_review, 'result.scene_review'),
        ...diagnostics(result.report, 'result.report')];
      if (problems.length && !row.diagnostics) row.diagnostics = problems;
    } else {
      // Asset/layout/generation tools retain their operation-specific outputs.
      if (result !== undefined) row.result = result;
      if (task.design !== undefined) row.design = task.design;
      const problems = [...diagnostics(task.failure, 'failure'), ...diagnostics(task.progress, 'progress')];
      if (problems.length && !row.diagnostics) row.diagnostics = problems;
    }
    if (artifacts && /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(task.id || '') && Number.isInteger(row.revision) && row.revision >= 0) {
      const folder = path.join(artifacts, task.id, 'revision_' + row.revision);
      row.records = {...row.records, directory:folder};
      if (task.progress) row.records.progress_path = path.join(folder, 'progress.json');
      if (task.quality || result?.scene_review) row.records.scene_review_path = path.join(folder, 'scene_review.json');
      if (result?.report) row.records.capture_report_path = result.report.source_path || path.join(folder, 'capture','report.json');
      if (result?.views?.length) row.records.capture_program_path = path.join(folder, 'capture','program.json');
      if (task.summary) row.records.complete_path = path.join(folder, 'release','complete.json');
    }
    return row;
  });
  return summary;
}


// Waiting belongs to the tool runtime. Only a terminal result (or an actual
// observer failure) needs another model decision.
export function createCaptureWatcher({artifacts, read, notify, signal, budgetMs = 1800000}) {
  const pending = new Map();
  async function save(file, record) {
    await fs.mkdir(path.dirname(file), {recursive: true});
    const temporary = file + '.tmp';
    await fs.writeFile(temporary, JSON.stringify(record, null, 2), 'utf8');
    await fs.rename(temporary, file);
  }
  function brief(value) {
    return compactCaptureObservation(value, {artifacts});
  }
  const watch = async (args, exec) => {
    args={...args,run_id:captureRunId(args.run_id)};
    exec.signal?.throwIfAborted();
    const agent = exec.agent, owner = agent?.id || agent?.session?.id;
    if (!owner || !/^[A-Za-z0-9_-]+$/.test(owner) || !/^sf_[A-Za-z0-9_-]+$/.test(args.run_id))
      throw new Error('Background capture waiting requires the current session and a native run_id');
    const key = owner + ':' + args.run_id;
    if (pending.has(key)) return pending.get(key).receipt;
    const current = await read('/observe', {run_id: args.run_id}, exec.signal);
    if (current.terminal) return brief(current);
    exec.signal?.throwIfAborted();
    const file = path.join(artifacts, 'capture-watches', owner, args.run_id + '.json');
    const record = {schema: 'spatialforge.capture-watch/v1', owner, run_id: args.run_id,
      state: 'watching', started_at: Date.now(), receipt_path:file, observation: brief(current)};
    await save(file, record);
    const receipt = {...brief(current), watch: {background: true, accepted: true, receipt_path: file,
      instruction: 'Continue independent work or finish this turn. A terminal result wakes this session once; do not poll.'}};
    const entry = {receipt};
    pending.set(key, entry);
    entry.done = (async () => {
      let value = current;
      try {
        while (!value.terminal && Date.now() - record.started_at < budgetMs) {
          signal?.throwIfAborted();
          value = await read('/wait', {run_id: args.run_id, timeout_seconds: 60}, signal);
        }
        signal?.throwIfAborted();
        record.state = value.terminal ? 'terminal' : 'timeout';
        record.observation = brief(value);
      } catch (error) {
        record.state = signal?.aborted ? 'interrupted' : 'observer_failed';
        record.error = error.message || String(error);
      }
      record.finished_at = Date.now();
      await save(file, record);
      if (record.state !== 'interrupted') {
        await notify(agent, record);
        record.notified_at = Date.now();
        await save(file, record);
      }
    })().catch(async error => {
      record.state = 'notification_failed'; record.error = error.message || String(error);
      await save(file, record).catch(() => {});
    }).finally(() => pending.delete(key));
    return receipt;
  };
  watch.whenSettled = () => Promise.all([...pending.values()].map(entry => entry.done));
  return watch;
}
