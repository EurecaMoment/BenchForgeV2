// Optional integration replay against an installed DSH, without model or simulator calls.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

const { values } = parseArgs({options:{
  'dsh-root':{type:'string'}, output:{type:'string'}, plugin:{type:'string'},
}});
if (!values['dsh-root'] || !values.output) throw Error('Usage: node replay_subagents.mjs --dsh-root /path/to/dsh --output /new/evidence/directory [--plugin /path/to/tools.mjs]');
const dsh = path.resolve(values['dsh-root']), out = path.resolve(values.output);
await fs.mkdir(out, {recursive:true});
const workspace = await fs.mkdtemp(path.join(out,'workspace-'));
const require = createRequire(path.join(dsh,'packages/core/agent-loop/package.json'));
const modules = {
  'dsh-session-query':'session-query/session-query',
  'dsh-subagent':'subagent/subagent',
  'dsh-subagent-spawn-in-process':'subagent/subagent-spawn-in-process',
  'dsh-tool-subagent':'subagent/tool-subagent',
  'dsh-tool-subagent-control':'subagent/tool-subagent-control',
};
const load = name => import(modules[name]
  ? pathToFileURL(path.join(dsh,'packages',modules[name],'lib/index.js'))
  : require.resolve('@deepseek-ai/' + name));
const { Context } = await load('cordis');
const { default:LlmRuntime, LlmAdapter, ToolCallId } = await load('dsh-llm');
const { default:SessionStore, SessionId } = await load('dsh-session');
const { default:SessionProjectionRegistry } = await load('dsh-session-projection');
const { default:SystemPrompt } = await load('dsh-system-prompt');
const { default:ToolRuntime } = await load('dsh-tools');
const { default:AgentRegistry } = await load('dsh-agent');
const { default:AgentLoop } = await load('dsh-agent-loop');
const { default:Persistence } = await load('dsh-session-persistence-jsonl');
const { default:SessionQuery } = await load('dsh-session-query');
const { default:Subagents } = await load('dsh-subagent');
const Spawn = await load('dsh-subagent-spawn-in-process');
const Delegate = await load('dsh-tool-subagent');
const Control = await load('dsh-tool-subagent-control');
const spatialforge = await import(values.plugin ? pathToFileURL(path.resolve(values.plugin)) : new URL('../plugin/tools.mjs', import.meta.url));

