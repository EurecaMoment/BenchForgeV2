import fs from 'node:fs/promises';
import path from 'node:path';

const producer = /^benchforge_(capture|run|refine|extend)$/;
const inside = (root, value) => {
  const relative = path.relative(root, value);
  return relative === '' || relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
};

// Associations come from paired native tool results, never a browser-supplied ID
// or a model-authored provenance string. Custom idempotency keys retain ownership.
export function nativeCaptureAssociations(events) {
  const calls = new Map(), found = [];
  for (const event of events) {
    if (event.type === 'tool/call' && producer.test(event.data?.name)) calls.set(event.data.callId, event.data);
    if (event.type !== 'tool/result') continue;
    const result = event.data?.message, call = calls.get(result?.toolCallId);
    if (!call || result.isError) continue;
    try {
      const value = JSON.parse((result.content || []).filter(row => row.type === 'text').map(row => row.text).join('\n'));
      if (!/^sf_[A-Za-z0-9_-]+$/.test(value.run_id || '') ||
          value.task_id && !value.task_id.startsWith(value.run_id + '.')) continue;
      found.push({run_id: value.run_id, call_id: call.callId, tool: call.name, time: event.time ?? 0});
    } catch {}
  }
  return found;
}

export function createCaptureAssociations({ctx, roots}) {
  const warmed = new Set(), writes = new Map();
  async function record(agent, events) {
    if (!/^session-[A-Za-z0-9-]+$/.test(agent?.id || '') || !agent.session?.header ||
        agent.session.header.origin === 'subagent') return;
    const additions = nativeCaptureAssociations(events);
    if (!additions.length) return;
    const cwd = await fs.realpath(agent.session.header.cwd);
    const candidates = await Promise.all(roots(cwd).map(root => fs.realpath(root)));
    const root = candidates.filter(root => inside(root, cwd)).sort((a, b) => b.length - a.length)[0];
    if (!root) return;
    const directory = path.join(root, '.benchforge', 'capture-associations');
    const file = path.join(directory, agent.id + '.json');
    const previous = writes.get(file) || Promise.resolve();
    const write = previous.catch(() => {}).then(async () => {
      let current;
      try {current = JSON.parse(await fs.readFile(file, 'utf8'));} catch (error) {if (error.code !== 'ENOENT') throw error;}
      if (current && current.context?.session_id !== agent.id) throw new Error('Native capture association belongs to another session');
      const records = new Map((current?.captures || []).map(row => [row.call_id, row]));
      let changed = false;
      for (const row of additions) if (!records.has(row.call_id)) {records.set(row.call_id, row); changed = true;}
      if (!changed) return;
      await fs.mkdir(directory, {recursive: true});
      const resolved = await fs.realpath(directory);
      if (!inside(root, resolved)) throw new Error('Capture associations must stay in their workspace');
      const temporary = file + '.tmp';
      await fs.writeFile(temporary, JSON.stringify({schema: 'benchforge.capture-associations/v1',
        context: {session_id: agent.id}, captures: [...records.values()].slice(-96)}, null, 2));
      await fs.rename(temporary, file);
    });
    writes.set(file, write);
    try {await write;} finally {if (writes.get(file) === write) writes.delete(file);}
  }
  async function warm(id) {
    if (warmed.has(id)) return;
    const agent = ctx.get('agents')?.get(id);
    if (!agent) return;
    // One bounded backfill for sessions created before ownership was recorded.
    await record(agent, agent.session.snapshotEvents().slice(-768));
    warmed.add(id);
  }
  return {record, warm};
}
