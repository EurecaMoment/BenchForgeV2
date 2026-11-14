import {Config, inject, registerPythonTools} from '../../host/python_tools.mjs';
import {definitions, schemas} from './contracts.mjs';

export {Config, inject};
export const name = 'spatial-learning-tools';

export function apply(ctx, config) {
  return registerPythonTools(ctx, config, {definitions, schemas, module: 'server.spatial_cli'});
}
