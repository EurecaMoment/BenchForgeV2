export function createProgressComponents({React, helpers}) {
  const h = React.createElement;
  const {status, button, card, empty, json, sceneName, questionText, planValue, planMarkdown,
  planMarkdownView, planEditInstruction, table, select, initialState, initialDemand, sceneConstraint,
  productionRequest, displayRef, filteredPage, useRecord, usePanelVisible, lifecycle,
  productionProductsRevision, sceneStage, pipelineForStage, sceneForStage, progressSceneForStage,
  registeredCollectionProgress, currentGeneration, sceneCollectionProgress, annotationProducts,
  stageState, recordedStageState,
  STAGES, PLAN_SECTIONS, PLAN_FIELDS, styles, dictionaries} = helpers;
  function TemplateCatalog({catalog, catalogQuery, setCatalogQuery, catalogPage, setCatalogPage,
    capability, setCapability, retry, t}) {
    return h('details', {'data-template-reference': true}, h('summary', null, t('templateCatalog')),
      h('small', {className: 'bfw-hint'}, t('catalogDesign')),
      h('div', {className: 'bfw-toolbar'},
        h('input', {className: 'bfw-input', 'aria-label': t('searchTemplates'), value: catalogQuery,
          placeholder: t('searchTemplates'), onChange: (e) => {setCatalogQuery(e.target.value); setCatalogPage(1);}}),
        select(t('capability'), capability, (id) => {setCapability(id); setCatalogPage(1);},
          [['', t('all')], ...(catalog.value?.capabilities || []).map((id) => [id, id])])),
      catalog.loading ? empty(t('loading')) : catalog.error ? h('div', null,
        h('p', {className: 'bfw-error'}, catalog.error), button(t('retry'), retry)) :
        !catalog.value?.items.length ? empty(t('noMatchingTemplates')) :
          h('div', {className: 'bfw-catalog'}, catalog.value.items.map((row) =>
            h('article', {className: 'bfw-template', key: row.id}, h('strong', null, row.title),
              h('p', {className: 'bfw-code'}, row.id + ' · ' + row.capabilities.join(' / ')),
              h('details', null, h('summary', null, t('details')),
                h('p', null, row.effective_measurement_conditions), h('p', null, row.prompt_template))))),
      h('div', {className: 'bfw-pagination'}, button(t('previous'), () => setCatalogPage(catalogPage - 1), {disabled: catalogPage <= 1}),
        h('span', null, catalogPage + ' / ' + (catalog.value?.pages || 1)),
        button(t('nextPage'), () => setCatalogPage(catalogPage + 1), {disabled: catalog.loading || !catalog.value || catalogPage >= catalog.value.pages})));
  }
  function RunDetails({record, t}) {
    if (!record) return empty(t('chooseRun'));
    const artifacts = record.artifacts || [];
    return h(React.Fragment, null,
      card(record.label, h(React.Fragment, null,
        h('div', null, status(record.state.state, t)),
        record.state.next && h('p', null, t('next') + ': ' + record.state.next),
        record.state.missing_binding && h('p', {className: 'bfw-code'}, record.state.missing_binding),
        table([t('steps'), t('state'), t('artifacts'), t('reason')], record.steps.map((step) => [step.id, status(step.state, t), h('span', {className: 'bfw-code'}, step.artifact_id || '—'), step.error || '—'])),
        record.plan && h('details', {className: 'bfw-detail-row'}, h('summary', null, t('plan')), json(record.plan)))),
      h('div', {className: 'bfw-details'},
        card(t('lineage'), h(React.Fragment, null,
          h('small', {className: 'bfw-hint'}, t('shapeNote')),
          record.artifacts_truncated && h('p', null, t('truncated')),
          artifacts.length ? artifacts.map((artifact) => h('details', {className: 'bfw-artifact', key: artifact.artifact_id},
            h('summary', null, status(artifact.status, t), ' ', artifact.artifact_type, ' · v', artifact.version),
            h('div', {className: 'bfw-code bfw-detail-row'}, artifact.artifact_id),
            h('div', {className: 'bfw-detail-row'}, t('producer') + ': ' + artifact.producer),
            h('div', {className: 'bfw-detail-row'}, t('parents')), json(artifact.parents),
            h('div', {className: 'bfw-detail-row'}, t('evidence')), json(artifact.evidence_refs),
            h('div', {className: 'bfw-detail-row'}, t('contracts')), json(artifact.contract_results))) : empty(t('noArtifacts')))),
        card(t('repairs'), h(React.Fragment, null,
          h('small', {className: 'bfw-hint'}, t('repairNote')),
          record.repairs.length ? record.repairs.map((repair, i) => h('details', {className: 'bfw-artifact', key: i},
            h('summary', null, status(repair.status, t), ' ', t(repair.operator)),
            h('div', {className: 'bfw-code bfw-detail-row'}, repair.artifact_id),
            h('p', null, t('reason') + ': ' + repair.reason),
            h('p', null, t('repairScope') + ': ' + repair.scope),
            h('p', null, t('newRun') + ': ' + t(repair.requires_new_run ? 'yes' : 'no')))) : empty(t('noRepairs'))))));
  }
  function executionStage(viewed, states, running, parallelTasks = [], generation = null) {
    const generated = currentGeneration(generation);
    if (generated?.state === 'running' && generated.fresh) return STAGES.find((row) => row.id === 'S4');
    const active = parallelTasks.filter((row) => lifecycle(row.state) === 'running');
    if (!running && !active.length) return viewed;
    return STAGES.find((row) => ['running', 'failed', 'canceled'].includes(states[row.id])) ||
      STAGES.find((row) => active.some((task) => task.stage === row.id)) ||
      STAGES.find((row) => states[row.id] === 'waiting') || {id: 'execution', key: 'productionProgress'};
  }
  function reportedProgress(value) {
    if (!value || value.interrupted) return null;
    const pairs = [['bytes_received', 'total_bytes', 'progressUpload'], ['completed', 'total', 'progressItems']];
    for (const [doneKey, totalKey, label] of pairs) {
      const done = value[doneKey], total = value[totalKey];
      if (Number.isFinite(done) && Number.isFinite(total) && total > 0 && done >= 0) {
        return {done: Math.min(done, total), total, label, bytes: totalKey === 'total_bytes'};
      }
    }
    return null;
  }
  function progressAmount(detail) {
    return detail.bytes ? (detail.done / 1048576).toFixed(1) + ' / ' + (detail.total / 1048576).toFixed(1) + ' MB' :
      detail.done + ' / ' + detail.total;
  }
  function ParallelProgress({tasks = [], stage, titleKey = 'parallelTasks', t}) {
    const rows = tasks.filter((row) => !row.stage || stage.id === 'execution' || row.stage === stage.id).map((row, index) => ({...row,
      display_name: row.display_name || row.label || row.name || t('parallelTask') + ' ' + (index + 1)}));
    if (!rows.length) return null;
    const completed = rows.filter((row) => lifecycle(row.state) === 'completed');
    const active = rows.filter((row) => lifecycle(row.state) !== 'completed');
    const caption = completed.length ? t('parallelCompleted') + ' ' + completed.length :
      t('parallelRunning') + ' ' + rows.filter((row) => lifecycle(row.state) === 'running').length;
    const publicFiles = (row) => (row.public_artifacts || []).filter((file) => {
      if (typeof file.url !== 'string' || file.url.includes('\\')) return false;
      const match = /^\/?api\/benchforge\/workbench\?(.+)$/.exec(file.url);
      return match && ['run_product', 'stage_media', 'media'].includes(new URLSearchParams(match[1]).get('view'));
    });
    const renderTask = (row) => {
      const state = lifecycle(row.state);
      const detail = reportedProgress(row.progress) || reportedProgress(row);
      const files = publicFiles(row);
      const count = Number.isSafeInteger(row.artifact_count) && row.artifact_count >= 0 ? row.artifact_count : files.length;
      const name = row.display_name;
      return h('article', {className: 'bfw-parallel-task', key: row.id, 'data-parallel-task': row.id, 'data-task-state': state},
        h('div', {className: 'bfw-parallel-task-heading'}, h('strong', {title: name}, name), status(state, t)),
        detail && h('progress', {max: detail.total, value: detail.done, 'aria-label': name + ' · ' + t(detail.label)}),
        detail && h('small', {className: 'bfw-parallel-task-count'}, t(detail.label) + ' ' + progressAmount(detail)),
        count > 0 && h('small', {className: 'bfw-parallel-task-count'}, t('parallelArtifacts') + ' ' + count),
        files.length > 0 && h('div', {className: 'bfw-parallel-links'}, files.slice(0, 3).map((file, i) =>
          h('a', {key: file.url, href: file.url, target: '_blank', rel: 'noopener noreferrer'}, file.title || t('parallelOpenArtifact') + ' ' + (i + 1)))));
    };
    return h('div', {className: 'bfw-parallel', 'data-parallel-tasks': true, 'aria-label': t(titleKey)},
      h('div', {className: 'bfw-parallel-heading'}, h('strong', null, t(titleKey)),
        h('span', {className: 'bfw-muted'}, caption + ' / ' + rows.length)),
      active.length > 0 && h('div', {className: 'bfw-parallel-grid'}, active.map(renderTask)),
      completed.length > 0 && h('details', {className: 'bfw-parallel-completed', open: false},
        h('summary', null, t('parallelCompleted') + ' ' + completed.length), h('div', {className: 'bfw-parallel-grid'}, completed.map(renderTask))));
  }
  function StageProgress({stage, pipeline, scene, record, planReceipt, collectionPlan, artifacts = [], conversationRunning = false, completedStages = 0, t}) {
    const collection = stage.id === 'S2' && (collectionPlan?.assessment?.scenes || collectionPlan?.inputs?.target_scene_count || record.value?.current_collection)
      ? sceneCollectionProgress(collectionPlan, record.value?.scenes?.runs || [], record.value?.current_collection) : null;
    const generation = stage.id === 'S4' ? currentGeneration(record.value?.generation) : null;
    scene = progressSceneForStage(stage.id, scene, record.value?.scenes?.runs || []);
    const tasks = (scene?.tasks || []).filter((row) => sceneStage(row) === stage.id);
    const operations = !pipeline && !scene ? (record.value?.operations || []).filter((row) => row.stage === stage.id) : [];
    const savedSteps = collection ? collection.rows.map((row) => ({id: row.name, state: row.state,
      label: collection.current ? t(row.phase) : row.phase, error: row.error, queue: row.task?.queue})) : stage.id === 'S1' && planReceipt ? [planReceipt] : scene ? tasks.map((row) => ({id: row.id,
      state: scene.state === 'CANCELED' && row.state !== 'SUCCEEDED' ? 'canceled' : lifecycle(row.state),
      label: row.progress?.stage || row.phase, error: row.failure || row.progress?.error,
      queue: row.queue, age: row.progress?.age_seconds, progress: row.progress})) : (pipeline?.steps || []).filter((row) => row.stage === stage.id)
      .map((row) => ({...row, label: row.uses})).concat(operations.map((row) => ({...row, label: row.tool})));
    const generationPhase = generation && t({selecting: 'generationSelecting', surface_oracle: 'generationOracle',
      writing: 'generationWriting', complete: 'generationComplete'}[generation.phase] || 'questionGeneration');
    const steps = generation ? [{id: t('questionGeneration'), state: generation.state === 'complete' ? 'waiting' :
      generation.state === 'incomplete' ? 'needs_evidence' : generation.state, label: generationPhase}] : savedSteps;
    const history = collection?.current ? (record.value?.scenes?.runs || []).flatMap((run) =>
      (run.tasks || []).filter((task) => sceneStage(task) === 'S2').map((task) => ({id: sceneName(task.name || task.summary?.name) || t('progressTasks'),
        state: run.state === 'CANCELED' && task.state !== 'SUCCEEDED' ? 'canceled' : lifecycle(task.state),
        label: task.progress?.stage || task.phase}))) : [];
    const completed = steps.filter((row) => row.state === 'completed').length;
    const current = steps.find((row) => ['running', 'waiting', 'needs_evidence', 'failed'].includes(row.state)) ||
      steps.find((row) => row.state !== 'completed');
    const recordedState = stageState(stage.id, pipeline, scene, operations, planReceipt, artifacts, collection, generation);
    const currentChildren = (record.value?.parallel_tasks || []).filter((row) => lifecycle(row.state) === 'running' &&
      (stage.id === 'execution' || row.stage === stage.id));
    const state = recordedState === 'unknown' && (conversationRunning || currentChildren.length) ||
      recordedState === 'completed' && currentChildren.length ? 'running' : recordedState;
    const parallelUnknown = !generation && currentChildren.length > 0 && !current;
    const products = stage.id === 'S3' && !steps.length ? annotationProducts(artifacts) : [];
    const productTotal = products.length ? artifacts.filter((row) => row.stage === 'S2' && row.kind === 'image' &&
      /^capture\/view_\d+\.png$/.test(row.file || '')).length : 0;
    const stale = record.error || (collection?.current ? collection.registrationStatus === 'unavailable' :
      generation ? false : ['partial', 'unavailable'].includes(record.value?.scenes?.status));
    // A list of recent operations is history, not a declared workload total.
    const readings = tasks.map((row) => reportedProgress(row.progress));
    const sharedMeasure = tasks.length > 1 && readings.every(Boolean) && readings.every((row) =>
      row.label === readings[0].label && row.bytes === readings[0].bytes) &&
      new Set(tasks.map((row) => row.progress?.stage || row.phase)).size === 1;
    const checked = generation?.contract_eligible_count ?? generation?.verified_count;
    const checkLabel = Number.isSafeInteger(generation?.contract_eligible_count) ? 'generationEligible' : 'generationVerified';
    const repairTarget = generation?.repair_target_count ?? generation?.repair_candidate_target ??
      (generation ? generation.written_count - checked : 0);
    const detail = generation ? {done: generation.written_count === generation.target_items || generation.state === 'incomplete'
      ? checked : generation.written_count, total: generation.target_items,
      label: generation.written_count === generation.target_items || generation.state === 'incomplete' ? checkLabel : 'generationWritten'} :
      !collection && current && !parallelUnknown && !['failed', 'canceled'].includes(state) ? sharedMeasure
      ? {...readings[0], done: readings.reduce((sum, row) => sum + row.done, 0), total: readings.reduce((sum, row) => sum + row.total, 0)}
      : tasks.length > 1 ? null : reportedProgress(current.progress) : null;
    // A whole-task count cannot describe work still occurring within that task.
    const activeUnknown = state === 'running' && (parallelUnknown || current && !detail);
    const total = collection ? collection.identityPending ? 0 : collection.total : detail?.total ||
      (activeUnknown || operations.length && !(stage.id === 'S1' && planReceipt) ? 0 : steps.length || productTotal);
    const done = collection ? collection.passed : detail?.done ?? (steps.length ? completed : products.length);
    const measured = total > 0;
    const percent = measured ? Math.min(100, Math.round(done / total * 100)) : null;
    const moving = ['running', 'previewable'].includes(state);
    const metric = measured ? (generation ? t(detail.label) + ' ' : '') + percent + '%' : t(state === 'completed' ? 'stageDone' : moving ? 'progressPending' :
      ['failed', 'canceled'].includes(state) ? 'progressPaused' : 'progressWaiting');
    const unit = t(collection ? 'scenePassed' : detail?.label || (products.length ? 'progressProducts' : scene ? 'progressTasks' : 'progressSteps'));
    const amount = detail?.bytes ? (done / 1048576).toFixed(1) + ' / ' + (total / 1048576).toFixed(1) + ' MB' : done + ' / ' + total;
    return h('section', {className: 'bfw-stage-progress', 'data-stage-progress': stage.id,
      'data-progress-state': stale ? 'stale' : state, 'aria-label': t('stageProgress')},
      h('div', {className: 'bfw-progress-caption'},
        h('div', {className: 'bfw-progress-heading'}, h('h2', null, t(stage.key)), status(state, t)),
        h('strong', {className: 'bfw-progress-metric'}, metric)),
      h('div', {className: 'bfw-progress-rail', 'data-indeterminate': String(!measured && moving)},
        measured ? h('progress', {max: total, value: done,
          'aria-label': t(products.length ? 'savedStageProducts' : 'stageProgress')}) :
          h('div', {className: 'bfw-progress-track', role: 'progressbar', 'aria-label': t('stageProgress'),
            'aria-valuetext': metric}, moving && h('span', {className: 'bfw-progress-sweep'})),
        measured && state === 'running' && h('span', {className: 'bfw-progress-activity', 'aria-hidden': true})),
      h('div', {className: 'bfw-progress-footer'},
        h('span', {className: 'bfw-muted', role: 'status', 'aria-live': 'polite'},
          measured ? unit + ' ' + amount : parallelUnknown ? t('parallelRunning') + ' ' + currentChildren.length :
            stage.id === 'execution' ? t('progressStages') + ' ' + completedStages + ' / 5' :
            steps.length ? unit + ' ' + completed + ' / ' + steps.length : t('waitingForReceipt')),
        current && h('span', {className: 'bfw-progress-current', title: current.id}, current.label || current.id),
        (conversationRunning || generation) && record.updatedAt && h('small', {className: 'bfw-muted', 'data-progress-updated': record.updatedAt},
          t('progressUpdated') + ' ' + new Date(record.updatedAt).toLocaleTimeString()),
        steps.length > 0 && h('details', {className: 'bfw-progress-details'}, h('summary', null, t('stageProcess')),
          h('div', {className: 'bfw-progress-detail-body'},
            h('small', {className: 'bfw-muted'}, t('lastObserved') + ': ' +
              (record.updatedAt ? new Date(record.updatedAt).toLocaleTimeString() : '—')),
            table([t('steps'), t('state'), t('phase')], steps.map((row) => [row.id, status(row.state, t), row.label || '—'])),
            history.length > 0 && h('small', {className: 'bfw-muted'}, t('priorSceneAttempts')),
            history.length > 0 && table([t('steps'), t('state'), t('phase')], history.map((row) => [row.id, status(row.state, t), row.label || '—']))))),
      generation && h('div', {className: 'bfw-parallel-task-count', 'data-generation-counts': true},
        h('span', {'data-generation-written': generation.written_count}, t('generationWritten') + ' ' + generation.written_count + ' / ' + generation.target_items), ' · ',
        h('span', {'data-generation-verified': generation.verified_count}, t('generationVerified') + ' ' + generation.verified_count + ' / ' + generation.target_items),
        Number.isSafeInteger(generation.contract_eligible_count) && h('span', {'data-generation-eligible': generation.contract_eligible_count},
          ' · ' + t('generationEligible') + ' ' + generation.contract_eligible_count + ' / ' + generation.target_items),
        Number.isSafeInteger(generation.candidate_count) && h('span', {'data-generation-candidate': generation.candidate_count}, ' · ' + t('generationCandidate') + ' ' + generation.candidate_count),
        Number.isSafeInteger(generation.published_count) && h('span', {'data-generation-published': generation.published_count}, ' · ' + t('generationPublished') + ' ' + generation.published_count),
        generation.written_count > checked && h('span', {'data-generation-draft': true}, ' · ' + t('generationNeedsRepair') + ' ' + (generation.written_count - checked))),
      Number.isSafeInteger(generation?.repair_candidate_verified_count) && repairTarget > 0 &&
        generation.repair_candidate_verified_count <= repairTarget && generation.written_count > checked &&
        h('div', {className: 'bfw-parallel-task-count', 'data-repair-progress': true},
          h('span', null, t('generationRepairVerified') + ' ' + generation.repair_candidate_verified_count + ' / ' + repairTarget),
          h('progress', {max: repairTarget, value: generation.repair_candidate_verified_count,
            'aria-label': t('generationRepairVerified')})),
      generation?.state === 'complete' && state !== 'completed' && h('small', {className: 'bfw-hint'}, t('generationAwaitingAdmission')),
      generation?.reported_state === 'running' && generation.state !== 'running' && h('small', {className: 'bfw-hint'}, t('generationInterrupted')),
      collection && h('div', {className: 'bfw-scene-summary', 'data-collection-scenes': true}, collection.rows.map((row) =>
        h('span', {className: 'bfw-scene-summary-row', key: row.id, 'data-scene-id': row.scene_id},
          h('strong', {title: row.scene_id || row.run_id}, row.name),
          h('span', {className: 'bfw-pill ' + row.state}, t(row.statusLabel))))),
      collection?.identityPending && h('small', {className: 'bfw-hint'}, t(collection.notice || 'sceneIdentityPending')),
      stale && h('p', {className: 'bfw-error'}, t('staleSnapshot')),
      !collection && current?.error && h('p', {className: 'bfw-error', role: 'alert'}, typeof current.error === 'string' ? current.error : JSON.stringify(current.error)),
      current?.queue && h('small', {className: 'bfw-hint'}, t('waiting') + ': ' + current.queue.reason),
      h(ParallelProgress, {tasks: record.value?.parallel_tasks || [], stage, t}),
      !collection && tasks.length > 1 && h(ParallelProgress, {stage, titleKey: 'progressTasks', t, tasks: tasks.map((row, index) => ({
        id: row.id, stage: stage.id, display_name: row.display_name || row.name || row.summary?.name || row.summary?.title ||
          t('progressTasks') + ' ' + (index + 1), state: row.queue && row.state !== 'FAILED_FINAL' ? 'waiting' : lifecycle(row.state),
        progress: row.progress, public_artifacts: artifacts.filter((file) => file.task_id === row.id && file.url),
      }))}));
  }
  return {TemplateCatalog, RunDetails, executionStage, reportedProgress, progressAmount, ParallelProgress, StageProgress};
}
