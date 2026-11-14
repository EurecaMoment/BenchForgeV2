import Schema from '@deepseek-ai/schemastery';
import {createExecutionTuning} from '../workbench/sessions/execution_control.mjs';
import {createSynthesisSessions} from '../workbench/sessions/synthesis.mjs';

export const name = 'benchforge-session-operations';
export const Config = Schema.object({
  revision: Schema.string().default('live-production-v1'),
});

export function apply(ctx) {
  const execution = createExecutionTuning({ctx});
  ctx.effect(() => () => execution.dispose(), name);
  ctx.provide('benchforgeSessions', {
    execution,
    preparation: (workspacePath, batchSize) => createSynthesisSessions({ctx, workspacePath, batchSize}),
  });
}
