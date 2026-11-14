import {Config, inject, registerPythonTools} from '../../dsh/host/python_tools.mjs';
import {definitions, schemas} from '../contracts/tools.mjs';

export {Config, inject};
export const name = 'spatial-learning-tools';

export function apply(ctx, config) {
  return registerPythonTools(ctx, config, {definitions, schemas, module: 'spatial_learning.server.cli'});
}
