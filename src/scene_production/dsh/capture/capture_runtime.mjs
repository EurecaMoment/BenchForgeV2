import path from 'node:path';
import {launchEnvironmentOf} from '@deepseek-ai/dsh-launch-environment';
import Schema from '@deepseek-ai/schemastery';
import {loadServiceConfig} from '../service_client.mjs';
import {createCaptureAssociations} from './capture_associations.mjs';

export const name = 'benchforge-capture';
export const inject = ['workspaceRegistry'];
export const Config = Schema.object({
  productionConfig: Schema.string().default(''),
  workspacePaths: Schema.array(Schema.string()).default([]),
  revision: Schema.string().default('live-production-v1'),
});

export async function apply(ctx, config) {
  const environment = launchEnvironmentOf(ctx);
  const {configPath} = await loadServiceConfig(config.productionConfig, {
    getEnvironmentValue: name => environment.getFrom(name, ['process', 'project-env', 'user-env']),
    requireOperatorToken: false,
  });
  const configuredRoots = config.workspacePaths?.length ? config.workspacePaths : [path.dirname(configPath)];
  const roots = cwd => [...configuredRoots, ...ctx.workspaceRegistry.list().map(workspace => workspace.path)]
    .filter(root => {
      const relative = path.relative(root, cwd);
      return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
    });
  const associations = createCaptureAssociations({ctx, roots});
  ctx.provide('benchforgeCapture', {associations});
  ctx.on('agent/pre-step', async ({agent}, next) => {
    const cwd = agent.session.header?.cwd;
    if (cwd && roots(cwd).length && agent.session.header?.origin !== 'subagent') {
      await associations.record(agent, agent.session.snapshotEvents().slice(-64));
    }
    return next();
  });
}
