import fs from 'node:fs/promises';
import path from 'node:path';
import {createUserMessage} from '@deepseek-ai/dsh-llm';
import {compactCaptureObservation} from './capture_watch.mjs';

// Existing Agents keep their preset revision. This root-scoped, authenticated
// adapter gives those Agents background waiting without replacing their tools.
export function createLegacyCaptureStep({watch, recover, read, createMessage = createUserMessage}) {
  const seen = new Set(), announced = new Set();
  return async ({agent, signal}, next) => {
    const decision = await next();
    if (decision.kind !== 'enter' || agent.session.header?.origin === 'subagent') return decision;
    const definition = agent.ctx?.get('tools')?.get('spatialforge_wait', agent);
    if (!definition || definition.description?.includes('background=true')) return decision;
    const events = agent.session.snapshotEvents().slice(-28);
    const calls = new Map(), messages = [];
    for (const event of events) {
      if (event.type === 'tool/call') calls.set(event.data.callId, event.data);
      if (event.type !== 'tool/result') continue;
      const result = event.data.message, call = calls.get(result.toolCallId);
      if (!call || !/^spatialforge_(capture|refine|run|extend|retry|wait|status)$/.test(call.name)) continue;
      const key = agent.id + ':' + result.toolCallId;
      if (seen.has(key)) continue;
      seen.add(key);
      if (seen.size > 512) seen.delete(seen.values().next().value);
      try {
        const args = JSON.parse(call.arguments), text = (result.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
        let value;
        if (result.isError) {
          if (call.name === 'spatialforge_retry' && /Unreviewed scene retries require an admitted native capture|Only review transport failures can reuse a frozen capture/.test(text)) {
            value = await recover(args, signal);
            value = await watch({run_id: args.task_id.split('.')[0]}, {agent, signal});
          } else if (['spatialforge_wait','spatialforge_status'].includes(call.name) && /KeyError/.test(text) && /['"]report['"]/.test(text)) {
            value = await read('/observe', {run_id: args.run_id}, signal);
          } else continue;
        } else {
          const response = JSON.parse(text);
          const run_id = response.run_id || args.run_id || args.task_id?.split('.')[0];
          if (!/^sf_[A-Za-z0-9_-]+$/.test(run_id || '')) continue;
          value = await watch({run_id}, {agent, signal});
          if (!value.watch?.accepted) continue;
          const identity=agent.id+':'+run_id;
          if(announced.has(identity))continue;
          announced.add(identity);
        }
        const summary = compactCaptureObservation(value);
        messages.push(createMessage({source:{kind:'spatialforge/capture-runtime'},content:[{type:'text',text:
          '采集运行时通知（不是用户指令）：'+JSON.stringify(summary)+'\n后台等待已受理时继续独立准备，或结束本轮等待终态通知，不再逐分钟模型轮询。失败仍未完成；原生质量验收与用户阶段窗口照常保留。'}]}));
      } catch (error) {
        signal?.throwIfAborted();
        messages.push(createMessage({source:{kind:'spatialforge/capture-runtime'},content:[{type:'text',text:
          '采集恢复尚未完成：'+error.message+'。保留现有作业与文件，按真实失败阶段处理，禁止把此错误当成已采集或已验收。'}]}));
      }
    }
    return messages.length ? {...decision, messages:[...(decision.messages || []), ...messages]} : decision;
  };
}

export async function attachCaptureRuntime(ctx, config) {
  if (!config.productionConfig) return;
  const cfg = JSON.parse(await fs.readFile(config.productionConfig, 'utf8'));
  if (!cfg.operator_token) return; // Environment-only deployments keep their normal scoped adapter.
  const revision = '?revision=' + encodeURIComponent(config.uiRevision);
  const {createObservationBridge} = await import('./observation_bridge.mjs' + revision);
  const {createCaptureRetry} = await import('./capture_retry.mjs' + revision);
  const {createCaptureWatcher} = await import('./capture_watch.mjs' + revision);
  const controller = new AbortController();
  ctx.on('dispose', () => controller.abort());
  const api = async (route, args, signal) => {
    const response = await fetch((cfg.service_url || 'http://127.0.0.1:' + (cfg.port || 3841)) + route,
      {method:'POST', headers:{'Content-Type':'application/json',Authorization:'Bearer '+cfg.operator_token},body:JSON.stringify(args),signal});
    const value = JSON.parse(await response.text(), (_key,item) => Object.is(item,-0) ? 0 : item);
    if (!response.ok) throw Object.assign(new Error('Native capture service rejected'),{status:response.status,response:value});
    return value;
  };
  const read = createObservationBridge({api,artifacts:cfg.artifacts,policyPython:config.productionPython});
  const recover = createCaptureRetry({api,serviceConfig:config.productionConfig,policyPython:config.productionPython});
  const watch = createCaptureWatcher({artifacts:cfg.artifacts,read,signal:controller.signal,notify:async(agent,record)=>{
    agent.followup(createUserMessage({source:{kind:'spatialforge/capture-watch'},content:[{type:'text',text:
      '采集终态通知：'+JSON.stringify(record)+'\n继续原任务；失败仍未完成，按真实失败阶段处理，不再轮询已结束作业。'}]}));
  }});
  const hook = createLegacyCaptureStep({watch,recover,read});
  const roots = config.workspacePaths?.length ? config.workspacePaths : [path.dirname(config.productionConfig)];
  ctx.on('agent/pre-step', async (input,next) => {
    const cwd = input.agent.session.header?.cwd;
    if (!cwd || !roots.some(root => {const relative=path.relative(root,cwd);return relative==='' || relative!=='..'&&!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative);})) return next();
    return hook(input,next);
  });
}
