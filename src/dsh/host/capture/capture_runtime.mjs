import fs from 'node:fs/promises';
import path from 'node:path';
import {createUserMessage} from '@deepseek-ai/dsh-llm';
import {launchEnvironmentOf} from '@deepseek-ai/dsh-launch-environment';
import Schema from '@deepseek-ai/schemastery';
import {loadServiceConfig} from '../../shared/config.mjs';
import {canonicalSceneToolName, captureObservationNames, sceneToolNames} from '../../shared/scene_tool_names.mjs';
const {compactCaptureObservation,captureRunId}=await import(new URL('./capture_watch.mjs'+new URL(import.meta.url).search,import.meta.url));

export const name = 'benchforge-capture';
export const inject = ['workspaceRegistry'];
export const Config = Schema.object({
  productionConfig: Schema.string().default(''),
  workspacePaths: Schema.array(Schema.string()).default([]),
  revision: Schema.string().default('live-production-v1'),
});

export async function apply(ctx, config) {
  const associations = await attachCaptureRuntime(ctx, config);
  ctx.provide('benchforgeCapture', {associations});
}

// Retained tools can have old implementations and lost registration disposers.
// Public around-dispatch hooks replace only these observation bodies. Their
// existing schemas, output validation, preset and Agent identity stay in place.
export function createScopedCaptureObservations({read,watch,evidence,artifacts}) {
  const ownershipKey=Symbol.for('benchforge.capture-observation-interceptors');
  const ownership=globalThis[ownershipKey]??=new WeakMap();
  const installed=new WeakMap(), records=new Set();
  return {
    install(agent) {
      if(installed.has(agent))return;
      const context=agent.ctx,tools=context?.get('tools');
      if(!tools || typeof context.on!=='function')return;
      const names=new Set(captureObservationNames.flatMap(sceneToolNames)
        .filter(name=>tools.get?.(name,agent)));
      if(!names.size)return;
      const previous=ownership.get(agent);
      const disposeHook=context.on('tools/execute',async(exec,next)=>{
        if(exec.agent!==agent || !names.has(exec.name))return next();
        const name=canonicalSceneToolName(exec.name);
        const args=exec.arguments;
        exec.signal?.throwIfAborted();
        let value;
        if(name==='benchforge_scene_status') {
          const {cursor:ignored,...request}=args;
          request.run_id=captureRunId(request.run_id);
          const {cursor,...observed}=await read(args.detail?'/inspect':'/observe',request,exec.signal);
          value=args.detail===true?observed:compactCaptureObservation(observed,{artifacts});
        } else if(name==='benchforge_wait') {
          const {background,cursor:ignored,...request}=args;
          request.run_id=captureRunId(request.run_id);
          const observed=background?await watch(request,exec):await read('/wait',request,exec.signal);
          value=compactCaptureObservation(observed,{artifacts});
        } else {
          if(typeof evidence!=='function')return next();
          const request={...args},runId=captureRunId(args.run_id || args.task_id);
          if(request.run_id)request.run_id=runId;
          if(request.task_id===runId) {
            const observed=await read('/observe',{run_id:runId},exec.signal);
            if(observed.tasks?.length!==1)throw new Error('Choose the exact task_id from this run: '+(observed.tasks || []).map(task=>task.id).join(', '));
            request.task_id=observed.tasks[0].id;
          }
          value=await evidence(request,exec);
        }
        exec.signal?.throwIfAborted();
        // Authored around-dispatch values re-enter Tools.normalizeDispatchResult,
        // which validates output.schema and invokes the original output renderer.
        return {isError:false,value,content:[]};
      });
      let released=false;
      const record={dispose() {
        if(released)return;
        released=true;
        disposeHook();
        records.delete(record);
        installed.delete(agent);
        if(ownership.get(agent)===record)ownership.delete(agent);
      }};
      installed.set(agent,record);
      records.add(record);
      ownership.set(agent,record);
      previous?.dispose();
    },
    dispose() {for(const record of [...records])record.dispose();},
  };
}

// Use the same native evidence route and vision checks as the preset tool.
// Never invoke a borrowed ToolDefinition with a fabricated run context.
export function createCaptureEvidence({api}) {
  return async(args,exec)=>{
    const value=await api('/evidence',args,exec.signal);
    if(!value.image_path)return value;
    const context=exec.agent?.ctx,attachments=context?.get('attachments'),llm=context?.get('llm');
    const routed=exec.agent?.session.requestHeader()?.config;
    const provider=routed?.provider??exec.agent?.options.provider,model=routed?.model??exec.agent?.options.model;
    if(!attachments||!llm||provider===undefined||model===undefined)throw Error('Image evidence needs the attachment service and a resolved vision route; copy to workspace_id for file processing.');
    const info=await llm.resolveModelInfo(provider,model,exec.signal);
    if(!info.inputModalities?.includes('image'))throw Error('Current model route does not declare image input; use JSON evidence or copy the image to workspace_id.');
    exec.signal.throwIfAborted();
    const data=await fs.readFile(value.image_path,{signal:exec.signal});
    exec.signal.throwIfAborted();
    value.image=await attachments.saveImage({data,mediaType:/\.jpe?g$/i.test(value.image_path)?'image/jpeg':'image/png',name:path.basename(value.image_path)});
    exec.signal.throwIfAborted();
    delete value.image_path;
    return value;
  };
}

