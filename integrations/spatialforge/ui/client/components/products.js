export function createProductComponents({React, helpers, components}) {
  const h = React.createElement;
  const {status, button, card, empty, json, sceneName, questionText, planValue, planMarkdown,
  planMarkdownView, planEditInstruction, table, select, initialState, initialDemand, sceneConstraint,
  productionRequest, displayRef, filteredPage, useRecord, usePanelVisible, lifecycle,
  productionProductsRevision, sceneStage, pipelineForStage, sceneForStage, progressSceneForStage,
  registeredCollectionProgress, currentGeneration, sceneCollectionProgress, annotationProducts,
  stageState, recordedStageState,
  STAGES, PLAN_SECTIONS, PLAN_FIELDS, styles, dictionaries} = helpers;
  const {TemplateCatalog, RunDetails, executionStage, reportedProgress, progressAmount, ParallelProgress,
    StageProgress, PublicObservation, QuestionDialog, sceneProjects, SceneGallery, SceneVideo,
    SceneLibrary, PreviewDialog, ArtifactGallery} = components;
  function StageReviewPanel({value, act, change, t}) {
    const [tick,setTick] = React.useState(Date.now());
    React.useEffect(() => {const timer=setInterval(() => setTick(Date.now()),1000); return () => clearInterval(timer);},[]);
    const received = React.useRef({value:null,at:0});
    if (received.current.value !== value) received.current={value,at:Date.now()};
    if (!value?.review_id) return null;
    const waiting = value.state === 'waiting_user';
    const remaining = Math.max(0,Math.ceil(value.deadline-value.server_time-(tick-received.current.at)/1000));
    const label = {waiting_user:'reviewWaiting',paused:'reviewPaused',needs_input:'reviewInstruction'}[value.state] || 'reviewFinished';
    return h('section',{className:'bfw-review','data-stage-review':value.stage,'data-review-state':value.state,'aria-live':'polite'},
      h('strong',null,t(STAGES.find(stage => stage.id === value.stage)?.key+'Nav')+' · '+t(label)), ' ', waiting && h('strong',{'data-review-countdown':true},
        Math.floor(remaining/60)+':'+String(remaining%60).padStart(2,'0')),
      waiting && h('span',{className:'bfw-muted'},' · '+t('reviewNote')),
      ['waiting_user','paused','needs_input'].includes(value.state) && h('div',{className:'bfw-review-actions'},
        value.state !== 'needs_input' && button(t('reviewContinue'),() => act('continue'),{'data-review-continue':true}),
        waiting && button(t('reviewPause'),() => act('pause'),{'data-review-pause':true}),
        button(t('reviewChange'),change,{'data-review-instruction':true})),
      value.instruction && h('p',null,value.instruction));
  }
  function DraftReview({draft, attachments, included, onInclude, t}) {
    if (!draft && !attachments.length) return null;
    return h('section', {className: 'bfw-draft-review', 'data-preserved-draft': true},
      draft && h(React.Fragment, null, h('strong', null, t('preservedDraft')), h('pre', {className: 'bfw-json'}, draft)),
      attachments.length > 0 && h('details', null, h('summary', null, t('preservedAttachments') + ': ' + attachments.length),
        h('ul', null, attachments.map((id) => h('li', {key: id, className: 'bfw-code'}, String(id))))),
      h('label', {className: 'bfw-consent'}, h('input', {type: 'checkbox', checked: included,
        onChange: (event) => onInclude(event.target.checked)}), t('includeDraft')));
  }
  function DemandForm({demand, change, busy, error, send, draft, attachments, included, onInclude, sceneSelection, openScenes, t}) {
    const append = demand.mode === 'append';
    return h('section', {className: 'bfw-demand', 'data-production-request': true},
      h('div', {className: 'bfw-demand-heading'}, h('h2', null, t('productionRequest')),
        select(t('task'), demand.mode, (mode) => change({mode}), [['new', t('newProduction')], ['append', t('appendRequest')]])),
      h('form', {onSubmit: (event) => {event.preventDefault(); send();}},
        h('label', {className: 'bfw-label'}, t(append ? 'changeRequirements' : 'productionRequirements'),
          h('textarea', {className: 'bfw-input bfw-textarea', rows: 3, 'data-production-objective': true,
            value: demand.objective, placeholder: t(append ? 'requestPlaceholder' : 'productionPlaceholder'),
            onChange: (event) => change({objective: event.target.value}), required: true})),
        !append && h('div', {className: 'bfw-demand-fields'},
          h('label', {className: 'bfw-label'}, t('targetItems'), h('input', {className: 'bfw-input', type: 'number', min: 1, step: 1,
            value: demand.count, 'data-production-count': true, onChange: (event) => change({count: event.target.value}), required: true})),
          select(t('executionMode'), demand.executionMode || 'production', (executionMode) => change({executionMode}),
            [['production', t('productionMode')], ['exploration', t('explorationMode')]]),
          select(t('quantityContract'), demand.quantityContract || 'minimum', (quantityContract) => change({quantityContract}),
            [['exact', t('exactQuantity')], ['minimum', t('minimumQuantity')], ['best_effort', t('bestEffortQuantity')]]),
          h('label', {className: 'bfw-label'}, t('capabilityRequest'), h('input', {className: 'bfw-input', value: demand.capability,
            placeholder: t('capabilityPlaceholder'), onChange: (event) => change({capability: event.target.value})}))),
        h(DraftReview, {draft, attachments, included, onInclude, t}),
        sceneSelection && h('div', {className: 'bfw-demand-scene-summary'},
          h('span', {className: 'bfw-muted'}, t('sceneSelected') + ': ' + sceneSelection.selected.length +
            ' · ' + t('allowNewScenes') + ': ' + (sceneSelection.allow_new_scenes ? '✓' : '—')),
          button(t('sceneLibrary'), openScenes)),
        error && h('p', {className: 'bfw-error', role: 'alert'}, error),
        h('div', {className: 'bfw-demand-footer'},
          h('div', {className: 'bfw-demand-options'},
            !append && h('details', null, h('summary', null, t('advancedOptions')), h('div', {className: 'bfw-form'},
              h('label', {className: 'bfw-label'}, t('sceneCount'), h('input', {className: 'bfw-input', type: 'number', min: 1, step: 1,
                value: demand.sceneCount, placeholder: t('optionalAuto'), onChange: (event) => change({sceneCount: event.target.value})})),
              h('label', {className: 'bfw-label'}, t('storageBudget'), h('input', {className: 'bfw-input', type: 'number', min: 0, step: 'any',
                value: demand.storageBudget, placeholder: t('optionalAuto'), onChange: (event) => change({storageBudget: event.target.value})}))),
              h('p', null, t('targetQuantityNote')), h('p', null, t('fullWorkflowNote')), h('p', null, t('requestNote'))),
            h('p', null, t(append ? 'appendNote' : 'productionHint'))),
          h('button', {type: 'submit', className: 'bfw-button bfw-action', disabled: busy || !demand.objective.trim(),
            'data-start-production': true}, t(busy ? 'sending' : append ? 'appendRequest' : 'startProduction')))));
  }
  function SendDialog({payload, change, draft, attachments, included, onInclude, sending, error, confirm, close, t}) {
    const ref = React.useRef(null);
    React.useEffect(() => {
      const trigger = document.activeElement;
      const dialog = ref.current;
      dialog.showModal();
      return () => {dialog.close(); trigger?.focus();};
    }, []);
    return h('dialog', {ref, className: 'bfw-preview-dialog', 'data-stage-confirm': true, 'aria-label': t('confirmTitle'),
      onCancel: (event) => {event.preventDefault(); if (!sending) close();}},
      h('h2', null, t('confirmTitle')), h('p', null, t('requestNote')), h('p', null, t('confirmSendNote')),
      h(DraftReview, {draft, attachments, included, onInclude, t}),
      h('textarea', {className: 'bfw-input bfw-textarea', 'data-request-text': true, 'aria-label': t('requestChange'), autoFocus: true,
        placeholder: t('requestPlaceholder'), value: payload.text, disabled: sending || payload.inserted, onChange: (event) => change(event.target.value)}),
      error && h('p', {className: 'bfw-error', role: 'alert'}, error),
      h('div', {className: 'bfw-stage-actions'}, button(t('cancel'), close, {disabled: sending}),
        button(t(sending ? 'sending' : 'confirmSend'), confirm, {className: 'bfw-button bfw-action', disabled: sending || !payload.text.trim()})));
  }
  function PlanProduct({plan, source, artifacts, preview, request, save, applyEdit, scenes = [],template, t}) {
    const [draft,setDraft]=React.useState(null);
    const [busy,setBusy]=React.useState(false);
    const [error,setError]=React.useState('');
    const [pending,setPending]=React.useState(null);
    const draftRef=React.useRef(null);
    const lock=React.useRef(false);
    const begin=()=>{const markdown=planMarkdown(plan),value={markdown,base_markdown:markdown,split:plan.inputs?.split || 'train',base:source?.plan_path};
      draftRef.current=value;setDraft(value);setError('');};
    const apply=async(path)=>{let message='',ok=false;
      try{ok=await applyEdit(path,(value)=>{message=value;});}catch(error){message=error.message;}
      if(!ok) setError('计划已保存，制作变更尚未提交。'+(message || '请点击“应用已保存修改”重试。'));
      else {setPending(null);setError('');}return ok;};
    const commit=async()=>{
      if(lock.current)return;lock.current=true;setBusy(true);setError('');
      try {const value=draftRef.current;const result=await save({plan_path:value.base,markdown:value.markdown,base_markdown:value.base_markdown,split:value.split});
        setDraft(null);draftRef.current=null;
        if(result.state!=='unchanged'){setPending(result.plan);if(applyEdit)await apply(result.plan);}
      }catch(error){setError(error.message);}finally{lock.current=false;setBusy(false);}
    };
    if (!plan) return h('div', null, empty(t('planPending')), h('details', null, h('summary', null, t('planTemplate')),
      h('small', {className: 'bfw-hint'}, t('planTemplateNote')),
      h('ol', null, (template?.sections || PLAN_SECTIONS.map(([key, title]) => ({key, title}))).map((row) => h('li', {key: row.key}, row.title)))));
    const document = plan.assessment;
    const labels=Object.fromEntries((plan.template_contracts || []).map((row)=>[row.id,row.title || row.task_name]));
    const sections = PLAN_SECTIONS.filter(([key]) => document?.[key]);
    const operate = (text) => request('本次操作对象是当前页面展示的已保存计划：' +
      (source?.plan_path || source?.operation_id || source?.run_id || plan.objective) + '\n请先读取该计划及其准确合同，再应用以下要求：\n' + text);
    return h('article', {key:draft ? 'editing' : 'saved',className: 'bfw-plan-document', 'data-assessment-document': document?.schema || 'legacy_summary'},
      h('div', {className: 'bfw-toolbar'}, h('span', {className: 'bfw-pill'}, t('persistedPlan')),
        document && h('span', {className: 'bfw-pill'}, t('completePlan') + ' · ' + sections.length + '/' + PLAN_SECTIONS.length),
        !draft && (document ? save && button(t('revisePlan'),begin,{'data-plan-revise':true}) : request && button(t('completePlanRequest'),()=>operate('请按照完整评测计划模板补全并保存 assessment，复用当前场景约束。'),{'data-plan-revise':true})),
        draft && button(t(busy ? 'savingPlan' : 'savePlan'),commit,{'data-plan-save':true,disabled:busy}),
        draft && button(t('cancelPlanEdit'),()=>{setDraft(null);draftRef.current=null;setError('');},{'data-plan-cancel':true,disabled:busy}),
        !draft && (pending || (plan.edit_revision && !plan.applies_edit)) && applyEdit && button('应用已保存修改',()=>apply(pending || source.plan_path),{'data-plan-apply':true}),
        !draft && !pending && !plan.edit_revision && document && request && button(t('continuePlan'), () => operate('请以当前已保存的完整评测计划继续实际生产。核对最新场景选择，复用已完成产物，补齐尚未完成的阶段并交付。不要重复提交正在运行的场景任务。'), {'data-plan-continue': true}),
        h('a', {className: 'bfw-button', href: 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(plan, null, 2)), download: 'assessment-plan.json'}, t('exportPlan')),
        h('a', {className: 'bfw-button', href: 'data:text/markdown;charset=utf-8,' + encodeURIComponent(planMarkdown(plan)), download: 'assessment-plan.md'}, t('exportPlanText'))),
      error && h('p',{className:'bfw-error',role:'alert'},error),
      draft && h('small',{className:'bfw-hint'},t('planEditNote')),
      draft && select('制作分区',draft.split,(value)=>{draftRef.current={...draftRef.current,split:value};setDraft({...draftRef.current});},['train','dev','test','sealed'].map(value=>[value,value])),
      typeof plan.user_markdown !== 'string' && h('h3', null, document ? planValue(document.title,null,['title'],labels) : (typeof plan.objective === 'string' ? plan.objective : plan.title || t('blueprint'))),
      scenes.length>0 && h('div',{className:'bfw-plan-scenes','data-plan-scene-previews':true},scenes.slice(0,3).map((row)=>h('button',{
        type:'button',className:'bfw-plan-scene',key:row.id,onClick:()=>preview({...row,title:row.name,kind:'scene'})},
        row.frames?.[0]?.url && h('img',{src:row.frames[0].url,alt:sceneName(row.name),loading:'lazy'}),h('span',null,sceneName(row.name)),h('small',null,row.planCurrent ? '本会话已采集场景' : '已采集参考场景')))),
      draft ? h('textarea', {className:'bfw-input bfw-plan-markdown-editor', 'data-plan-markdown-editor':true,
        'aria-label':t('planMarkdownEditor'), rows:32, spellCheck:false,
        style:{minHeight:'min(70vh, 50rem)',fontFamily:'ui-monospace, SFMono-Regular, Menlo, monospace',fontSize:'.8rem',lineHeight:1.55,whiteSpace:'pre',overflow:'auto'},
        value:draft.markdown,
        onChange:(event)=>{const value={...draftRef.current,markdown:event.target.value};draftRef.current=value;setDraft(value);}}) : typeof plan.user_markdown === 'string' ? planMarkdownView(plan.user_markdown) : document ? h(React.Fragment, null, h('p', {className: 'bfw-plan-summary'}, planValue(document.summary,null,['summary'],labels)),
        h('small', {className: 'bfw-hint'}, t('planDesignNote')),
        h('nav', {className: 'bfw-plan-toc', 'aria-label': t('completePlan')}, sections.map(([key, title], index) =>
          h('a', {key, href: '#bfw-plan-' + key}, String(index + 1).padStart(2, '0') + ' ' + title))),
        sections.map(([key, title], index) => h('section', {key, id: 'bfw-plan-' + key, className: 'bfw-plan-section', 'data-plan-section': key},
          h('h4', null, h('span', {className: 'bfw-muted'}, String(index + 1).padStart(2, '0') + ' '), title), planValue(document[key],null,[key],labels))))
        : h('p', {className: 'bfw-hint'}, t('legacyPlan')),
      !draft && h(document ? 'details' : React.Fragment, document ? {} : null, document && h('summary', null, t('planSteps')),
      plan.inputs && h('dl', {className: 'bfw-definition'}, Object.entries(plan.inputs).map(([key, value]) => h('div', {key},
        h('dt', null, key), h('dd', null, typeof value === 'object' ? JSON.stringify(value) : String(value))))),
      plan.selections?.length > 0 && table([t('selectedTemplates'), t('selectionTotal'), t('reason')],
        plan.selections.map((row) => [row.template_ids.join(', '), row.count, row.reason])),
      plan.steps?.length ? table([t('steps'), t('operator'), t('details')], plan.steps.map((row) =>
        [row.id, row.uses, row.title || row.description || (row.depends_on || []).join(' → ') || '—'])) : null),
      !draft && artifacts.length > 0 && h(ArtifactGallery, {items: artifacts, selected: [], preview, t}),
      !draft && h('details', null, h('summary', null, t('plan')), json(plan)));
  }
  function ReportProduct({item, observedAt, t}) {
    const [data, setData] = React.useState(item?.data || null);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      setError('');
      if (!item) {setData(null); return;}
      if (item.data) {setData(item.data); return;}
      const controller = new AbortController();
      setData(null);
      fetch(item.url, {signal: controller.signal}).then(async (response) => {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      }).then(setData).catch((reason) => {if (reason.name !== 'AbortError') setError(reason.message);});
      return () => controller.abort();
    }, [item?.url, observedAt]);
    if (!item) return empty(t('reportPending'));
    if (error) return h('p', {className: 'bfw-error', role: 'alert'}, t('artifactReadFailed') + ' ' + error);
    if (!data) return empty(t('loading'));
    return h('article', {className: 'bfw-plan-document'}, h('h3', null, item.title),
      h(DeliveryReceipt, {receipt: data, t}),
      data.scene_previews?.length > 0 && h('div', {'data-report-scene-previews': true,
        style: {display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: '.75rem'}},
        data.scene_previews.map((row) => h('figure', {key: row.url, style: {margin: 0}},
          h('img', {src: row.url, alt: row.title, loading: 'lazy', style: {width: '100%', aspectRatio: '16 / 9', objectFit: 'cover'}}),
          h('figcaption', {className: 'bfw-muted'}, row.title)))),
      data.body_markdown && h(React.Fragment, null, planMarkdownView(data.body_markdown),
        h('a', {className: 'bfw-button', href: item.step_id && item.url
            ? item.url + (item.url.includes('?') ? '&' : '?') + 'format=markdown'
            : 'data:text/markdown;charset=utf-8,' + encodeURIComponent(data.body_markdown),
          download: 'delivery_report.md'}, t('exportPlanText'))),
      !data.body_markdown && h('dl', {className: 'bfw-definition'}, Object.entries(data).filter(([key, value]) =>
        ['requested','accepted','shortfall','split','scene_groups','total','count','success_rate','model_api_calls','benchmark_approved','state','status'].includes(key) &&
        (value === null || typeof value !== 'object')).map(([key, value]) =>
        h('div', {key}, h('dt', null, key==='benchmark_approved' ? t('approval') :
          ({total:'总数',count:'数量',success_rate:'成功率',model_api_calls:'模型调用次数',status:'状态'})[key] || t(key)),
          h('dd', null, typeof value === 'boolean' ? t(value ? 'yes' : 'no') : ['state','status'].includes(key) ? t(value) : String(value ?? '—'))))),
      !data.body_markdown && data.per_partition && table(['数据用途','题量'], Object.entries(data.per_partition).map(([split,count])=>
        [({train:'训练',dev:'开发验证',test:'测试',sealed:'封存'})[split] || split,count])),
      h('details', null, h('summary', null,'数据详情'), json(data)));
  }
  function Quality({report, t, templateName=(id)=>id}) {
    if (!report) return empty(t('noReport'));
    return h(React.Fragment, null,
      h(DeliveryReceipt, {receipt: report, t}),
      h('small', {className: 'bfw-hint'}, t('reportNote')),
      h('div', {className: 'bfw-stats'}, ['requested', 'accepted', 'shortfall', 'scene_groups'].map((key) =>
        h('div', {className: 'bfw-stat', key}, t(key), h('strong', null, report[key] ?? '—')))),
      report.per_partition && table(['数据用途','题量'], Object.entries(report.per_partition).map(([split,count])=>
        [({train:'训练',dev:'开发验证',test:'测试',sealed:'封存'})[split] || split,count])),
      h('p', null, t('approval') + ': ', report.benchmark_approved === undefined ? '—' : t(report.benchmark_approved ? 'yes' : 'no')),
      card(t('coverage'), table([t('template'), t('accepted')], Object.entries(report.per_template || {}).map(([id,count])=>[templateName(id),count]))),
      card(t('rejections'), report.rejections?.length ? json(report.rejections) : empty(t('noRejections'))));
  }

  function DeliveryReceipt({receipt, t}) {
    if (!receipt || !['exact', 'minimum', 'best_effort'].includes(receipt.quantity_contract) &&
        receipt.target_items == null && receipt.target_reached == null && receipt.delivery_satisfied == null && !receipt.delivery_status) return null;
    const contract = ['exact', 'minimum', 'best_effort'].includes(receipt.quantity_contract)
      ? t({exact: 'exactQuantity', minimum: 'minimumQuantity', best_effort: 'bestEffortQuantity'}[receipt.quantity_contract]) : t('unknown');
    const targetReached = typeof receipt.target_reached === 'boolean' ? t(receipt.target_reached ? 'targetReached' : 'targetNotReached') : t('unknown');
    const delivery = typeof receipt.delivery_satisfied === 'boolean'
      ? t(receipt.delivery_satisfied ? 'deliverySatisfied' : 'deliveryNotSatisfied')
      : t({complete: 'deliveryComplete', partial: 'deliveryPartial', unsatisfied: 'deliveryUnsatisfied', not_evaluated: 'deliveryUnknown'}[receipt.delivery_status] || 'deliveryUnknown');
    return h('section', {className: 'bfw-delivery-receipt', 'data-delivery-satisfied': String(receipt.delivery_satisfied ?? 'unknown')},
      h('h4', null, t('deliveryReceipt')),
      h('dl', {className: 'bfw-definition'},
        h('div', null, h('dt', null, t('quantityContract')), h('dd', null, contract)),
        h('div', null, h('dt', null, t('targetItems')), h('dd', null, receipt.target_items ?? receipt.requested ?? '—')),
        h('div', null, h('dt', null, t('accepted')), h('dd', null, receipt.accepted ?? '—')),
        h('div', null, h('dt', null, t('shortfall')), h('dd', null, receipt.shortfall ?? '—')),
        h('div', null, h('dt', null, t('targetReached')), h('dd', null, targetReached)),
        h('div', null, h('dt', null, t('deliverySatisfaction')), h('dd', null, delivery))));
  }

  function ExecutionFeedback({renderFactorySlot, t}) {
    return h('div', {className: 'bfw-native-chat', 'data-execution-feedback': true,
      'data-native-chat-view': true, 'aria-label': t('executionFeedback')},
      renderFactorySlot('conversation.content', {variant: 'embedded', phase: 'active', hero: false}));
  }
  return {StageReviewPanel, DraftReview, DemandForm, SendDialog, PlanProduct, ReportProduct, Quality, DeliveryReceipt, ExecutionFeedback};
}
