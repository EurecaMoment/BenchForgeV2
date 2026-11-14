import Schema from '@deepseek-ai/schemastery';
import {canonicalSceneToolName} from '../plugin/scene_tool_names.mjs';

export const name = 'benchforge-subagent-policy';
export const inject = ['systemPrompt', 'tools'];
export const Config = Schema.object({
  persona: Schema.string().required(),
  parentTools: Schema.array(Schema.string()).required(),
});

export function apply(ctx, {persona, parentTools}) {
  const isSubagent = agent => agent?.session?.header?.origin === 'subagent';
  const parentOnly = new Set(parentTools);
  for (const tool of parentTools) parentOnly.add(tool.replace(/^benchforge_/, ''));
  ctx.systemPrompt.section({
    name,
    order: 500,
    text: ({scope}) => isSubagent(scope) ? persona : '',
  });
  ctx.tools.guard(call => isSubagent(call.agent) && parentOnly.has(canonicalSceneToolName(call.name))
    ? 'The parent agent owns this production operation.'
    : undefined);
}
