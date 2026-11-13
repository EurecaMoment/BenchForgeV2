import fs from 'node:fs/promises';
import path from 'node:path';

const within = (root, value) => {
  const relative = path.relative(root, value);
  return relative === '' || relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
};
const route = value => value && Object.fromEntries(['provider','model','reasoningEffort'].filter(key => value[key] !== undefined).map(key => [key,value[key]]));
const same = (a,b) => a?.provider === b?.provider && a?.model === b?.model && a?.reasoningEffort === b?.reasoningEffort;

// One deliberate change at the next native request. A later user's model
// selection is left to DSH; no default-model setting or second selection
// middleware is installed. The admitted request/header is the proof of use.
export function createExecutionTuning({ctx, pairing}) {
  const records = new Map(), files = new Map(), writes = new Map(), compacting = new Set();
  const forwardedSummaries=new WeakSet();
  const controller = new AbortController();
  const error = (message,status=400) => Object.assign(new Error(message),{status});
  async function save(id, value) {
    records.set(id,value);
    const file=files.get(id), previous=writes.get(id) || Promise.resolve();
    if (!file) return;
    const operation=previous.catch(()=>{}).then(async()=>{
      await fs.mkdir(path.dirname(file),{recursive:true});
      const temporary=file+'.tmp';
      await fs.writeFile(temporary,JSON.stringify(value,null,2),'utf8');
      await fs.rename(temporary,file);
    });
    writes.set(id,operation);
    try {await operation;} finally {if(writes.get(id)===operation)writes.delete(id);}
  }
  async function owner(root,id) {
    if(!/^session-[A-Za-z0-9-]+$/.test(id || ''))throw error('A current production conversation is required');
    const agent=ctx.get('agents')?.get(id);
    if(!agent || agent.session?.header?.origin === 'subagent')throw error('The production parent is unavailable',409);
    const cwd=agent.session.header.cwd;
    if(!cwd || !within(await fs.realpath(root),await fs.realpath(cwd)))throw error('The conversation belongs to another workspace',403);
    const file=path.join(root,'.benchforge','execution',id+'.json');
    files.set(id,file);
    if(!records.has(id)) {
      try {records.set(id,JSON.parse(await fs.readFile(file,'utf8')));} catch(e) {if(e.code!=='ENOENT')throw e;}
    }
    return agent;
  }
  async function compactWhenIdle(agent) {
    const id=agent.id, record=records.get(id);
    if(!record?.compact || record.compact.state !== 'waiting_for_idle' || compacting.has(id))return;
    compacting.add(id);
    try {
      await agent.whenIdle();
      controller.signal.throwIfAborted();
      if(ctx.get('agents')?.get(id)!==agent || agent.status !== 'idle')return;
      const compaction=agent.ctx?.get('compaction') || ctx.get('compaction');
      const commands=agent.ctx?.get('commands') || ctx.get('commands');
      if(!compaction?.compactNow && !commands?.find?.(agent,'compact'))throw error('Native history compaction is unavailable',503);
      // compactNow reserves the idle Agent synchronously and preserves queued
      // input. It never cancels a running tool or shadows an unpaired call.
      // Preset compaction may live in an isolated Cordis group. The registered
      // command carries that group's capability; do not bypass its isolation.
      const operation=(compaction?.compactNow ? compaction.compactNow(agent,controller.signal) :
        commands.execute(agent,'/compact',[],controller.signal)).then(value=>({value}),error=>({error}));
      await save(id,{...records.get(id),compact:{state:'running',started_at:Date.now()}});
      const settled=await operation;if(settled.error)throw settled.error;
      const result=settled.value;
      if(result?.commandId) {
        const done=result.result;
        await save(id,{...records.get(id),compact:{state:done.kind==='success'?(done.sourceEventSeq===undefined?'no_compactable_history':'complete'):'failed',
          command_id:result.commandId,text:done.text,finished_at:Date.now(),...(done.sourceEventSeq===undefined?{}:{summary_seq:done.sourceEventSeq})}});
      } else await save(id,{...records.get(id),compact:{state:result?'complete':'no_compactable_history',finished_at:Date.now(),
        ...(result?{shadowed_tokens:result.shadowedTokenCount,summary_seq:result.summarySeq}: {})}});
    } catch(e) {
      if(controller.signal.aborted)return;
      await save(id,{...records.get(id),compact:{state:e.code==='busy'?'waiting_for_idle':'failed',error:e.message,finished_at:Date.now()}});
    } finally {compacting.delete(id);}
  }
  async function compactAtBoundary({agent,signal}) {
    const id=agent.id,record=records.get(id);
    if(record?.compact?.state !== 'waiting_for_boundary' || compacting.has(id))return;
    const meter=agent.ctx?.get('tokenMeter') || ctx.get('tokenMeter');
    const compaction=agent.ctx?.get('compaction') || ctx.get('compaction');
    if(!meter?.measure || !compaction?.compactRegion) {
      await save(id,{...record,compact:{state:'waiting_for_idle'}});return;
    }
    compacting.add(id);
    try {
      signal.throwIfAborted();
      const measurement=meter.measure(agent.session),nodes=measurement.nodes,surface=agent.session.surface.nodes;
      if(nodes.length!==surface.length || nodes.some((item,index)=>item.seq!==surface[index]))throw error('Native token measurement no longer matches the session');
      const first=surface.length && agent.session.eventAt(surface[0])?.type==='system/message'?1:0;
      let retained=0,cut=nodes.length;
      for(let i=nodes.length-1;i>=first;i--) {
        retained+=nodes[i].tokens;cut=i;if(retained>=32768)break;
      }
      const balance=pairing || await import('@deepseek-ai/dsh-compaction');
      while(cut>first && !balance.toolPairingBalancedBefore(agent.session,surface[cut]))cut--;
      if(cut<=first) {
        await save(id,{...record,compact:{state:'no_compactable_history',finished_at:Date.now()}});return;
      }
      const start=surface[first],end=surface[cut-1];
      if(!balance.toolPairingBalancedBefore(agent.session,start) || !balance.toolPairingBalancedAfter(agent.session,end))
        throw error('No balanced native history range is available');
      await save(id,{...record,compact:{state:'running',started_at:Date.now(),retained_tokens:retained}});
      const result=await compaction.compactRegion(start,end,agent,signal);
      await save(id,{...records.get(id),compact:{state:'complete',finished_at:Date.now(),retained_tokens:retained,
        shadowed_tokens:result.shadowedTokenCount,summary_seq:result.summarySeq}});
    } catch(e) {
      if(signal.aborted)throw e;
      await save(id,{...records.get(id),compact:{state:'failed',error:e.message,finished_at:Date.now()}});
    } finally {compacting.delete(id);}
  }
  const disposers=[
    ctx.on('llm/stream',function(options,next) {
      const record=records.get(options.sessionId);
      if(forwardedSummaries.has(options) || options.purpose!=='compaction' || Object.isFrozen(options) ||
        !['waiting_for_boundary','waiting_for_idle','running'].includes(record?.compact?.state) ||
        options.provider!==record.selected.provider || options.model!==record.selected.model)return next();
      const last=options.messages.at(-1);
      if(last?.role!=='user' || !last.content?.some(block=>block.type==='text' && block.text.includes('compaction engine')))return next();
      // The public llm/stream seam permits a replacement stream for a
      // caller-owned auxiliary request. Keep its route/config and cached
      // history prefix, clone the final directive, and never rewrite a frozen
      // Agent-loop request. The provider's actual chunks and finish pass through.
      const directive='\nCheckpoint size target: at most 1500 tokens total. Keep all eight required sections. Preserve the current objective, user hard requirements, accepted artifacts, pending job identities, current files and one next action. Refer to saved scripts/ledgers by path; do not copy full code, old tool output, superseded revisions or every historical retry. Older detail remains in the archived session log and saved artifacts. Give the latest true state precedence over earlier provisional claims. Output only the concise checkpoint.';
      const replaced={...options,messages:[...options.messages.slice(0,-1),{...last,content:last.content.map(block=>block.type==='text'?{...block,text:block.text+directive}:block)}]};
      forwardedSummaries.add(replaced);
      return this.stream(replaced);
    },{prepend:true}),
    ctx.on('agent/pre-step',async(input,next)=>{
      await compactAtBoundary(input);return next();
    },{prepend:true}),
    ctx.on('agent/request',async({agent,turn,step,signal},next)=>{
      const resolved=await next(), record=records.get(agent.id);
      if(!record || !['requested','prepared'].includes(record.state))return resolved;
      if(!same(route(resolved),record.from)) {
        await save(agent.id,{...record,state:'superseded',reason:'The native model selection changed before this request.'});
        return resolved;
      }
      signal.throwIfAborted();
      await save(agent.id,{...record,state:'prepared',prepared_turn:turn,prepared_step:step});
      return {...resolved,reasoningEffort:record.selected.reasoningEffort};
    },{prepend:true}),
    ctx.on('session/event',async(session,event)=>{
      const record=records.get(session.id);
      if(event.type==='request/header' && record?.state==='prepared' && same(route(event.data.header.config),record.selected))
        await save(session.id,{...record,state:'applied',applied_at:event.time,request_seq:event.seq});
    }),
    ctx.on('agent/status',({agent,status})=>{
      if(status==='idle')void compactWhenIdle(agent);
    }),
  ];
  return {
    async arm(root,id,{reasoning_effort,compact_history=false},signal) {
      if(typeof reasoning_effort !== 'string' || !reasoning_effort.trim() || reasoning_effort.length>64)
        throw error('A supported reasoning effort is required');
      const agent=await owner(root,id), current=agent.session.requestHeader?.()?.config;
      if(!current?.provider || !current?.model)throw error('The parent has no admitted model request',409);
      const llm=agent.ctx?.get('llm') || ctx.get('llm');
      const info=await llm.resolveModelInfo(current.provider,current.model,signal);
      const supported=info.reasoning?.efforts?.map(item=>item.id) || [];
      if(!supported.includes(reasoning_effort))throw error(`The current model does not advertise reasoning effort ${reasoning_effort}`);
      const selected={...route(current),reasoningEffort:reasoning_effort};
      const previous=records.get(id);
      if(previous?.state==='prepared')throw error('The adjustment is already preparing a native request',409);
      const record={schema:'benchforge.execution-tuning/v1',session_id:id,requested_at:Date.now(),
        state:same(route(current),selected)?'applied':'requested',from:route(current),selected,supported_efforts:supported,
        // Changing effort alone retains the committed native compact receipt.
        ...(previous?.compact?{compact:previous.compact}:{}),
        ...(compact_history?{compact:{state:agent.status==='idle'?'waiting_for_idle':'waiting_for_boundary'}}:{})};
      await save(id,record);
      if(agent.status==='idle')void compactWhenIdle(agent);
      return {...record,receipt_path:files.get(id)};
    },
    async observe(root,id) {
      const agent=await owner(root,id), events=agent.session.snapshotEvents().slice(-100);
      const config=agent.session.requestHeader?.()?.config;
      const sharedLlm=ctx.get('llm'), sessionLlm=agent.ctx?.get('llm') || sharedLlm;
      const efforts=async llm=>{
        try {
          if(!config?.provider || !config?.model || !llm?.resolveModelInfo)return [];
          const info=await llm.resolveModelInfo(config.provider,config.model);
          return info.reasoning?.efforts?.map(item=>item.id) || [];
        } catch {return null;}
      };
      const available=await efforts(sessionLlm), shared=sharedLlm===sessionLlm?available:await efforts(sharedLlm);
      const record=records.get(id);
      // An authorized native /compact can finish outside this UI adapter.
      // Reconcile only its committed command pair and summary reference.
      if(record?.compact && record.compact.state!=='complete') {
        const commands=new Set(events.filter(event=>event.type==='command/run' && event.data.name==='compact' && event.time>=record.requested_at).map(event=>event.data.commandId));
        const done=events.findLast(event=>event.type==='command/done' && commands.has(event.data.commandId) && event.data.kind==='success' && event.data.sourceEventSeq!==undefined);
        if(done)await save(id,{...record,compact:{state:'complete',finished_at:done.time,command_id:done.data.commandId,
          summary_seq:done.data.sourceEventSeq,text:done.data.text}});
      }
      const starts=new Map(), steps=[], tools=[], pending=new Map();
      let activity=null;
      for(const event of events) {
        const d=event.data, key=d && d.turn+':'+d.step;
        if(event.type==='step/start') {
          starts.set(key,event.time);activity={phase:'preparing',turn:d.turn,step:d.step,started_at:event.time};
        }
        if(event.type==='request/header')activity={...(activity || {}),phase:'model',started_at:event.time};
        if(event.type==='assistant/message' && starts.has(key)) {
          const started=starts.get(key), seconds=(event.time-started)/1000, content=d.message?.content || [];
          const chunks=(d.stream || []).map(chunk=>chunk.time ?? chunk.time0).filter(time=>Number.isFinite(time) && time>=started);
          const first=chunks.length?(Math.min(...chunks)-started)/1000:null;
          const decoding=first===null?null:seconds-first;
          steps.push({turn:d.turn,step:d.step,seconds,usage:d.usage,first_stream_seconds:first,
            output_tokens_per_second:decoding>0 && Number.isFinite(d.usage?.outputTokens)?d.usage.outputTokens/decoding:null,
            reasoning_only:content.length>0 && content.every(block=>block.type==='reasoning')});
          activity={phase:'between_steps',turn:d.turn,step:d.step,started_at:event.time};
        }
        if(event.type==='tool/call') {
          const tool={time:event.time,name:d.name};tools.push(tool);pending.set(d.callId,tool);
          if(/^benchforge_(status|wait|evidence)$/.test(d.name || '')) {
            try {tool.input=Object.fromEntries(Object.entries(JSON.parse(d.arguments)).filter(([key])=>['run_id','task_id','detail','background','timeout_seconds'].includes(key)));} catch {}
          }
          activity={phase:'tool',started_at:event.time};
        }
        if(event.type==='tool/result') {
          const tool=pending.get(d.message?.toolCallId);
          if(tool) {
            tool.seconds=Math.max(0,(event.time-tool.time)/1000);
            tool.result_characters=(d.message?.content || []).reduce((count,block)=>count+(block.type==='text'?(block.text || '').length:0),0);
            tool.failed=d.message?.isError===true;
            if(tool.failed && /^benchforge_(status|wait|evidence)$/.test(tool.name))
              tool.error=(d.message?.content || []).filter(block=>block.type==='text').map(block=>block.text || '').join('\n').slice(0,1200);
          }
          pending.delete(d.message?.toolCallId);
          if(pending.size===0 && activity?.phase==='tool')activity={phase:'between_steps',started_at:event.time};
        }
        if(event.type==='compaction/start')activity={phase:'compaction',started_at:event.time};
        if(event.type==='compaction/end' || event.type==='turn/end')activity=null;
      }
      // Native inactivity is not production completion. Never expose private
      // reasoning text, or count a reasoning-only response as an artifact.
      if(activity && pending.size>0 && activity.phase==='tool')activity.started_at=Math.min(...[...pending.values()].map(tool=>tool.time));
      const current=activity?{...activity,elapsed_seconds:Math.max(0,(Date.now()-activity.started_at)/1000),
        active_tools:activity.phase==='tool'?[...pending.values()]:[]}:{phase:agent.status==='idle'?'idle':'unknown',active_tools:[]};
      const agentTools=ctx.get('agentPresets')?.serviceFor?.(agent,'tools') || agent.ctx?.get('tools') || ctx.get('tools');
      const toolDefinitions=Object.fromEntries(['benchforge_scene_status','benchforge_wait'].map(name=>{
        const tool=agentTools?.get?.(name,agent);
        return [name,tool?{description:tool.description}:null];
      }));
      const localTools=agent.ctx?.get('tools');
      const bindings=Object.fromEntries(['benchforge_scene_status','benchforge_wait','benchforge_scene_evidence'].map(name=>{
        const selected=agentTools?.get?.(name,agent),local=localTools?.get?.(name,agent);
        return [name,{same_registration:selected===local,selected_description:selected?.description ?? null,
          local_description:local?.description ?? null,selected_present:Boolean(selected),local_present:Boolean(local)}];
      }));
      return {session_id:id,agent_status:agent.status,last_used:route(agent.session.requestHeader?.()?.config),
        available_efforts:available,shared_efforts:shared,
        policy:records.get(id) || null,recent_steps:steps.slice(-4),recent_tools:tools.slice(-8),
        tool_definitions:toolDefinitions,
        tool_binding_scopes:bindings,
        recent_turn_outcomes:events.filter(event=>event.type==='turn/end').slice(-3).map(event=>({time:event.time,outcome:event.data})),
        current_activity:current,
        last_event:events.length?{type:events.at(-1).type,time:events.at(-1).time}:null};
    },
    async dispose() {
      controller.abort();for(const dispose of disposers)dispose();
      await Promise.allSettled([...writes.values()]);
    },
  };
}
