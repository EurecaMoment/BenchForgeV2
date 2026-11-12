import vm from 'node:vm';

export function loadClient(source, React, globals = {}) {
  let definition;
  const context = {window: {__ModuleLoader__: {load(value) { definition = value; }}}, ...globals};
  vm.runInNewContext(source, context, {filename: 'client.js'});
  if (!definition || typeof definition.factory !== 'function') throw new Error('DSH client factory was not registered');
  return {definition, api: definition.factory(() => React), context};
}