// Existing Agents keep their preset revision. This root-scoped, authenticated
// adapter gives those Agents background waiting without replacing their tools.
export function createLegacyCaptureStep({watch, associate, createMessage = createUserMessage}) {
  const seen = new Set(), announced = new Set();
  return async ({agent, signal}, next) => {
    const decision = await next();
    if (decision.kind !== 'enter' || agent.session.header?.origin === 'subagent') return decision;
    const events = agent.session.snapshotEvents().slice(-64);
    if (associate) await associate(agent, events);
    const tools = agent.ctx?.get('tools');
    const definition = sceneToolNames('benchforge_wait').map(name => tools?.get(name, agent)).find(Boolean);
    if (!definition || definition.description?.includes('background=true')) return decision;
    const calls = new Map(), messages = [];
    for (const event of events) {
      if (event.type === 'tool/call') calls.set(event.data.callId, event.data);
      if (event.type !== 'tool/result') continue;
      const result = event.data.message, call = calls.get(result.toolCallId);
      const name = canonicalSceneToolName(call?.name);
      if (!call || !/^benchforge_(capture|refine|run|extend|retry|wait|scene_status)$/.test(name)) continue;
      const key = agent.id + ':' + result.toolCallId;
      if (seen.has(key)) continue;
      seen.add(key);
      if (seen.size > 512) seen.delete(seen.values().next().value);
      try {
        const args = JSON.parse(call.arguments), text = (result.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
        if (result.isError) continue;
        const response = JSON.parse(text);
        const run_id = response.run_id || args.run_id || args.task_id?.split('.')[0];
        if (!/^sf_[A-Za-z0-9_-]+$/.test(run_id || '')) continue;
        const value = await watch({run_id}, {agent, signal});
        if (!value.watch?.accepted) continue;
        const identity=agent.id+':'+run_id;
        if(announced.has(identity))continue;
        announced.add(identity);
        const summary = compactCaptureObservation(value);
        messages.push(createMessage({source:{kind:'benchforge/capture-runtime'},content:[{type:'text',text:
          '采集运行时通知（不是用户指令）：'+JSON.stringify(summary)+'\n后台等待已受理时继续独立准备，或结束本轮等待终态通知，不再逐分钟模型轮询。失败仍未完成；原生质量验收与用户阶段窗口照常保留。'}]}));
      } catch (error) {
        signal?.throwIfAborted();
        messages.push(createMessage({source:{kind:'benchforge/capture-runtime'},content:[{type:'text',text:
          '采集恢复尚未完成：'+error.message+'。保留现有作业与文件，按真实失败阶段处理，禁止把此错误当成已采集或已验收。'}]}));
      }
    }
    return messages.length ? {...decision, messages:[...(decision.messages || []), ...messages]} : decision;
  };
}

export async function attachCaptureRuntime(ctx, config) {
  if (!config.productionConfig) return;
  const environment = launchEnvironmentOf(ctx);
  const {config: cfg, configPath, serviceUrl, operatorToken} = await loadServiceConfig(config.productionConfig, {
    getEnvironmentValue: (name) => environment.getFrom(name, ['process','project-env','user-env']),
    requireOperatorToken: false,
    requireScenePolicy: false,
  });
  if (!operatorToken) return; // The scoped plugin still handles its own credentials.
  const revision = '?revision=' + encodeURIComponent(config.revision ?? 'live-production-v1');
  const {createCaptureWatcher, deliverCaptureNotice} = await import('./capture_watch.mjs' + revision);
  const {createCaptureAssociations} = await import('./capture_associations.mjs' + revision);
  const controller = new AbortController();
  ctx.effect(()=>()=>controller.abort(),'benchforge capture runtime cancellation');
  const api = async (route, args, signal) => {
    const response = await fetch(serviceUrl + route,
      {method:'POST', headers:{'Content-Type':'application/json',Authorization:'Bearer '+operatorToken},body:JSON.stringify(args),signal});
    const value = JSON.parse(await response.text(), (_key,item) => Object.is(item,-0) ? 0 : item);
    if (!response.ok) throw Object.assign(new Error('Native capture service rejected'),{status:response.status,response:value});
    return value;
  };
  const configuredRoots = config.workspacePaths?.length ? config.workspacePaths : [path.dirname(configPath)];
  const roots = cwd => [...configuredRoots, ...(ctx.get('workspaceRegistry')?.list().map(workspace => workspace.path) ?? [])]
    .filter(root => {
      const relative = path.relative(root, cwd);
      return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
    });
  const associations = createCaptureAssociations({ctx, roots});
  const watch = createCaptureWatcher({artifacts:cfg.artifacts,read:api,signal:controller.signal,
    notify:async(agent,record)=>deliverCaptureNotice(agent,record,createUserMessage)});
  const observations=createScopedCaptureObservations({read:api,watch,evidence:createCaptureEvidence({api}),artifacts:cfg.artifacts});
  ctx.effect(()=>()=>observations.dispose(),'benchforge capture observation interceptors');
  const hook = createLegacyCaptureStep({watch,associate:associations.record});
  ctx.on('agent/pre-step', async (input,next) => {
    const cwd = input.agent.session.header?.cwd;
    if (!cwd || !roots(cwd).length) return next();
    if(input.agent.session.header?.origin!=='subagent')observations.install(input.agent);
    return hook(input,next);
  });
  return associations;
}
