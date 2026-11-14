import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {readChildCatalog} from '../../../dsh/host/session_family.mjs';

const queues = new Map();
const nativeIdleProbes = new WeakMap();
const NATIVE_ACTIVITY_PROBE_MS = 50;
const SCHEMA = 'benchforge.synthesis-sessions/v1';
const FACING_REFERENCE = fileURLToPath(new URL('../../../scene_production/resources/native_asset_facing.json', import.meta.url));
const FACING_HELPER = fileURLToPath(new URL('../../../scene_production/server/scene_program/geometry/native_asset_facing.py', import.meta.url));
const PERSONA = `You are a BenchForge preparation worker for one self-contained artifact assignment. Read the supplied frozen plan, contracts and relevant saved evidence. Write only inside the assigned output directory. Start file operations by changing to that directory and using explicit paths; preserve parent plans, scene selections, runner state, accepted artifacts and other workers' files.
At the start of file work, batch-copy the supplied source scripts or programs into your directory and save manifest.json with status preparing, the working artifact paths and known missing inputs. Use the supplied source paths instead of rediscovering the workspace or checking the whole production chain first. On recovery, preserve saved edits and continue the existing working copies. If a source is actually missing, record its exact path and continue the already determined scope; when no source was supplied, save the known design or script scaffold and preparing manifest first.
Apply the smallest concrete patch. Locate and batch-read only the functions or sections needed for it, then save known changes as you work. For scene design, persist the title, descriptive summary and program draft before investigating unresolved structure. If an exact input or required structure remains unknown, state the specific question or missing field in the manifest and hand off the completed scope; do not delay all saved preparation while trying to validate the entire production pipeline.
Keep verification proportional to the actual change and unresolved evidence. Do not add complex SHA checks or compute checksums for every input, PNG, output and receipt. Preserve supplied native identities and use necessary file size/mtime version bindings. Serialize JSON/JSONL directly with explicit UTF-8 writes; do not re-read every newly written record just to check serialization. Do not repeatedly scan directories, poll unchanged state or revalidate unrelated completed stages. Run only the checks needed for the patch and its source/production boundary; broaden checks when a concrete failure requires it.
Preparation is complete when the requested edits or design artifacts are saved, checks proportional to those changes have run, and an honest manifest reports artifact paths, actual checks, missing inputs and unresolved issues. A useful saved partial preparation can be handed off with its concrete blocker. Parent production acceptance is a later responsibility and must not prevent preparation drafts from being saved or delivered. Preserve hard requirements, exact measurement and public-question contracts, provenance, physics and everyday realism. Recognizable real assets are the default; geometry explicitly declared in the frozen plan remains valid in its scope. Predictions and references are not captured evidence or GT; record unaccepted or missing inputs without inventing results.
For scene facing and functional-layout work, use the calibrated native asset front axes in ${FACING_REFERENCE}; the dependency-free planning helper is ${FACING_HELPER}. It provides yaw_toward(kind, source_xy, target_xy) and world_forward(kind, yaw_deg). These references apply to their named source USD assets. Do not infer an asset's front from AABB dimensions or an earlier visual-review pass. Unknown assets have no implied axis. Keep their uncertainty explicit and obtain only the necessary shape evidence. Face monitors toward their operator, chairs toward their declared working target and conversation seats toward their declared conversation target; use the saved role relations, not a single assumed axis for all assets. The helper computes planned directions, not executed physics or acceptance; verify changed poses in subsequent native capture. Use Python with -B when reading the helper outside your assigned write directory.
The parent owns authoritative merging, capture, acceptance, export and each production stage's user window. Do not spawn more workers, create stage windows or bypass parent-owned tools through a shell, HTTP or task code. Question workers deliver S4 preparation or shards; the parent packages S5 after aggregate S4 acceptance. Update manifest.json to reflect the actual preparation outcome and quote its path in the final handoff. Preparation completion and accepted scene/data production are separate outcomes.`;

