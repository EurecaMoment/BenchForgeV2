const namespace = 'benchforgeWorkbench';
const owner = '@eurecamoment/benchforge-ui';

const READ_VIEWS = [
  'runtime', 'summary', 'progress', 'run', 'stage_artifacts', 'catalog', 'dataset',
  'scene_library', 'scene_selection', 'stage_review', 'plan_template', 'execution_status', 'synthesis_status',
];
const WRITE_VIEWS = ['stage_review', 'scene_selection', 'plan_edit', 'execution_control', 'synthesis_start'];

export function workbenchRemote(z) {
  const codec = (name, create) => ({mode: 'strict', typeSymbol: owner + '#' + name, create});
  const parameter = (name, schema) => ({name, wire: name, source: 'json', codec: schema});
  const query = (views) => () => z.object({view: z.enum(views)}).catchall(z.string());
  const json = codec('Json', () => z.json());
  const descriptor = (method, parameters) => ({
    id: owner + '#' + namespace + '/' + method,
    service: namespace, namespace, method, parameters,
    invocation: {kind: 'direct'}, cancellation: {parameter: 'signal'}, result: json,
  });
  return {package: owner, descriptors: [
    descriptor('read', [parameter('query', codec('ReadQuery', query(READ_VIEWS)))]),
    descriptor('write', [parameter('query', codec('WriteQuery', query(WRITE_VIEWS))), parameter('body', json)]),
  ]};
}
