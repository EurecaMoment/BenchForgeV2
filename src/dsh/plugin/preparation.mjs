import fs from 'node:fs/promises';
import path from 'node:path';

const inside = (root, value) => {
  const relative = path.relative(root, value);
  return relative === '' || relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
};
async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

// Native tools supply exec.agent; a model cannot select another parent identity.
// The saved plan uses the same conversation association as workbench edits.
export async function savedPreparationPlan(workspace, planPath, agent, signal) {
  signal?.throwIfAborted();
  if (!agent || agent.id !== agent.session?.header?.id) throw new Error('Preparation needs the current parent Agent');
  const root = await fs.realpath(workspace);
  const cwd = await fs.realpath(agent.session.header.cwd);
  const file = await fs.realpath(path.resolve(root, planPath));
  if (!inside(root, cwd) || !inside(root, file) || !(await fs.stat(file)).isFile())
    throw new Error('Preparation plan and parent must belong to the named workspace');
  const policy = await readJson(path.join(root, 'scene-library', 'policy.json'));
  if (policy?.enabled && (policy.excluded_paths || []).some(folder => inside(folder, file)))
    throw new Error('This saved plan references a removed scene; use the revised parent plan');
  let current = path.dirname(file);
  while (inside(root, current)) {
    signal?.throwIfAborted();
    const records = await Promise.all(['request.json', 'state.json'].map(name => readJson(path.join(current, name))));
    if (records.some(record => record?.context?.session_id === agent.id || record?.context?.session_ids?.includes(agent.id)))
      return {workspacePath: root, planPath: file, parentId: agent.id};
    if (current === root) break;
    current = path.dirname(current);
  }
  throw new Error('The saved plan is not associated with the current parent conversation');
}

export function createPreparationHandler({ctx, batchSize = 3, revision = '', createController}) {
  return async (args, exec) => {
    const scope = await savedPreparationPlan(args.workspace, args.plan_path, exec.agent, exec.signal);
    const factory = createController || (await import(new URL('../ui/synthesis_sessions.js' + revision, import.meta.url))).createSynthesisSessions;
    return factory({ctx, workspacePath: scope.workspacePath, batchSize}).start({
      parentId: scope.parentId, planPath: scope.planPath, batchKey: args.batch_key, tasks: args.tasks,
    }, exec.signal);
  };
}
