import Schema from '@deepseek-ai/schemastery';

export const name = 'benchforge-session-operations';
export const Config = Schema.object({
  revision: Schema.string().default('live-production-v1'),
});

export async function apply(ctx, {revision}) {
  const version = '?revision=' + encodeURIComponent(revision);
  const {createExecutionTuning} = await import('./execution_tuning.mjs' + version);
  const {createSynthesisSessions} = await import('./synthesis_sessions.js' + version);
  const execution = createExecutionTuning({ctx});
  ctx.effect(() => () => execution.dispose(), name);
  ctx.provide('benchforgeSessions', {
    execution,
    preparation: (workspacePath, batchSize) => createSynthesisSessions({ctx, workspacePath, batchSize}),
  });
}
