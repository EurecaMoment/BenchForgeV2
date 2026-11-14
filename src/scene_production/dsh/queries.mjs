import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {Readable} from 'node:stream';
import {ApiError, assertSessionDirectory, inside, readJson, resolveToken, scopeOf} from '../../dsh/host/session_scope.mjs';

const execute = promisify(execFile);

export function createSceneQueries({workbenchUrl, pipelineSceneIds}) {
  function previewMediaKey(config, roots, url) {
    return JSON.stringify([config.productionConfig, roots.map((root) => root.path),
      ...['session_id', 'scene', 'run', 'task', 'revision', 'library'].map((key) => url.searchParams.get(key) || '')]);
  }

  async function sceneLibrary(config, roots, url, signal, selection) {
    const session = url.searchParams.get('session_id') || '';
    if (roots.length !== 1 || !config.productionConfig || !/^session-[a-zA-Z0-9-]+$/.test(session)) {
      throw new ApiError('A registered workspace and conversation are required for the scene library', 403);
    }
    const action = selection ? 'save' : url.searchParams.get('view') === 'scene_selection' ? 'selection' : 'list';
    const helper = 'scene_production.server.scene_library.scene_library';
    const args = ['-B', '-m',helper, '--config', config.productionConfig, '--workspace', roots[0].path,
      '--session', session, '--action', action, '--page', String(Math.max(1, Number(url.searchParams.get('page')) || 1)),
      '--query', (url.searchParams.get('q') || '').slice(0, 300), '--origin', url.searchParams.get('origin') || 'all',
      '--size',String(Math.max(1,Math.min(24,Number(url.searchParams.get('page_size')) || 12)))];
    if (selection) args.push('--value', JSON.stringify(selection));
    const key = JSON.stringify([roots[0].path, session, args.slice(9)]);
    const cached = action === 'list' && config._libraryCache.get(key);
    if (cached && cached.expires > Date.now()) return cached.value;
    const previous = config._libraryQueue.get(roots[0].path) || Promise.resolve();
    const job = previous.catch(() => {}).then(async () => {
      if (action === 'list' && signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      // Finish atomic index/selection writes even if a search query or tab is replaced.
      const {stdout} = await execute(config.productionPython, args, {timeout: 20000, maxBuffer: 3 * 1024 * 1024});
      const result = JSON.parse(stdout);
      if (result.error) throw new ApiError(result.error, result.status_code || 503);
      return result;
    });
    config._libraryQueue.set(roots[0].path, job);
    const value = await job;
    if (action !== 'list') {config._libraryCache.clear(); return value;}
    const scenes = [];
    const result = {...value, items: value.items.map((row) => {
      const link = (file) => workbenchUrl({view: 'stage_media', library: '1', scene: row.run_id, session_id: session,
        task: row.task_id, revision: String(row.revision), file}, roots[0].path);
      let video = null;
      if (row.video) {
        const {source_path, ...publicVideo} = row.video;
        video = {...publicVideo, url: link(row.video.file)};
        const mediaUrl = new URL(video.url, url);
        config._previewMedia.set(previewMediaKey(config, roots, mediaUrl), {source_path,
          content_type: 'video/mp4', expires: Date.now() + 30000});
        if (config._previewMedia.size > 256) config._previewMedia.delete(config._previewMedia.keys().next().value);
      } else if (row.available) scenes.push({run_id: row.run_id, tasks: [{id: row.id, revision: row.revision, state: 'SUCCEEDED'}]});
      return {...row, frames: row.frames.map((frame) => ({...frame, url: link(frame.file)})), video};
    })};
    scheduleSceneMovies(config, session, scenes, [...new Set(scenes.map((row) => row.run_id))]);
    if (config._libraryCache.size >= 24) config._libraryCache.delete(config._libraryCache.keys().next().value);
    config._libraryCache.set(key, {expires: Date.now() + 30000, value: result});
    return result;
  }

  function scheduleSceneMovies(config, session, scenes, runIds = []) {
    if (!config.productionConfig || !config._previewJobs || !/^session-[a-zA-Z0-9-]+$/.test(session)) return;
    for (const scene of scenes.filter((row) => /^sf_[a-zA-Z0-9_-]+$/.test(row.run_id) &&
      row.tasks?.some((task) => task.state === 'SUCCEEDED'))) {
      const key = JSON.stringify([session, scene.run_id, scene.tasks.filter((task) => task.state === 'SUCCEEDED').map((task) => [task.id, task.revision])]);
      const previous = config._previewJobs.get(key);
      if (previous && (!previous.error || Date.now() - previous.time < 60000)) continue;
      const job = {time: Date.now(), error: false};
      config._previewJobs.set(key, job);
      if (config._previewJobs.size > 96) config._previewJobs.delete(config._previewJobs.keys().next().value);
      // One CPU encoder at a time, started by the production observation rather than a preview click.
      config._previewQueue = config._previewQueue.then(async () => {
        const helper = 'scene_production.server.scene_library.scene_preview_video';
        const {stdout} = await execute(config.productionPython, ['-B', '-m',helper, '--config', config.productionConfig,
          '--session', session, '--scene', scene.run_id, '--run-ids', JSON.stringify(runIds)],
        {timeout: 60000, maxBuffer: 2 * 1024 * 1024});
        const value = JSON.parse(stdout);
        if (value.error) throw new Error('Scene movie export did not complete');
      }).catch(() => {job.error = true; job.time = Date.now();});
    }
  }

  async function associatedCaptures(roots, scope, associations) {
    if (scope.history || !/^session-[A-Za-z0-9-]+$/.test(scope.session_id)) return [];
    await associations?.warm(scope.session_id);
    const captures = [];
    for (const root of roots) {
      const file = path.join(root.path, '.benchforge', 'capture-associations', scope.session_id + '.json');
      const saved = await readJson(file);
      if (!saved || saved.context?.session_id !== scope.session_id) continue;
      await inside(root, file);
      for (const row of saved.captures || []) if (/^sf_[A-Za-z0-9_-]+$/.test(row.run_id || '')) captures.push(row.run_id);
    }
    return [...new Set(captures.reverse())];
  }

  async function sceneArtifacts(config, roots, url, signal, media = false) {
    const session = url.searchParams.get('session_id') || '', scene = url.searchParams.get('scene') || '';
    if (!roots.length || !config.productionConfig || !/^session-[a-zA-Z0-9-]+$/.test(session) || !/^sf_[a-zA-Z0-9_-]+$/.test(scene)) {
      throw new ApiError('A registered workspace and session-owned scene are required', 403);
    }
    const library = url.searchParams.get('library') === '1';
    const helper = (library ? 'scene_production.server.scene_library.scene_library' : 'scene_production.server.scene_library.observations');
    const args = ['-B', '-m',helper, '--config', config.productionConfig, '--session', session,
      '--action', media ? 'file' : 'artifacts', ...(library ? ['--workspace', roots[0].path] : ['--scene', scene])];
    if (!library && config._sessionIds?.length) args.push('--sessions', JSON.stringify(config._sessionIds));
    if (!library && config._captureIds?.length) args.push('--run-ids', JSON.stringify(config._captureIds));
    const run = url.searchParams.get('run');
    if (library && run) throw new ApiError('Library scenes use their saved catalog identity', 403);
    if (run) {
      const {root, directory} = await resolveToken(run, roots);
      await assertSessionDirectory(root, directory, scopeOf(url, config._sessionIds));
      const state = await readJson(path.join(directory, 'state.json'));
      const sceneIds = pipelineSceneIds(state);
      if (!sceneIds.includes(scene)) throw new ApiError('Scene is not referenced by this pipeline', 403);
      args.push('--run-ids', JSON.stringify(sceneIds));
    }
    if (media || library) args.push('--task', url.searchParams.get('task') || '', '--revision', url.searchParams.get('revision') || '');
    if (media) args.push('--file', url.searchParams.get('file') || '');
    const {stdout} = await execute(config.productionPython, args, {signal, timeout: 12000, maxBuffer: 2 * 1024 * 1024});
    const result = JSON.parse(stdout);
    if (result.error) throw new ApiError(result.error, result.status_code || 503);
    if (media) return result;
    for (const row of result.items || []) if (row.file === 'preview/scene.mp4' && row.source_path && config._previewMedia) {
      const mediaUrl = new URL(url);
      mediaUrl.searchParams.set('task', row.task_id); mediaUrl.searchParams.set('revision', String(row.revision));
      config._previewMedia.set(previewMediaKey(config, roots, mediaUrl), {source_path: row.source_path,
        content_type: 'video/mp4', expires: Date.now() + 30000});
    }
    if (result.state === 'SUCCEEDED' && !(result.items || []).some((row) => row.file === 'preview/scene.mp4')) {
      const tasks = [...new Map((result.items || []).map((row) => [row.task_id,
        {id: row.task_id, revision: row.revision, state: 'SUCCEEDED'}])).values()];
      scheduleSceneMovies(config, session, [{run_id: scene, tasks}], run ? [scene] : []);
    }
    return {...result, items: (result.items || []).map(({source_path, ...row}) => ({...row,
      url: workbenchUrl({view: 'stage_media', scene, session_id: session, ...(library ? {library: '1'} : {}), ...(run ? {run} : {}), task: row.task_id,
        revision: String(row.revision), file: row.file}, roots[0].path)})), snapshot_at: new Date().toISOString()};
  }

  async function sceneMedia(config, roots, url, request) {
    const cached = url.searchParams.get('file') === 'preview/scene.mp4' && config._previewMedia?.get(previewMediaKey(config, roots, url));
    const file = cached && cached.expires > Date.now() ? cached : await sceneArtifacts(config, roots, url, request.signal, true);
    if (file.data !== undefined) return Response.json(file.data, {headers: {'cache-control': 'no-store'}});
    const stat = await fs.stat(file.source_path), headers = {'content-type': file.content_type,
      'cache-control': 'private, max-age=30', 'x-content-type-options': 'nosniff', 'accept-ranges': 'bytes'};
    let start = 0, end = stat.size - 1, status = 200;
    const range = request.headers.get('range');
    if (range) {
      const match = /^bytes=(\d+)-(\d*)$/.exec(range);
      if (!match) throw new ApiError('Invalid media range', 416);
      start = Number(match[1]); end = match[2] ? Math.min(Number(match[2]), end) : end;
      if (start > end || start >= stat.size) throw new ApiError('Media range is outside the file', 416);
      headers['content-range'] = `bytes ${start}-${end}/${stat.size}`; status = 206;
    }
    headers['content-length'] = String(end - start + 1);
    return new Response(Readable.toWeb(createReadStream(file.source_path, {start, end, signal: request.signal})), {status, headers});
  }

  return {sceneLibrary, sceneArtifacts, sceneMedia, scheduleSceneMovies, associatedCaptures};
}
