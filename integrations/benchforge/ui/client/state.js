export function createWorkbenchState({STAGES, sceneName}) {
  function initialState(sessionId) {
    const fallback = {version: 3, stage: 'S1', run: '', production: '', dataset: '', template: '', split: '', q: '', page: 1, size: 24, layout: 'grid',
      runFilter: '', runListPage: 1, runListSize: 12, versionFilter: '', versionListPage: 1, versionListSize: 12};
    const saved = JSON.parse(localStorage.getItem('bfw:benchforge:' + sessionId) || 'null');
    if (saved?.version === 3) {
      const {tab, ...route} = saved;
      const stage = ({overview: 'S1', runs: 'S1', datasets: 'S4', quality: 'S5'})[tab] || saved.stage;
      return {...fallback, ...route, stage: STAGES.some((row) => row.id === stage) ? stage : 'S1', size: [24, 48, 96].includes(saved.size) ? saved.size : 24,
        page: Number.isSafeInteger(saved.page) && saved.page > 0 ? saved.page : 1,
        runListPage: Number.isSafeInteger(saved.runListPage) && saved.runListPage > 0 ? saved.runListPage : 1,
        versionListPage: Number.isSafeInteger(saved.versionListPage) && saved.versionListPage > 0 ? saved.versionListPage : 1,
        runListSize: [12, 24, 48].includes(saved.runListSize) ? saved.runListSize : 12,
        versionListSize: [12, 24, 48].includes(saved.versionListSize) ? saved.versionListSize : 12,
        layout: saved.layout === 'grid' ? 'grid' : 'table'};
    }
    return fallback;
  }
  function initialDemand(sessionId) {
    const fallback = {version: 1, objective: '', count: '100', capability: '', sceneCount: '', storageBudget: '',
      mode: 'new', executionMode: 'production', quantityContract: 'minimum'};
    const saved = JSON.parse(localStorage.getItem('bfw:production-request:' + sessionId) || 'null');
    if (saved?.version !== 1) return fallback;
    return {...fallback, ...saved,
      executionMode: ['production', 'exploration'].includes(saved.executionMode) ? saved.executionMode : fallback.executionMode,
      quantityContract: ['exact', 'minimum', 'best_effort'].includes(saved.quantityContract) ? saved.quantityContract : fallback.quantityContract};
  }
  function sceneConstraint(selection) {
    if (!selection) return '';
    return '\n场景使用约束（以保存的场景选择为准）：\n' + JSON.stringify({schema: selection.schema,
      selection_path: selection.selection_path, version: selection.version, selected_scenes: selection.sources || selection.selected,
      allow_new_scenes: selection.allow_new_scenes}, null, 2) +
      '\n只允许复用 selected_scenes 中勾选的场景，使用所列 task_id 与 revision 的采集、标注和场景程序。未勾选的已有场景不得用于本次任务。' +
      (selection.allow_new_scenes ? '允许按需求生成新场景，生成后统一登记到场景库。' : '不允许通过新建、复制或重新生成场景绕过选择。') +
      '若所选场景不足以满足要求，如实记录缺口，等待用户调整场景选择。\n';
  }
  function productionRequest(demand, selection) {
    if (demand.mode === 'append') return '请将以下要求应用于当前会话的生产任务，保留已有产物和失败证据，并继续实际执行至完成：\n' + demand.objective.trim() + sceneConstraint(selection);
    return [
      '请实际执行一次 BenchForge 评测数据集生产任务，完整完成五阶段：评测计划、场景生成或复用与采集、标注、按能力模板出题、质量检查与打包交付；不要只写计划。',
      'execution_mode=' + (demand.executionMode || 'production') + '；quantity_contract=' + (demand.quantityContract || 'minimum') + '。',
      '生产需求：' + demand.objective.trim(),
      'target_items=' + Number(demand.count) + '。这是请求目标；按数量合同处理短缺，不得把执行完成表述为数量达标或质量验收通过。',
      demand.capability.trim() ? '能力与模板要求：' + demand.capability.trim() : '请根据上述需求从现有能力图谱和出题模板中拆解并选择适用模板。',
      demand.sceneCount ? '目标场景数：' + Number(demand.sceneCount) + ' 个。' : '',
      demand.storageBudget ? '存储预算上限：' + Number(demand.storageBudget) + ' GB。' : '',
      '使用当前已接入工具。场景是出题前提，GT 仅来自官方、程序或仿真，公开题目不泄露答案。请将计划、场景、标注、题目表和最终报告关联到当前会话，使工作台实时展示实际回执和产物。',
    ].filter(Boolean).join('\n') + sceneConstraint(selection);
  }
  function displayRef(value) {
    const parts = String(value || '').split(/[\\/]/).filter(Boolean);
    if (parts[0] === 'operations' && parts[1]) return '运行 ' + parts[1].slice(0, 8);
    const visible = parts.filter((part) => !['steps', 'questions', 'dataset', 'pipeline_run'].includes(part));
    return visible[visible.length - 1] || String(value || '—');
  }
  function filteredPage(items, query, page, size, searchable) {
    const needle = String(query || '').trim().toLocaleLowerCase();
    const matches = needle ? items.filter((item) => searchable(item).toLocaleLowerCase().includes(needle)) : items;
    const pages = Math.max(1, Math.ceil(matches.length / size));
    const current = Math.min(Math.max(1, page), pages);
    return {items: matches.slice((current - 1) * size, current * size), total: matches.length, pages, page: current};
  }

  const lifecycle = (value) => ({SUCCEEDED: 'completed', FAILED_FINAL: 'failed', CANCELED: 'canceled',
    READY: 'waiting', PENDING: 'waiting', RUNNING: 'running'}[value] || value || 'unknown');
  function backgroundProductionState(value) {
    if (!value) return 'unknown';
    const states = [
      ...(value.pipelines || []).map((row) => lifecycle(row.state)),
      ...(value.parallel_tasks || []).map((row) => lifecycle(row.state)),
      ...(value.scenes?.runs || []).map((row) => lifecycle(row.state)),
      ...(value.operations || []).map((row) => lifecycle(row.state)),
      value.generation ? lifecycle(value.generation.state) : null,
    ].filter(Boolean);
    if (states.includes('running')) return 'running';
    return states.length ? 'idle' : 'unknown';
  }
  function productionProductsRevision(value) {
    const terminal = (state) => ['completed', 'failed', 'canceled'].includes(lifecycle(state)) ? lifecycle(state) : null;
    const sorted = (rows) => rows.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
    const artifacts = (row) => [row.artifact_revision ?? null, row.artifact_count ?? null,
      sorted((row.public_artifacts || []).map((file) => [file.url, file.revision ?? file.version ?? null]))];
    // Live counters and observation timestamps do not invalidate saved products.
    return JSON.stringify([
      sorted((value?.operations || []).filter((row) => terminal(row.state)).map((row) => [row.id, terminal(row.state)])),
      sorted((value?.pipelines || []).map((row) => [row.id, terminal(row.state), row.revision ?? null, artifacts(row),
        sorted((row.steps || []).filter((step) => terminal(step.state)).map((step) => [step.id, terminal(step.state), step.artifact_revision ?? null]))])),
      sorted((value?.scenes?.runs || []).map((row) => [row.run_id, terminal(row.state),
        sorted((row.tasks || []).map((task) => [task.id, task.revision ?? null, terminal(task.state), artifacts(task)]))])),
      sorted((value?.parallel_tasks || []).filter((row) => terminal(row.state) || row.artifact_revision != null ||
        row.artifact_count > 0 || row.public_artifacts?.length).map((row) => [row.id, row.revision ?? null, terminal(row.state), artifacts(row)])),
      value?.current_collection && [value.current_collection.plan_path, value.current_collection.ledger_version,
        value.current_collection.status, sorted((value.current_collection.rows || []).map((row) => [row.design_id, row.task_id, row.revision]))],
      value?.generation && value.generation.state !== 'running' ? [value.generation.run_id || value.generation.plan_path,
        value.generation.state, value.generation.written_count, value.generation.verified_count, value.generation.published_count] : null,
    ]);
  }
  const sceneStage = (row) => row.workflow === 'scene' ? 'S2' : row.workflow === 'dataset' ? 'S4' :
    ({review: 'S5', publish: 'S5', export: 'S5', dataset: 'S4', annotate: 'S3'}[row.phase] || 'S2');
  function pipelineForStage(id, pipelines) {
    const latest = (stage) => pipelines.filter((row) => row.steps?.some((step) => step.stage === stage))
      .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))[0];
    return latest(id) || (id === 'S3' ? latest('S2') : null);
  }
  function sceneForStage(id, scenes) {
    const candidates = scenes.filter((scene) => scene.tasks?.some((task) => sceneStage(task) === id ||
      id === 'S3' && sceneStage(task) === 'S2'));
    const usable = candidates.filter((scene) => scene.state !== 'CANCELED');
    return usable.find((scene) => !scene.terminal && scene.state !== 'FAILED_FINAL') ||
      usable.find((scene) => scene.state === 'SUCCEEDED') || usable[0] || candidates[0];
  }
  function progressSceneForStage(id, selected, scenes = []) {
    const active = scenes.filter((row) => !row.terminal && !['SUCCEEDED', 'FAILED_FINAL', 'CANCELED'].includes(row.state) &&
      row.tasks?.some((task) => sceneStage(task) === id));
    if (!active.length) return selected;
    const seen = new Set();
    const tasks = active.flatMap((row) => row.tasks || []).filter((task) => {
      const key = task.id + ':' + task.revision;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
    return {state: active.some((row) => row.state === 'RUNNING') ? 'RUNNING' : active[0].state, tasks};
  }
  function registeredCollectionProgress(plan, current) {
    const design = plan?.assessment?.scenes;
    const targets = design?.designs || [];
    const total = Number(design?.target_scene_count ?? plan?.inputs?.target_scene_count) || targets.length;
    const saved = new Map((current.rows || []).map((row) => [row.design_id, row]));
    const accepted = (current.rows || []).filter((row) => row.state === 'completed').length;
    const trusted = current.status === 'current' && current.target === total && targets.length === total &&
      saved.size === total && targets.every((row) => saved.has(row.id)) && current.accepted === accepted &&
      (current.rows || []).every((row) => ['completed', 'waiting'].includes(row.state));
    const rows = targets.map((target) => {
      const row = trusted ? saved.get(target.id) : null;
      const passed = row?.state === 'completed';
      return {id: target.id, scene_id: row?.scene_id || target.scene_id, run_id: row?.run_id,
        name: row?.name || sceneName(target.name) || '场景', state: passed ? 'completed' : 'waiting',
        statusLabel: passed ? 'scenePassed' : 'scenePending', phase: passed ? 'sceneNativeAccepted' : 'scenePending'};
    });
    return {rows, total, passed: trusted ? accepted : 0, state: trusted && accepted === total && total > 0 ? 'completed' : 'waiting',
      identityPending: !trusted, current: true, registrationStatus: current.status,
      notice: current.status === 'pending' ? 'scenePlanPending' : !trusted ? 'sceneSnapshotUnavailable' : null};
  }
  function currentGeneration(value) {
    if (!value || !['current_applied_plan', 'current_plan_path_after_save'].includes(value.association) ||
        !Number.isSafeInteger(value.target_items) || value.target_items < 1 ||
        !Number.isSafeInteger(value.written_count) || !Number.isSafeInteger(value.verified_count) ||
        value.written_count < 0 || value.verified_count < 0 || value.written_count > value.target_items ||
        value.verified_count > value.target_items) return null;
    const heartbeat = value.heartbeat_at ?? value.updated_at;
    const age = Date.now() / 1000 - heartbeat;
    const fresh = value.fresh === true && Number.isFinite(age) && age >= 0 && age <= 30 && value.process_alive !== false;
    const eligible = value.contract_eligible_count;
    if (eligible != null && (!Number.isSafeInteger(eligible) || eligible < 0 || eligible > value.verified_count)) return null;
    const incomplete = value.state === 'complete' && (value.written_count !== value.target_items || value.verified_count !== value.target_items ||
      eligible != null && eligible !== value.target_items);
    return {...value, fresh, state: incomplete || value.state === 'running' && !fresh ? 'incomplete' : value.state};
  }
  function sceneCollectionProgress(plan, scenes = [], current = null) {
    if (current) return registeredCollectionProgress(plan, current);
    const design = plan?.assessment?.scenes;
    const declared = Number(design?.target_scene_count ?? plan?.inputs?.target_scene_count);
    const total = Number.isInteger(declared) && declared > 0 ? declared :
      design?.designs?.length || design?.selected_scenes?.length || 0;
    const targets = (design?.designs || []).map((row) => ({
      // This is a declared program filename, not a guess from a display name.
      id: row.scene_id || String(row.program_path || row.artifact || '').match(/([^/\\\s]+)\.scene_program\.json\b/)?.[1],
      name: row.name,
    })).filter((row) => row.id);
    const targetIds = new Set(targets.map((row) => row.id));
    const boundPlan = total > 0 && targetIds.size === total;
    const timestamp = (value) => {
      if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) {
        const number = Number(value); return number < 1e12 ? number * 1000 : number;
      }
      return Date.parse(value) || 0;
    };
    const latest = new Map();
    for (const run of scenes) {
      const tasks = (run.tasks || []).filter((task) => task.workflow === 'scene' ||
        sceneStage(task) === 'S2' && task.workflow !== 'asset');
      if (!tasks.length && (run.tasks?.length || !run.scene_id || !run.state)) continue;
      const groups = new Map();
      for (const task of tasks.length ? tasks : [null]) {
        const key = task?.scene_id || run.scene_id || run.run_id;
        if (!key) continue;
        groups.set(key, [...(groups.get(key) || []), task]);
      }
      for (const [key, candidates] of groups) {
        const task = candidates.filter(Boolean).sort((a, b) => (Number(b.revision) || 0) - (Number(a.revision) || 0) ||
          timestamp(b.updated_at || b.created_at) - timestamp(a.updated_at || a.created_at))[0];
        if (!run.state && !task?.state && !task?.queue) continue;
        const sceneId = task?.scene_id || run.scene_id;
        if (boundPlan && sceneId && !targetIds.has(sceneId)) continue;
        const created = timestamp(task?.created_at || run.created_at || run.updated_at || task?.updated_at);
        const updated = timestamp(run.updated_at || task?.updated_at || run.created_at);
        const candidate = {run, task, sceneId, created, updated};
        const prior = latest.get(key);
        if (!prior || created > prior.created || created === prior.created && updated > prior.updated) latest.set(key, candidate);
      }
    }
    const observed = [...latest.values()].map(({run, task, sceneId}) => {
      const nativeState = lifecycle(task?.state || run.state);
      const phase = task?.progress?.stage || task?.phase || run.progress?.stage || '';
      const acceptance = task?.acceptance?.passed ?? task?.acceptance_passed ?? run.acceptance?.passed ?? run.acceptance_passed;
      let state = 'waiting', label = 'scenePending';
      if (nativeState === 'completed' && acceptance !== false) {
        state = 'completed'; label = 'scenePassed';
      } else if (nativeState === 'failed' || acceptance === false && nativeState === 'completed') {
        state = 'failed'; label = 'sceneNeedsRepair';
      } else if (nativeState === 'canceled') {
        state = 'canceled'; label = 'sceneStopped';
      } else if (task?.queue || run.queue || nativeState === 'waiting') {
        state = 'waiting'; label = 'sceneQueued';
      } else if (nativeState === 'running' || lifecycle(run.state) === 'running') {
        state = 'running'; label = /repair|revis|retry/i.test(phase) ? 'sceneRepairing' : 'sceneCapturing';
      }
      return {id: sceneId || run.run_id, scene_id: sceneId, run_id: run.run_id,
        name: task?.name || run.name || sceneId || run.run_id, state, statusLabel: label,
        phase, task, error: task?.failure || task?.progress?.error || run.failure};
    });
    const rows = boundPlan ? [...targets.map((target) => observed.find((row) => row.scene_id === target.id) ||
      {id: target.id, scene_id: target.id, name: target.name || target.id, state: 'waiting', statusLabel: 'scenePending'}),
      ...observed.filter((row) => !row.scene_id)] : observed;
    if (!total && !rows.length) return null;
    const identityPending = rows.some((row) => !row.scene_id) || total > 0 && rows.length > total;
    const passed = rows.filter((row) => row.state === 'completed' && row.scene_id).length;
    const state = total > 0 && !identityPending && rows.length === total && passed === total ? 'completed' :
      rows.some((row) => row.state === 'running') ? 'running' : rows.some((row) => row.state === 'failed') ? 'failed' :
      rows.length && rows.every((row) => row.state === 'canceled') ? 'canceled' : 'waiting';
    return {rows, total, passed, state, identityPending};
  }
  function annotationProducts(artifacts) {
    return artifacts.filter((row) => row.stage === 'S3' && row.kind === 'json' && artifacts.some((image) =>
      image.kind === 'image' && image.task_id === row.task_id && image.revision === row.revision &&
      image.file === row.file?.replace(/\.json$/, '.png')));
  }
  function stageState(id, pipeline, scene, operations = [], planReceipt = null, artifacts = [], collection = null, generation = null) {
    const generated = id === 'S4' ? currentGeneration(generation) : null;
    if (generated?.state === 'running' && generated.fresh) return 'running';
    if (generated?.state === 'failed') return 'failed';
    if (generated?.state === 'incomplete') return 'needs_evidence';
    const recorded = recordedStageState(id, pipeline, scene, operations, planReceipt, artifacts, collection);
    if (generated?.state === 'complete' && pipeline?.steps?.some((row) => row.stage === id) && recorded !== 'unknown') return recorded;
    return generated?.state === 'complete' && recorded !== 'completed' ? 'waiting' : recorded;
  }
  function recordedStageState(id, pipeline, scene, operations = [], planReceipt = null, artifacts = [], collection = null) {
    if (id === 'S1' && planReceipt) return 'completed';
    if (id === 'S2' && collection) return collection.state;
    const current = (scene?.tasks || []).filter((row) => sceneStage(row) === id);
    if (current.length) {
      if (scene.state === 'CANCELED' && current.some((row) => row.state !== 'SUCCEEDED')) return 'canceled';
      if (current.some((row) => row.state === 'FAILED_FINAL')) return 'failed';
      if (current.some((row) => row.queue) && !current.some((row) => row.state === 'RUNNING' && !row.queue)) return 'waiting';
      if (current.every((row) => row.state === 'SUCCEEDED')) {
        const parentSteps = (pipeline?.steps || []).filter((row) => row.stage === id);
        return parentSteps.some((row) => row.state !== 'completed')
          ? stageState(id, pipeline, null, operations, planReceipt, artifacts) : 'completed';
      }
      if (current.some((row) => row.state === 'RUNNING')) return 'running';
      return lifecycle(scene.state);
    }
    const steps = (pipeline?.steps || []).filter((row) => row.stage === id);
    if (!steps.length) {
      if (id === 'S3' && annotationProducts(artifacts).length) {
        const capture = (pipeline?.steps || []).filter((row) => row.stage === 'S2');
        const views = artifacts.filter((row) => row.stage === 'S2' && row.kind === 'image' && /^capture\/view_\d+\.png$/.test(row.file || ''));
        const labels = annotationProducts(artifacts);
        const paired = views.length && views.every((view) => labels.some((label) => label.task_id === view.task_id &&
          label.revision === view.revision && label.file === view.file.replace(/\.png$/, '.json')));
        const settled = scene?.state === 'SUCCEEDED' || capture.length && capture.every((row) => row.state === 'completed');
        return paired && settled ? 'completed' : 'previewable';
      }
      if (pipeline || scene) return 'unknown';
      const recorded = operations.filter((row) => row.stage === id);
      return recorded.find((row) => row.state === 'running')?.state || recorded[0]?.state || 'unknown';
    }
    if (steps.every((row) => row.state === 'completed')) return 'completed';
    return steps.find((row) => row.state !== 'completed' && row.state !== 'unknown')?.state ||
      (pipeline.current?.stage === id && pipeline.state !== 'completed' ? pipeline.state : 'unknown');
  }
  return {initialState, initialDemand, sceneConstraint, productionRequest, displayRef, filteredPage,
    lifecycle, backgroundProductionState, productionProductsRevision, sceneStage, pipelineForStage, sceneForStage, progressSceneForStage,
    registeredCollectionProgress, currentGeneration, sceneCollectionProgress, annotationProducts, stageState,
    recordedStageState};
}