// Continuation loads sessions through the real JSONL persistence. Corpus search
// is not part of this test and must never fall through to a production service.
class ReplayQuery extends SessionQuery {
  async searchSessions() {throw Error('Unexpected corpus search');}
  async searchEvents() {throw Error('Unexpected event search');}
}
const entered = new Set(), calls = [], artifacts = [];
const together = Promise.withResolvers();
const published = new Map();
class Adapter extends LlmAdapter {
  requests = 0;
  async resolveModel(provider,id) {return {provider,id,name:id,inputModalities:['text']};}
  async *stream(options) {
    this.requests++;
    const texts = options.messages.flatMap(m => m.role === 'user' ? m.content.filter(b => b.type === 'text').map(b => b.text) : []);
    const worker = texts.some(t => t.includes('WORKER_A')) ? 'A' : texts.some(t => t.includes('WORKER_B')) ? 'B' : undefined;
    const resumed = texts.some(t => t.includes('RESUME_REPAIR'));
    let args;
    if (worker) {
      if (!entered.has(worker)) {
        entered.add(worker);
        if (entered.size === 2) together.resolve();
        await together.promise; // Both child activations must coexist before either publishes.
      }
      const key = worker + (resumed ? '-resume' : '-initial');
      if (!published.has(key)) {
        published.set(key,true);
        const artifact = path.join(workspace,worker + (resumed ? '-repaired' : '-initial') + '.json');
        // Fixture observations stay explicitly labeled; they are not scene GT.
        await fs.writeFile(artifact,JSON.stringify({fixture:true,worker,resumed},null,2));
        artifacts.push(artifact);
        args = {workspace,action:'publish',handoff_id:'work-'+worker,role:'worker',
          status:worker === 'A' && !resumed ? 'blocked' : 'done',
          summary:resumed ? 'Resumed after parent feedback' : 'Scripted independent observation',
          artifacts:[artifact],blockers:worker === 'A' && !resumed ? ['fixture repair pending'] : [],
        };
      }
    }
    const block = args ? {type:'tool-call',id:'handoff-'+this.requests,name:'spatialforge_collaboration',arguments:JSON.stringify(args)}
      : {type:'text',text:'Scripted transport replay complete; no scene acceptance claimed.'};
    yield {type:'block-start',index:0,blockType:block.type};
    if (args) yield {type:'tool-call-delta',index:0,id:block.id,name:block.name,argumentsDelta:block.arguments};
    else yield {type:'text-delta',index:0,text:block.text};
    yield {type:'block-end',index:0,block};
    yield {type:'finish',reason:{kind:args?'tool-calls':'stop'}};
  }
}
const ctx = new Context(), adapter = new Adapter();
const snapshots = new Map();
async function until(condition) {
  const deadline = Date.now() + 5000;
  while (!condition()) {
    if (Date.now() > deadline) throw Error('Replay child did not settle');
    await new Promise(resolve => setTimeout(resolve,10));
  }
}
let number = 0;
async function call(parent,name,args) {
  const result = await ctx.tools.execute({name,arguments:args,callId:ToolCallId('parent-call-'+(++number)),agent:parent,signal:AbortSignal.timeout(15000)});
  calls.push({name,args,result});
  assert.equal(result.isError,false,JSON.stringify(result));
  return result.content.filter(b => b.type === 'text').map(b => b.text).join('');
}
try {
  for (const plugin of [LlmRuntime,SessionStore,SessionProjectionRegistry,SystemPrompt,ToolRuntime,AgentRegistry]) await ctx.plugin(plugin);
  await ctx.plugin(Persistence,{root:path.join(workspace,'sessions')});
  await ctx.plugin(ReplayQuery);
  await ctx.plugin(AgentLoop,{agents:[]});
  await ctx.plugin(Subagents);
  await ctx.plugin(Spawn,{providerName:'spawn'});
  await ctx.plugin(Delegate,{provider:'spawn',toolName:'subagent',backgroundMode:'continuable'});
  await ctx.plugin(Control);
  ctx.llm.registerAdapter(['fixture'],adapter);
  ctx.on('agent/turn-stopping',({agent}) => {snapshots.set(agent.id,agent.session);});
  const config = path.join(workspace,'service.json');
  await fs.writeFile(config,JSON.stringify({port:9}));
  process.env.SPATIALFORGE_OPERATOR_TOKEN = 'scripted-unused-token';
  // Only the shared-workspace tool is registered; no producer, network call or
  // simulator entry point exists in this replay context.
  await spatialforge.apply({on:()=>{},llm:ctx.llm,get:ctx.get.bind(ctx),tools:{register:tool => {
    if (tool.name === 'spatialforge_collaboration') ctx.tools.register(tool);
  }}},{dshRoot:dsh,serviceConfig:config});
  const parent = await ctx.agentLoop.create(SessionId('spatialforge-replay-parent'),{provider:'fixture',model:'fixture'});
  const children = await Promise.all(['A','B'].map(async worker => {
    const text = await call(parent,'subagent',{description:'Independent fixture worker '+worker,prompt:'WORKER_'+worker,run_in_background:true});
    assert.match(text,/^started subagent /);
    return text.slice('started subagent '.length);
  }));
  await until(() => children.every(id => !ctx.agents.get(id)));
  assert.equal(entered.size,2);
  const blocked = JSON.parse(await call(parent,'spatialforge_collaboration',{workspace,action:'list',filter:{status:'blocked'}}));
  assert.equal(blocked.handoffs.length,1);
  assert.equal(blocked.handoffs[0].handoff_id,'work-A');
  // This child has released its activation: send_message must restore its
  // persisted conversation and wake a second turn, not create a new child.
  await call(parent,'send_message',{agent_id:children[0],message:'RESUME_REPAIR: close the fixture blocker and publish the updated evidence.'});
  await until(() => published.has('A-resume') && !ctx.agents.get(children[0]));
  const resolved = JSON.parse(await call(parent,'spatialforge_collaboration',{workspace,action:'list',filter:{status:'blocked'}}));
  assert.deepEqual(resolved.handoffs,[]);
  const history = JSON.parse(await call(parent,'spatialforge_collaboration',{workspace,action:'list',history:true}));
  assert.equal(history.handoffs.length,3);
  assert.equal(history.handoffs.filter(h => h.status === 'blocked').length,1);
  assert.equal(new Set(history.handoffs.map(h => h.agent)).size,2);
  const workerA = history.handoffs.filter(h => h.handoff_id === 'work-A');
  assert.equal(workerA[0].agent,workerA[1].agent);
  const eventsA = snapshots.get(children[0]).snapshotEvents();
  assert.equal(eventsA.filter(e => e.type === 'turn/start').length,2);
  await parent.whenIdle();
  const childTurns = children.map(id => {
    const events = snapshots.get(id).snapshotEvents();
    assert.ok(events.filter(e => e.type === 'turn/end').every(e => e.data.reason.kind === 'completed'));
    assert.equal(events.filter(e => e.type === 'tool/result' && e.data.message.isError).length,0);
    return {id,completed_turns:events.filter(e => e.type === 'turn/end').length};
  });
  assert.deepEqual(childTurns.map(c => c.completed_turns),[2,1]);
  for (const [id,session] of snapshots) await fs.writeFile(path.join(out,id+'.json'),JSON.stringify(session.snapshotEvents(),null,2));
  const result = {children,overlapping_children:entered.size,resumed_same_child:workerA[0].agent,
    child_turns:childTurns,current_blockers:resolved.handoffs.length,history:history.handoffs,artifacts,calls,requests:adapter.requests,
    model_api_calls:0,isaac_starts:0,scope:'Actual DSH subagent creation, concurrent activations, child tool inheritance, JSONL session restore, send_message resumption and shared handoffs. Decisions and artifact content are scripted fixtures, not autonomous model performance.'};
  await fs.writeFile(path.join(out,'subagent-replay.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({children:children.length,overlapping_children:entered.size,resumed_same_child:true,current_blockers:0,history_records:3,model_api_calls:0}));
} finally {
  together.resolve();
  await ctx.fiber.dispose();
}
