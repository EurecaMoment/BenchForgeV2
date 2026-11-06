import fs from 'node:fs/promises';
import path from 'node:path';

export function compactCaptureObservation(value) {
  return {run_id:value.run_id,state:value.state,terminal:value.terminal,
    ...(value.watch ? {watch:value.watch} : {}),
    tasks:value.tasks.map(task=>({id:task.id,state:task.state,phase:task.phase,revision:task.revision,
      next_action:task.next_action,
      ...(task.failure ? {failure:{stage:task.failure.stage,error:task.failure.error}} : {}),
      ...(task.quality ? {scene_quality_passed:task.quality.scene_quality_passed,issues:task.quality.feedback?.issues} : {})}))};
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
    return compactCaptureObservation(value);
  }
  const watch = async (args, exec) => {
    exec.signal?.throwIfAborted();
    const agent = exec.agent, owner = agent?.id || agent?.session?.id;
    if (!owner || !/^[A-Za-z0-9_-]+$/.test(owner) || !/^sf_[A-Za-z0-9_-]+$/.test(args.run_id))
      throw new Error('Background capture waiting requires the current session and a native run_id');
    const key = owner + ':' + args.run_id;
    if (pending.has(key)) return pending.get(key).receipt;
    const current = await read('/observe', {run_id: args.run_id}, exec.signal);
    if (current.terminal) return current;
    exec.signal?.throwIfAborted();
    const file = path.join(artifacts, 'capture-watches', owner, args.run_id + '.json');
    const record = {schema: 'spatialforge.capture-watch/v1', owner, run_id: args.run_id,
      state: 'watching', started_at: Date.now(), observation: brief(current)};
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
