import fs from 'node:fs/promises';
import path from 'node:path';

const string = {type:'string'};
const strings = {type:'array',items:string};
export const handoffParameters = {
  action:{type:'string',enum:['publish','list','read'],required:true},
  history:{type:'boolean',description:'For list: include earlier versions. Default returns only the latest record per handoff, then applies filters.'},
  handoff_id:string,
  role:string,
  agent:string,
  status:{type:'string',enum:['working','ready','blocked','done']},
  summary:string,
  inputs:strings,
  artifacts:strings,
  findings:strings,
  blockers:strings,
  next_actions:strings,
  parent_handoff_id:string,
  reply_to:string,
  related_handoff_ids:strings,
  requested_from:strings,
  decision:string,
  confidence:{type:'number'},
  supersedes_handoff_id:string,
  filter:{type:'object',additionalProperties:false,properties:{status:string,role:string,agent:string}},
};

const pending = new Map();

export async function executeHandoff(args, {agent, signal}) {
  signal?.throwIfAborted();
  const file = path.join(path.resolve(args.workspace), '.benchforge', 'collaboration', 'handoffs.jsonl');
  const previous = pending.get(file) ?? Promise.resolve();
  const operation = previous.catch(() => {}).then(async () => {
    signal?.throwIfAborted();
    if (args.action === 'publish') {
      if (!args.role || !args.summary) throw new Error('collaboration publish needs role and summary');
      await fs.mkdir(path.dirname(file), {recursive:true});
      signal?.throwIfAborted();
      const handoff = {
        handoff_id:args.handoff_id || Date.now() + '-' + Math.random().toString(36).slice(2,8),
        created_at:new Date().toISOString(),
        agent:args.agent || agent?.session?.id || 'current-agent',
        role:args.role,
        status:args.status || 'working',
        summary:args.summary,
        inputs:args.inputs || [],
        artifacts:args.artifacts || [],
        findings:args.findings || [],
        blockers:args.blockers || [],
        next_actions:args.next_actions || [],
        parent_handoff_id:args.parent_handoff_id || null,
        reply_to:args.reply_to || null,
        related_handoff_ids:args.related_handoff_ids || [],
        requested_from:args.requested_from || [],
        decision:args.decision || null,
        confidence:args.confidence ?? null,
        supersedes_handoff_id:args.supersedes_handoff_id || null,
      };
      // Complete an append already in flight before honoring cancellation.
      await fs.appendFile(file, JSON.stringify(handoff) + '\n', 'utf8');
      signal?.throwIfAborted();
      return handoff;
    }
    let rows = [];
    try {
      const contents = await fs.readFile(file, {encoding:'utf8', signal});
      rows = contents.split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    signal?.throwIfAborted();
    if (args.action === 'read') {
      const row = rows.findLast(item => item.handoff_id === args.handoff_id);
      if (!row) throw new Error('Unknown collaboration handoff: ' + args.handoff_id);
      return row;
    }
    if (args.action === 'list') {
      if (!args.history) rows = [...new Map(rows.map(item => [item.handoff_id, item])).values()];
      const filter = args.filter || {};
      return {handoffs:rows.filter(item =>
        (!filter.status || item.status === filter.status) &&
        (!filter.role || item.role === filter.role) &&
        (!filter.agent || item.agent === filter.agent))};
    }
    throw new Error('Unknown collaboration action: ' + args.action);
  });
  pending.set(file, operation);
  try {
    return await operation;
  } finally {
    if (pending.get(file) === operation) pending.delete(file);
  }
}