class SynthesisError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}
const inside = (root, value) => {
  const relative = path.relative(root, value);
  return relative === '' || relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
};
const nonempty = (value, field) => {
  if (typeof value !== 'string' || !value.trim()) throw new SynthesisError(`${field} must be non-empty text`);
  return value;
};
function fields(value, allowed, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new SynthesisError(`${name} must be an object`);
  const extra = Object.keys(value).filter(key => !allowed.includes(key));
  if (extra.length) throw new SynthesisError(`Unsupported ${name} fields: ${extra.join(', ')}`);
}
async function json(file) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
async function write(file, value) {
  const temporary = file + '.' + randomUUID() + '.tmp';
  try { await fs.writeFile(temporary, JSON.stringify(value, null, 2)); await fs.rename(temporary, file); }
  finally { await fs.unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}
async function directory(value, name) {
  let resolved;
  try { resolved = await fs.realpath(value); }
  catch (error) {
    if (error.code === 'ENOENT') throw new SynthesisError(`${name} must be an existing directory`);
    throw error;
  }
  if (!(await fs.stat(resolved)).isDirectory()) throw new SynthesisError(`${name} must be a directory`);
  return resolved;
}
async function existingFile(value, name) {
  let resolved;
  try { resolved = await fs.realpath(value); }
  catch (error) {
    if (error.code === 'ENOENT') throw new SynthesisError(`${name} must be an existing file`);
    throw error;
  }
  if (!(await fs.stat(resolved)).isFile()) throw new SynthesisError(`${name} must be a file`);
  return resolved;
}
async function recordDirectory(root) {
  let current = root;
  for (const name of ['.benchforge', 'synthesis-sessions']) {
    const next = path.join(current, name);
    try { await fs.mkdir(next); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    current = await directory(next, 'synthesis record directory');
    if (!inside(root, current)) throw new SynthesisError('Synthesis records must stay inside the workspace', 403);
  }
  return current;
}
function receipt(record, recordPath, reason) {
  const acceptedCount = record.tasks.filter(task => task.state === 'accepted').length;
  const failedCount = record.tasks.filter(task => task.state === 'failed').length;
  const pending = record.tasks.some(task => ['pending', 'starting'].includes(task.state));
  const errors = [...new Set(record.tasks.filter(task => task.error).map(task =>
    task.error.split('; known global tools:')[0]))];
  if (errors.length) reason = 'Preparation startup failed or is unconfirmed: ' + errors.join('; ');
  return {parentId: record.parentId, batchKey: record.batchKey, recordPath,
    ...(record.planPath ? {planPath: record.planPath} : {}),
    state: pending ? 'waiting' : failedCount ? acceptedCount ? 'partial_failure' : 'failed' : 'accepted',
    acceptedCount, failedCount, ...(reason ? {reason} : {}),
    ...(record.reasoningSelection ? {reasoningSelection: record.reasoningSelection} : {}),
    tasks: record.tasks.map(({prompt, ...task}) => task)};
}
async function serialized(key, operation) {
  const previous = queues.get(key) || Promise.resolve();
  const current = previous.catch(() => {}).then(operation);
  queues.set(key, current);
  try { return await current; }
  finally { if (queues.get(key) === current) queues.delete(key); }
}
async function lock(file) {
  let opened;
  try {
    const handle = opened = await fs.open(file, 'wx');
    await handle.writeFile(JSON.stringify({pid: process.pid}));
    return async () => { await handle.close(); await fs.unlink(file).catch(error => { if (error.code !== 'ENOENT') throw error; }); };
  } catch (error) {
    if (opened) {
      await opened.close();
      await fs.unlink(file).catch(remove => { if (remove.code !== 'ENOENT') throw remove; });
    }
    if (error.code !== 'EEXIST') throw error;
    const owner = await json(file);
    if (Number.isSafeInteger(owner?.pid)) {
      try { process.kill(owner.pid, 0); }
      catch (probe) {
        if (probe.code === 'ESRCH') {
          await fs.unlink(file).catch(remove => { if (remove.code !== 'ENOENT') throw remove; });
          return lock(file);
        }
      }
    }
    return null;
  }
}

function activityError(error) {
  return {name: error?.name || 'Error', message: error?.message || String(error),
    ...(error?.code !== undefined ? {code: error.code} : {})};
}

function nativeIdleProbe(agent) {
  const cached = nativeIdleProbes.get(agent);
  if (cached?.state === 'pending') return cached;
  const probe = {state: 'pending'};
  let finishRead;
  let timer;
  // Reads await this bounded promise, never the Agent's unbounded promise.
  // Once timed out, subsequent reads of a pending probe return immediately.
  probe.readReady = new Promise(resolve => {
    finishRead = () => { clearTimeout(timer); resolve(); };
    timer = setTimeout(resolve, NATIVE_ACTIVITY_PROBE_MS);
  });
  nativeIdleProbes.set(agent, probe);
  try {
    probe.idlePromise = agent.whenIdle();
    if (!probe.idlePromise || typeof probe.idlePromise.then !== 'function') {
      probe.state = 'unknown';
      probe.reason = 'Agent.whenIdle() did not return a promise';
      finishRead();
    } else {
      // Exactly one completion listener for an unfinished Agent probe. Readers
      // reuse readReady instead of racing or reattaching to idlePromise.
      Promise.resolve(probe.idlePromise).then(() => {
        probe.state = 'settled'; finishRead();
      }, error => {
        probe.state = 'error'; probe.error = activityError(error); finishRead();
      });
    }
  } catch (error) {
    probe.state = 'error'; probe.error = activityError(error); finishRead();
  }
  return probe;
}

/**
 * A trusted server adapter for native continuable spawn. The caller owns route
 * authentication and registered-workspace admission. Native spawn inherits the
 * parent's cwd; the assigned write directory is a worker policy, not an OS sandbox.
 */
export function createSynthesisSessions({ctx, workspacePath, batchSize = 3}) {
  if (!Number.isSafeInteger(batchSize) || batchSize < 1) throw new SynthesisError('batchSize must be a positive integer');
  const get = name => ctx.get(name);

  async function nativeActivity(agentId) {
    let agent;
    try {
      agent = get('agents')?.get(agentId);
      if (!agent) return {available: false, agentStatus: null, idleConfirmed: false, activityPending: null};
      const probe = typeof agent.whenIdle === 'function' ? nativeIdleProbe(agent) : undefined;
      if (probe) await probe.readReady;
      const agentStatus = typeof agent.status === 'string' ? agent.status : null;
      if (!probe || probe.state === 'unknown') return {available: true, agentStatus,
        idleConfirmed: false, activityPending: agentStatus === 'running' ? true : null,
        reason: probe?.reason || 'Agent.whenIdle() is unavailable; agentStatus alone cannot confirm idle'};
      if (probe.state === 'error') return {available: true, agentStatus, idleConfirmed: false,
        activityPending: agentStatus === 'running' ? true : null, error: probe.error};
      return {available: true, agentStatus,
        idleConfirmed: probe.state === 'settled' && agentStatus === 'idle',
        activityPending: probe.state === 'pending' || agentStatus === 'running'};
    } catch (error) {
      return {available: Boolean(agent), agentStatus: null, idleConfirmed: false,
        activityPending: null, error: activityError(error)};
    }
  }

  async function preparationReasoning(parent, signal) {
    const llm = parent.ctx?.get('llm') || get('llm');
    if (typeof llm?.resolveModelInfo !== 'function') throw new SynthesisError('The parent model capability registry is unavailable', 503);
    // The native delegation resolver inherits the latest request route, then
    // falls back to creation options before the parent's first request.
    const route = parent.session.requestHeader?.()?.config || parent.options;
    const provider = nonempty(route?.provider, 'parent provider'), model = nonempty(route?.model, 'parent model');
    const info = await llm.resolveModelInfo(provider, model, signal);
    const supportedEfforts = info.reasoning?.efforts?.map(effort => effort.id) || [];
    const preferredEffort = 'low';
    const selectedEffort = ['low', 'minimal', 'none', 'off', 'medium', 'high', 'xhigh']
      .find(effort => supportedEfforts.includes(effort)) || supportedEfforts[0];
    const selectionMode = selectedEffort ? 'explicit' : info.reasoning ? 'inherit' : 'not_applicable';
    return {provider, model, preferredEffort, selectionMode,
      ...(selectedEffort ? {selectedEffort} : {}), supportedEfforts,
      ...(info.reasoning?.defaultEffort ? {providerDefaultEffort: info.reasoning.defaultEffort} : {}),
      reason: !selectedEffort ? 'The model exposes no selectable reasoning effort; no reasoningEffort override is supplied.' :
        selectedEffort === preferredEffort ? 'The model supports the preferred preparation effort.' :
          !['minimal', 'none', 'off', 'medium', 'high', 'xhigh'].includes(selectedEffort)
            ? `The model exposes no supported preferred or lighter preparation level; its advertised ${selectedEffort} is selected explicitly.`
            : `The model does not support ${preferredEffort}; preparation uses supported ${selectedEffort}. Provider/model and parent effort are unchanged.`};
  }

  async function scope(parentId, requireAgent = true, signal) {
    nonempty(parentId, 'parentId');
    const parent = get('agents')?.get(parentId);
    if (requireAgent && (!parent || parent.id !== parentId || parent.session?.header?.id !== parentId)) {
      throw new SynthesisError('The current parent Agent is unavailable', 409);
    }
    const root = await directory(workspacePath, 'workspace');
    const parentHeader = parent?.session?.header || (await header(parentId, signal)).header;
    const cwd = await directory(nonempty(parentHeader?.cwd, 'parent cwd'), 'parent cwd');
    if (!inside(root, cwd)) throw new SynthesisError('The parent Agent belongs to another workspace', 403);
    const service = get('subagents');
    if (!service?.startActivation) throw new SynthesisError('Native subagent service is unavailable', 503);
    return {root, parent, service, dir: await recordDirectory(root)};
  }
  const fileOf = (dir, batchKey) => path.join(dir, 'batch-' + Buffer.from(nonempty(batchKey, 'batchKey'), 'utf8').toString('base64url') + '.json');

  async function header(childId, signal) {
    signal?.throwIfAborted();
    const live = get('sessions')?.get(childId);
    if (live) return {header: live.header, absent: false};
    const query = get('sessionQuery');
    if (!query?.observeSession) return {absent: false};
    try {
      const observed = await query.observeSession(childId, {signal, projectionMode: 'none'});
      try { return {header: observed.header, absent: false}; }
      finally { observed[Symbol.dispose](); }
    } catch (error) {
      if (signal?.aborted) throw error;
      return {absent: ['SESSION_QUERY_SESSION_NOT_FOUND', 'session/not-found'].includes(error.code)};
    }
  }
  async function reconcile(record, signal) {
    const uncertain = record.tasks.filter(task => ['starting', 'failed'].includes(task.state));
    if (!uncertain.length) return false;
    let changed = false;
    const catalog = await readChildCatalog(get('sessionQuery'), record.parentId, signal);
    for (const task of uncertain) {
      const entry = catalog.find(child => child.id === task.childId);
      const observed = await header(task.childId, signal);
      if (observed.header && (observed.header.parentSession !== record.parentId || observed.header.origin !== 'subagent')) {
        throw new SynthesisError('Reserved child identity belongs to another parent', 409);
      }
      // Native catalog commit occurs only after initial inbox acceptance.
      if (entry?.mode === 'continuable' && observed.header) {
        task.state = 'accepted'; task.recovered = true; delete task.error;
        changed = true;
      } else if (task.state === 'starting' && observed.absent) {
        task.state = 'pending';
        changed = true;
      }
    }
    return changed;
  }
  async function occupied(dir) {
    let active = 0;
    for (const name of (await fs.readdir(dir)).filter(name => name.startsWith('batch-') && name.endsWith('.json'))) {
      const record = await json(path.join(dir, name));
      if (record?.schema !== SCHEMA) continue;
      for (const task of record.tasks) {
        if (get('agents')?.get(task.childId)?.status === 'running' || task.state === 'starting') active++;
      }
    }
    return active;
  }

  async function start(request, signal) {
    fields(request, ['parentId', 'batchKey', 'tasks', 'planPath'], 'synthesis request');
    const {root, parent, service, dir} = await scope(request.parentId, true, signal);
    const batchKey = nonempty(request.batchKey, 'batchKey');
    const planPath = request.planPath === undefined ? undefined : await existingFile(
      path.resolve(root, nonempty(request.planPath, 'planPath')), 'planPath');
    if (planPath && !inside(root, planPath)) throw new SynthesisError('The saved plan must stay inside the workspace', 403);
    if (!Array.isArray(request.tasks) || !request.tasks.length) throw new SynthesisError('tasks must contain preparation work');
    const tasks = await Promise.all(request.tasks.map(async task => {
      fields(task, ['key', 'label', 'prompt', 'outputDirectory'], 'synthesis task');
      const outputDirectory = await directory(path.resolve(root, nonempty(task.outputDirectory, 'outputDirectory')), 'outputDirectory');
      if (outputDirectory === root || !inside(root, outputDirectory)) throw new SynthesisError('Worker output must be a dedicated directory inside the workspace', 403);
      return {key: nonempty(task.key, 'key'), label: nonempty(task.label, 'label'),
        prompt: nonempty(task.prompt, 'prompt'), outputDirectory};
    }));
    tasks.sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
    for (let i = 0; i < tasks.length; i++) for (let j = i + 1; j < tasks.length; j++) {
      if (tasks[i].key === tasks[j].key || inside(tasks[i].outputDirectory, tasks[j].outputDirectory) || inside(tasks[j].outputDirectory, tasks[i].outputDirectory)) {
        throw new SynthesisError('Preparation tasks require distinct keys and non-overlapping output directories');
      }
    }
    const recordPath = fileOf(dir, batchKey);
    const identity = {parentId: parent.id, batchKey, workspacePath: root, ...(planPath ? {planPath} : {}), tasks};
    return serialized(dir, async () => {
      const release = await lock(path.join(dir, '.startup.lock'));
      if (!release) {
        const saved = await json(recordPath);
        if (saved) {
          if (saved.schema !== SCHEMA || JSON.stringify(saved.identity) !== JSON.stringify(identity)) {
            throw new SynthesisError('This batchKey already binds different preparation work; use a new batchKey for changes', 409);
          }
          return receipt(saved, recordPath, 'Another workspace preparation batch is being registered');
        }
        return {parentId: parent.id, batchKey, recordPath, state: 'waiting', acceptedCount: 0, failedCount: 0,
          tasks: [], reason: 'Another workspace preparation batch is being registered'};
      }
      try {
        let record = await json(recordPath);
        if (record && (record.schema !== SCHEMA || JSON.stringify(record.identity) !== JSON.stringify(identity))) {
          throw new SynthesisError('This batchKey already binds different preparation work; use a new batchKey for changes', 409);
        }
        if (!record) {
          record = {schema: SCHEMA, identity, parentId: parent.id, batchKey, workspacePath: root,
            ...(planPath ? {planPath} : {}),
            createdAt: Date.now(), tasks: tasks.map(task => ({...task, childId: randomUUID(), state: 'pending'}))};
          await write(recordPath, record);
        }
        await reconcile(record, signal);
        await write(recordPath, record);
        const active = await occupied(dir);
        const slots = Math.max(0, batchSize - active);
        const ready = record.tasks.filter(task => ['pending', 'failed'].includes(task.state)).slice(0, slots);
        if (!ready.length) {
          await write(recordPath, record);
          return receipt(record, recordPath, record.tasks.some(task => task.state !== 'accepted')
            ? active >= batchSize ? `${active} preparation tasks occupy this workspace's batch budget (${batchSize})`
              : 'A reserved child exists but initial inbox acceptance is not yet confirmed' : undefined);
        }
        const reasoningSelection = await preparationReasoning(parent, signal);
        record.reasoningSelection = reasoningSelection;
        for (const task of ready) {
          task.state = 'starting'; task.reasoningSelection = reasoningSelection; delete task.error;
        }
        await write(recordPath, record); // Reserve durable identities before native creation.
        let saves = Promise.resolve();
        const save = () => { saves = saves.then(() => write(recordPath, record)); return saves; };
        await Promise.all(ready.map(async task => {
          try {
            signal?.throwIfAborted();
            const result = await service.startActivation({provider: 'spawn', childId: task.childId, label: task.label,
              parent, delivery: 'parent', prompt: [{type: 'text', text:
                PERSONA + '\n\n' +
                (planPath ? `Saved frozen plan: ${planPath}\nRead this saved plan for the assigned preparation.\n\n` : '') +
                `Assigned output directory: ${task.outputDirectory}\nChange to this directory before file operations. All writes must stay there.\n\n${task.prompt}`}],
              ...(reasoningSelection.selectedEffort ? {agentOptions: {reasoningEffort: reasoningSelection.selectedEffort}} : {}),
              maxDepth: 1, signal: signal || new AbortController().signal});
            if (result.childId !== task.childId || typeof result.messageId !== 'string' || !result.messageId) {
              throw new Error('Native startup returned an incomplete identity receipt');
            }
            task.state = 'accepted'; task.messageId = result.messageId;
          } catch (error) {
            task.error = error.message || String(error);
            // A typed native rejection is a failed attempt; uncertain startup
            // retains the reserved id for catalog/header reconciliation.
            task.state = error.name === 'SubagentError' && error.code !== 'DUPLICATE_CHILD' && !signal?.aborted ? 'failed' : 'starting';
          }
          await save();
        }));
        await reconcile(record, signal?.aborted ? undefined : signal);
        await save();
        return receipt(record, recordPath, record.tasks.some(task => task.state === 'pending')
          ? 'Remaining preparation work is waiting for the workspace batch budget' : undefined);
      } finally { await release(); }
    });
  }
  async function read({parentId, batchKey}, signal) {
    const {dir} = await scope(parentId, false, signal);
    const recordPath = fileOf(dir, batchKey);
    const value = await serialized(dir, async () => {
      const record = await json(recordPath);
      if (!record) return {parentId, batchKey, recordPath, state: 'not_started', acceptedCount: 0, tasks: []};
      if (record.parentId !== parentId) throw new SynthesisError('This batch belongs to another parent', 403);
      const release = await lock(path.join(dir, '.startup.lock'));
      if (!release) return receipt(record, recordPath, 'Workspace preparation registration is in progress');
      try {
        if (await reconcile(record, signal)) await write(recordPath, record);
        return receipt(record, recordPath);
      } finally { await release(); }
    });
    const [parentNativeActivity, ...taskActivities] = await Promise.all([
      nativeActivity(parentId), ...value.tasks.map(task => nativeActivity(task.childId)),
    ]);
    return {...value, parentNativeActivity,
      tasks: value.tasks.map((task, index) => ({...task, nativeActivity: taskActivities[index]}))};
  }
  return {start, read};
}
