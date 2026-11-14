import {ApiError} from '../../host/session_scope.mjs';

export function createWorkbenchReadRoutes({discover, productionProgress, readRun, sceneArtifacts, sceneMedia, readDataset, readMedia}) {
  return async function dispatch({view, request, url, roots, limits, scoped, scope, sessions}) {
    if (view === 'summary') return discover(roots, limits, request.signal, scope);
    if (view === 'progress') return productionProgress(roots, scoped, url, request.signal);
    if (view === 'run') return readRun(url.searchParams.get('run'), roots, limits, request.signal, scope);
    if (view === 'run_product') {
      const run = await readRun(url.searchParams.get('run'), roots, limits, request.signal, scope);
      const product = url.searchParams.get('product'), step = url.searchParams.get('step');
      const value = product === 'plan' ? run.plan : product === 'config' ? run.stage_artifacts.find((row) => row.stage === 'S4')?.data
        : product === 'report' ? run.stage_artifacts.find((row) => row.stage === 'S5' && row.step_id === step)?.data : null;
      if (!value) throw new ApiError('Stage product was not found', 404);
      if (product === 'report' && url.searchParams.get('format') === 'markdown') {
        if (typeof value.body_markdown !== 'string' || !value.body_markdown.trim()) throw new ApiError('Markdown report was not found', 404);
        return new Response(value.body_markdown, {headers: {'content-type': 'text/markdown; charset=utf-8',
          'content-disposition': 'attachment; filename="delivery_report.md"', 'cache-control': 'no-store',
          'x-content-type-options': 'nosniff'}});
      }
      return value;
    }
    if (view === 'stage_artifacts') return sceneArtifacts(scoped, roots, url, request.signal);
    if (view === 'stage_media') return sceneMedia(scoped, roots, url, request);
    if (view === 'dataset') return readDataset(url, roots, request.signal, sessions);
    if (view === 'media') return readMedia(url, roots, request.signal, sessions);
    throw new ApiError('Unsupported workbench view');
  };
}
