window.__ModuleLoader__.load({
  id: '@eurecamoment/benchforge-spatialforge-ui',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const PANEL = 'benchforge-spatialforge-evaluation';
    const SPATIALFORGE_PRESET = 'spatialforge-standard-ptc';
    const NS = 'benchforgeWorkbench';
    const STAGES = [
      {id: 'S1', key: 'blueprint'},
      {id: 'S2', key: 'collection'},
      {id: 'S3', key: 'structure'},
      {id: 'S4', key: 'synthesis'},
      {id: 'S5', key: 'verification'},
    ];
    const dictionaries = {
      zh: {
        productionMonitor: '生产实况', autoRefresh: '自动更新 · 约 3 秒', staleSnapshot: '观测异常 · 非最新状态', pollingPaused: '隐藏时暂停更新',
        lastObserved: '最近观测', conversationRunning: 'DSH 对话执行中；以下为工具记录', productionScope: '当前工作区与本会话场景任务',
        retainedSnapshot: '连接异常，保留上次成功观测，恢复后自动续更', partialObservation: '部分来源读取失败；显示的是可读取记录，不能据此判断全部任务正常。',
        persistedSteps: '已落盘完成步骤', currentStep: '当前待完成步骤', unrecordedStep: '尚无执行回执', sceneJobs: '本会话场景任务',
        completedTasks: '执行完成任务', phase: '生产阶段', workerStage: 'worker 最近上报', workerAge: '距 worker 上报', transfer: '已接收产物',
        capturedViews: '已记录图像', actionTraces: '交互轨迹', publication: '发布状态', canceled: '已取消',
        taskLimit: '本页显示前 12 项任务；完整状态可在对话使用 spatialforge_status 查看。',
        noProduction: '尚未找到本会话场景任务或工作区 pipeline 回执；聊天生成中的文字不计为生产完成。',
        recentOperations: '最近工具操作', observerNotConfigured: '场景队列观察器未配置；当前仅读取工作区 pipeline。',
        productionDetails: '查看生产明细', runFilter: '筛选运行名称、ID 或状态', versionFilter: '筛选版本、运行或任务',
        noMatchingRuns: '没有符合筛选条件的运行。', noMatchingVersions: '没有符合筛选条件的数据集版本。',
        chooseVersionForReport: '先选择一个数据集版本，再查看对应的质量报告。',
        noMatchingTemplates: '没有符合条件的模板。', clearFilters: '清空筛选', searchTemplates: '搜索模板',
        readFailed: '读取失败，请重试。', retry: '重试', sampleRemoved: '该样本已不在当前结果中，已返回列表。',
        stageStateSource: '步骤状态来源', workspacePipeline: '工作区流水线', sessionProduction: '本会话场景任务',
        panel: '评测工作台', openEvaluation: '评测集', noWorkspace: '当前 SpatialForge 会话没有登记的工作区。请先为这个会话选择工作区。', overview: '总览', runs: '运行与产物', datasets: '数据集', quality: '质量报告',
        subtitle: '从评测目标到数据集交付，组织每一步操作与产物。', refresh: '刷新', loading: '读取中…',
        scope: '显示已登记工作区中的最近索引记录；未统计的数据以“—”表示。', snapshot: '快照时间',
        draft: '草稿', candidate: '候选', verified: '已验证', rejected: '已拒绝', superseded: '已替代',
        failed: '失败', completed: '执行完成', waiting: '等待', needs_input: '缺输入', needs_evidence: '缺证据',
        running: '运行中', proposed: '待审阅', unknown: '未记录', unassessed: '未评估',
        recent: '最近运行', workspace: '工作区', state: '状态', steps: '步骤', artifacts: '产物',
        updated: '更新时间', open: '查看', noRuns: '当前索引中没有持久化 pipeline 运行。', all: '全部',
        sources: '数据来源', indexed: '已读取操作索引', no_index: '没有运行索引', index_error: '索引读取失败',
        record_error: '记录读取失败', limit: '条最近操作上限', truncated: '列表已截断；更早记录不计入本页',
        chooseRun: '从运行列表选择一项，查看步骤、产物和修复建议。', plan: '冻结计划摘要', next: '运行提示',
        lineage: '产物与来源', contracts: '结构合同', shapeNote: '结构合同通过不代表 GT 或场景质量已通过。',
        noArtifacts: '该运行没有产物 manifest；不能据此推断候选或验证数量。', producer: '生成操作',
        parents: '父产物', evidence: '证据引用', version: '版本', repairs: '修复建议', noRepairs: '没有持久化修复建议。',
        repairNote: '以下是已保存的建议，不代表修复已执行。继续生产仍使用原 DSH 工具。',
        reason: '原因', operator: '操作', repairScope: '范围', newRun: '要求新运行', yes: '是', no: '否',
        directory: '数据集版本目录', datasetNote: '每个产物目录独立作为一个版本；只展示公开题目和声明的媒体。',
        noDatasets: '当前操作索引中没有可读取的公开数据集。', generationAccepted: '生成接纳数', browse: '浏览样本',
        chooseDataset: '选择数据集版本', template: '模板', split: '分区', search: '题目、ID 或任务', apply: '检索',
        previous: '上一页', nextPage: '下一页', page: '页', matches: '符合条件', total: '全集记录', pageSize: '每页',
        grid: '网格', table: '表格', question: '公开题目', noItems: '没有符合条件的记录。', item: '样本',
        details: '公开条件与输出格式', media: '公开观测', noMedia: '未声明公开媒体', close: '返回列表',
        publicNote: '当前是公开题目视角，接口不读取 authority、答案或 oracle 文件。',
        report: '生成质量报告', noReport: '该版本没有 quality_report.json，不能宣称已完成集合质量验收。',
        requested: '请求数', accepted: '生成接纳数', shortfall: '缺口', scene_groups: '场景组',
        approval: '报告声明 benchmark_approved', reportNote: '生成接纳数不等于已验证样本数；未收集模型响应时不显示 IRT。',
        coverage: '各模板实际接纳数', rejections: '缺口与拒绝原因', noRejections: '报告没有记录缺口或拒绝原因。',
        local_field_repair: '局部字段修复', template_rebinding: '模板重绑定', candidate_resynthesis: '候选重合成',
        skill_reexecution: '重新执行步骤', upstream_rollback: '上游回滚', final_rejection: '最终拒绝',
        task: '任务', capability: '能力', path: '来源目录', runCount: '运行', datasetCount: '数据集版本',
        workflow: '五步工作流', blueprint: '评测计划', collection: '场景预览', structure: '标注预览', synthesis: '评测配置与题目表', verification: '最终报告',
        stageProgress: '本阶段生产进度', waitingForReceipt: '等待执行回执', observedSteps: '已完成步骤', stageProcess: '查看本阶段执行过程',
        keyProduct: '关键产物', draftOnly: '浏览器草稿 · 尚未提交生产', planPending: '生产计划尚未落盘。在下方填写目标，使用“填入对话”制定计划。',
        planEditor: '编辑评测要求与模板', productionRecord: '生产记录', automaticRecord: '自动跟随本会话生产', artifactPending: '尚无可预览产物；生产中生成的内容将在这里更新。',
        sceneSelection: '选择场景', selectedScenes: '已选场景', preview: '预览', previewClose: '关闭预览', selectArtifact: '选择',
        sceneGallery: '可用场景', annotationGallery: '标注数据', annotationNote: '点击预览查看公开标注与证据；模型候选标注与仿真真值保留各自来源。',
        evaluationConfig: '评测配置', questionTable: '题目表', finalReport: '最终报告', artifactFiles: '产物文件与来源',
        insertStage: '填入对话', stepInstruction: '查看本步指令', chooseSceneHint: '可多选，所选场景会随本步指令填入对话。',
        persistedPlan: '已落盘评测计划', planSteps: '计划步骤', reportPending: '最终报告尚未生成；执行完成不等于评测通过。',
        knownProgress: '以执行回执为准', unmeasuredProgress: '尚无可测量的完成总量', noStageSteps: '当前生产记录尚未提供本阶段的执行回执。',
        downloadArtifact: '打开产物', artifactReadFailed: '产物读取失败，请重试。', runHistory: '历史计划与运行', runDetails: '当前运行明细与产物来源',
        confirmSend: '确认发送', confirmTitle: '确认发送本步任务', cancel: '取消', sending: '提交中…', sent: '本步任务已提交到当前对话，执行状态以对话回执为准。',
        confirmSendNote: '将本步计划、所选场景、数据集版本和产物引用打包，直接提交到当前 SpatialForge 对话。输入框现有文字和附件也会一同发送；取消不会更改输入框。',
        sendBusy: '输入框正在处理提交或命令，请完成后重试。', sendFailed: '提交失败，已保留任务内容，请重试。', noSendInterface: '当前 DSH 未提供对话提交接口。',
        existingDraft: '将一同发送的输入框文字', existingAttachments: '将一同发送的附件数',
        blueprintDesc: '定义测量目标，选择能力与模板，明确产量和来源。', collectionDesc: '先准备场景，再采集图像、视频、轨迹与原生状态。',
        structureDesc: '整理公开观测、标定和对象关系，绑定程序或仿真证据。', synthesisDesc: '按模板批量出题，查看数据集全集和样本。', verificationDesc: '审查有效性、分区与覆盖，生成报告和交付版本。',
        objective: '评测目标', objectivePlaceholder: '例如：测试室内遮挡条件下的距离估计和相对位置推理，生成 300 道评测题。',
        targetItems: '目标题量', storageBudget: '存储上限（GB）', sourceType: '数据来源', simulator: '仿真场景', program: '程序生成', official: '官方数据',
        templateCatalog: '能力与出题模板', catalogDesign: '目录是出题设计；执行能力由 DSH 检查适配器。', selectedTemplates: '已选模板', selectTemplate: '选择', removeTemplate: '移除',
        noSelection: '还未选择模板；也可让 DSH 根据目标拆解。', allocate: '计划分配', saveBlueprint: '保存蓝图草稿', blueprintSaved: '蓝图已保存到当前会话浏览器草稿。',
        preparePlan: '填入对话：制定生产计划', prepareStage: '填入对话：执行当前步骤', draftReady: '步骤指令已插入当前对话输入框，请查看后发送。',
        draftBusy: '当前输入框忙碌，请稍后重试。', nativeInputMissing: '当前会话未提供输入接口，请使用下方复制指令。', copyInstruction: '复制步骤指令', copied: '已复制步骤指令。',
        stepOutput: '本步产物', noStepArtifacts: '所选运行尚无可归属本步骤的产物记录。', chooseProduction: '查看生产运行', stageEvidence: '本步产物与来源',
        nextStep: '下一步', previousStep: '上一步', openData: '打开数据集全集', openQuality: '查看质量报告', openRun: '查看完整运行',
        workflowNote: '五步用于组织操作与产物，可按需组合或返回修复。', chatNote: '指令进入现有 DSH 对话，发送后由工具执行；页面从持久化产物读取结果。',
        blueprintOutput: '需求、模板与数量分配', collectionOutput: '参考、场景、媒体与采集记录', structureOutput: '证据、标定、状态与来源关系', synthesisOutput: '题目、公开观测与数据集版本', verificationOutput: '质量结果、修复建议与交付包',
        sceneFirst: '场景先行', sceneFirstNote: '复用或生成场景 → 采集 RGB / 深度 / 分割 / 轨迹 → 返回可追溯证据。',
        evidencePolicy: 'GT 来自官方、程序或仿真；模型推断保持为候选标注。', qualityPolicy: '执行完成、生成接纳和验证通过分别展示；没有响应矩阵时不展示 IRT。',
        savedAt: '草稿保存于', navigation: 'BenchForge 五步', liveRecords: '当前会话的实际产物', requiredGoal: '先填写评测目标。', perTemplate: '题 / 模板',
      },
      en: {
        productionMonitor: 'Live production', autoRefresh: 'Auto update · about 3 s', staleSnapshot: 'Observation issue · not current', pollingPaused: 'Updates paused while hidden',
        lastObserved: 'Last observed', conversationRunning: 'DSH conversation running; tool records below', productionScope: 'Current workspace and session scene jobs',
        retainedSnapshot: 'Connection failed. Keeping the last successful observation and retrying automatically', partialObservation: 'Some sources could not be read. Available records do not establish that all jobs are healthy.',
        persistedSteps: 'Persisted completed steps', currentStep: 'Current unfinished step', unrecordedStep: 'No execution receipt yet', sceneJobs: 'Session scene jobs',
        completedTasks: 'Completed tasks', phase: 'Production phase', workerStage: 'Last worker report', workerAge: 'Since worker report', transfer: 'Artifacts received',
        capturedViews: 'Recorded images', actionTraces: 'Action traces', publication: 'Publication status', canceled: 'Canceled',
        taskLimit: 'Showing the first 12 tasks. Use spatialforge_status in the conversation for the complete record.',
        noProduction: 'No session scene job or workspace pipeline receipt found. Chat prose is not production completion.',
        recentOperations: 'Recent tool operations', observerNotConfigured: 'Scene observer is not configured; only workspace pipelines are observed.',
        productionDetails: 'View production details', runFilter: 'Filter runs by name, ID or state', versionFilter: 'Filter versions, runs or tasks',
        noMatchingRuns: 'No runs match this filter.', noMatchingVersions: 'No dataset versions match this filter.',
        chooseVersionForReport: 'Choose a dataset version to view its quality report.',
        noMatchingTemplates: 'No templates match these filters.', clearFilters: 'Clear filters', searchTemplates: 'Search templates',
        readFailed: 'Could not read the records. Please retry.', retry: 'Retry', sampleRemoved: 'This sample is no longer in the current results. Returned to the list.',
        stageStateSource: 'Step status source', workspacePipeline: 'Workspace pipeline', sessionProduction: 'Session scene job',
        panel: 'Evaluation workbench', openEvaluation: 'Evaluations', noWorkspace: 'This SpatialForge session has no registered workspace. Attach one to this session first.', overview: 'Overview', runs: 'Runs & artifacts', datasets: 'Datasets', quality: 'Quality reports',
        subtitle: 'From evaluation goals to dataset delivery: actions and artifacts at every step.', refresh: 'Refresh', loading: 'Loading…',
        scope: 'Recent indexed records in registered workspaces. Unmeasured values are shown as —.', snapshot: 'Snapshot',
        draft: 'Draft', candidate: 'Candidate', verified: 'Verified', rejected: 'Rejected', superseded: 'Superseded',
        failed: 'Failed', completed: 'Execution completed', waiting: 'Waiting', needs_input: 'Needs input', needs_evidence: 'Needs evidence',
        running: 'Running', proposed: 'Proposed', unknown: 'Not recorded', unassessed: 'Unassessed',
        recent: 'Recent runs', workspace: 'Workspace', state: 'State', steps: 'Steps', artifacts: 'Artifacts',
        updated: 'Updated', open: 'Open', noRuns: 'No persisted pipeline runs in the current index.', all: 'All',
        sources: 'Sources', indexed: 'Operation index read', no_index: 'No run index', index_error: 'Index read failed',
        record_error: 'Record read failed', limit: 'recent operation limit', truncated: 'List truncated; older records are excluded from these totals',
        chooseRun: 'Select a run to inspect steps, artifacts and repair proposals.', plan: 'Frozen plan summary', next: 'Run note',
        lineage: 'Artifacts & provenance', contracts: 'Shape contracts', shapeNote: 'Shape checks do not establish GT or scene quality.',
        noArtifacts: 'This run has no artifact manifest. Candidate and verified counts are unknown.', producer: 'Producer',
        parents: 'Parents', evidence: 'Evidence references', version: 'Version', repairs: 'Repair proposals', noRepairs: 'No saved repair proposals.',
        repairNote: 'Saved proposals are not executed repairs. Production continues through the existing DSH tools.',
        reason: 'Reason', operator: 'Operator', repairScope: 'Scope', newRun: 'Requires new run', yes: 'Yes', no: 'No',
        directory: 'Dataset versions', datasetNote: 'Each artifact directory is an isolated version. Only public questions and declared media are exposed.',
        noDatasets: 'No readable public datasets in the operation index.', generationAccepted: 'Generation accepted', browse: 'Browse samples',
        chooseDataset: 'Choose dataset version', template: 'Template', split: 'Split', search: 'Question, ID or task', apply: 'Search',
        previous: 'Previous', nextPage: 'Next', page: 'Page', matches: 'Matches', total: 'All records', pageSize: 'Per page',
        grid: 'Grid', table: 'Table', question: 'Public question', noItems: 'No matching records.', item: 'Sample',
        details: 'Public conditions & output format', media: 'Public observations', noMedia: 'No declared public media', close: 'Back to list',
        publicNote: 'Public view. The API does not read authority, answers or oracle files.',
        report: 'Generation quality report', noReport: 'No quality_report.json. Collection acceptance cannot be inferred.',
        requested: 'Requested', accepted: 'Generation accepted', shortfall: 'Shortfall', scene_groups: 'Scene groups',
        approval: 'Report declares benchmark_approved', reportNote: 'Generation acceptance is not verified-item count. IRT is hidden without model responses.',
        coverage: 'Accepted items per template', rejections: 'Shortfalls & rejections', noRejections: 'No shortfall or rejection recorded in this report.',
        local_field_repair: 'Local field repair', template_rebinding: 'Template rebinding', candidate_resynthesis: 'Candidate resynthesis',
        skill_reexecution: 'Step re-execution', upstream_rollback: 'Upstream rollback', final_rejection: 'Final rejection',
        task: 'Task', capability: 'Capability', path: 'Source directory', runCount: 'Runs', datasetCount: 'Dataset versions',
        workflow: 'Five-step workflow', blueprint: 'Evaluation plan', collection: 'Scene preview', structure: 'Annotation preview', synthesis: 'Evaluation config & questions', verification: 'Final report',
        stageProgress: 'Stage production progress', waitingForReceipt: 'Waiting for execution receipt', observedSteps: 'Completed steps', stageProcess: 'Stage execution details',
        keyProduct: 'Key product', draftOnly: 'Browser draft · not submitted', planPending: 'No persisted plan. Set the goal below and draft a planning request in chat.',
        planEditor: 'Edit requirements & templates', productionRecord: 'Production record', automaticRecord: 'Follow this session’s production', artifactPending: 'No previewable artifacts yet. New production outputs will appear here.',
        sceneSelection: 'Select scenes', selectedScenes: 'Selected scenes', preview: 'Preview', previewClose: 'Close preview', selectArtifact: 'Select',
        sceneGallery: 'Available scenes', annotationGallery: 'Annotations', annotationNote: 'Open public annotations and evidence. Candidate model annotations retain their source separately from simulation truth.',
        evaluationConfig: 'Evaluation configuration', questionTable: 'Questions', finalReport: 'Final report', artifactFiles: 'Artifact files & provenance',
        insertStage: 'Draft in chat', stepInstruction: 'View stage instruction', chooseSceneHint: 'Select multiple scenes to include in the stage instruction.',
        persistedPlan: 'Persisted evaluation plan', planSteps: 'Planned steps', reportPending: 'No final report yet. Execution completion is not benchmark approval.',
        knownProgress: 'From execution receipts', unmeasuredProgress: 'No measurable total reported', noStageSteps: 'No execution receipt for this stage in this production record.',
        downloadArtifact: 'Open artifact', artifactReadFailed: 'Could not read this artifact. Retry.', runHistory: 'Past plans and runs', runDetails: 'Current run details and artifact provenance',
        confirmSend: 'Confirm and send', confirmTitle: 'Confirm stage task', cancel: 'Cancel', sending: 'Submitting…', sent: 'Stage task submitted to this conversation; follow its execution receipt in chat.',
        confirmSendNote: 'Package this stage, plan, selected scenes, dataset version and artifact references and submit directly to this SpatialForge conversation. Existing composer text and attachments will also be sent. Cancel leaves them unchanged.',
        sendBusy: 'The composer is processing a submission or command. Try again after it finishes.', sendFailed: 'Submission failed. Task retained; please retry.', noSendInterface: 'This DSH session has no submission interface.',
        existingDraft: 'Composer text included in this submission', existingAttachments: 'Attachments included in this submission',
        blueprintDesc: 'Define the goal, capabilities, templates, quantity and sources.', collectionDesc: 'Prepare scenes, then collect images, video, trajectories and native state.',
        structureDesc: 'Organize public observations, calibration and source evidence.', synthesisDesc: 'Produce questions and inspect dataset versions and samples.', verificationDesc: 'Inspect validity, splits and coverage; prepare reports and releases.',
        objective: 'Evaluation goal', objectivePlaceholder: 'For example: 300 indoor distance and relative-position questions with varied occlusion.',
        targetItems: 'Target items', storageBudget: 'Storage limit (GB)', sourceType: 'Source', simulator: 'Simulation scenes', program: 'Program generation', official: 'Official data',
        templateCatalog: 'Capabilities & templates', catalogDesign: 'Design catalog. DSH checks execution adapters before production.', selectedTemplates: 'Selected templates', selectTemplate: 'Select', removeTemplate: 'Remove',
        noSelection: 'No templates selected. DSH can decompose the goal.', allocate: 'Allocation', saveBlueprint: 'Save blueprint draft', blueprintSaved: 'Blueprint saved in this session’s browser draft.',
        preparePlan: 'Draft in chat: production plan', prepareStage: 'Draft in chat: current step', draftReady: 'Instruction inserted into this session’s composer. Review and send.',
        draftBusy: 'The composer is busy. Try again shortly.', nativeInputMissing: 'No input interface in this session. Copy the instruction below.', copyInstruction: 'Copy step instruction', copied: 'Instruction copied.',
        stepOutput: 'Step outputs', noStepArtifacts: 'No recorded artifacts map to this step in the selected run.', chooseProduction: 'Production run', stageEvidence: 'Step artifacts & sources',
        nextStep: 'Next step', previousStep: 'Previous step', openData: 'Browse all dataset items', openQuality: 'Open quality report', openRun: 'Open full run',
        workflowNote: 'Five steps organize actions and artifacts. Compose or revisit them as needed.', chatNote: 'Instructions use the existing DSH conversation and tools. Results come from persisted artifacts.',
        blueprintOutput: 'Goal, templates and allocation', collectionOutput: 'References, scenes, media and captures', structureOutput: 'Evidence, calibration, state and provenance', synthesisOutput: 'Questions, public observations and dataset versions', verificationOutput: 'Quality results, repair proposals and packages',
        sceneFirst: 'Scenes first', sceneFirstNote: 'Reuse or generate scenes → capture RGB / depth / masks / trajectories → retain traceable evidence.',
        evidencePolicy: 'GT comes from official sources, programs or simulation. Model inference remains candidate annotation.', qualityPolicy: 'Completion, generation acceptance and verification are distinct. No IRT without response data.',
        savedAt: 'Draft saved at', navigation: 'BenchForge five steps', liveRecords: 'Actual artifacts in this session', requiredGoal: 'Enter an evaluation goal first.', perTemplate: 'items / template',
      },
    };
    const styles = `
.bfw-root{height:100%;overflow:auto;box-sizing:border-box;container-type:inline-size;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font:.875rem/1.55 system-ui,sans-serif}
.bfw-root *{box-sizing:border-box}.bfw-shell{min-width:0;max-width:100%;padding:clamp(.75rem,2.5cqi,1.75rem)}
.bfw-header,.bfw-toolbar,.bfw-pagination,.bfw-counts,.bfw-preview-header,.bfw-progress-caption{display:flex;align-items:center;flex-wrap:wrap;gap:clamp(.5rem,1.5cqi,1rem)}
.bfw-header{justify-content:space-between;margin-block-end:1rem}.bfw-title{font-size:clamp(1.1rem,2.5cqi,1.5rem);margin:0}.bfw-kicker{font-size:.7rem;letter-spacing:.09em}.bfw-muted,.bfw-kicker{color:var(--dsw-alias-label-secondary)}
.bfw-toolbar{margin-block:.75rem}.bfw-label{display:grid;gap:.35em;font-size:.8rem;min-inline-size:0;max-inline-size:100%}.bfw-button,.bfw-input,.bfw-select{font:inherit;color:inherit;border:1px solid var(--dsw-alias-border-l3);border-radius:.5rem;padding:.5em .8em;background:var(--dsw-alias-button-elevated-fill);max-inline-size:100%;min-inline-size:0}.bfw-input{flex:1 1 16ch;width:100%}.bfw-select{width:100%;text-overflow:ellipsis}.bfw-button{cursor:pointer}.bfw-button:hover{background:var(--dsw-alias-button-floating-hover)}.bfw-button:disabled{opacity:.5;cursor:default}.bfw-action{background:var(--dsw-alias-brand-primary);color:var(--dsw-alias-label-onbrand,#fff);border-color:transparent}.bfw-button:focus-visible,.bfw-input:focus-visible,.bfw-select:focus-visible,.bfw-stage:focus-visible,.bfw-preview-open:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}
.bfw-flow{display:flex;flex-wrap:wrap;gap:.4em;padding:.4em;background:var(--dsw-alias-bg-layer-2);border-radius:1.5rem;margin-block:1rem}.bfw-stage{flex:1 1 12ch;min-inline-size:0;display:flex;align-items:center;flex-wrap:wrap;gap:.4em .65em;cursor:pointer;text-align:start;border:1px solid transparent;border-radius:1.1rem;padding:clamp(.6em,1.6cqi,1em);background:transparent;color:var(--dsw-alias-label-secondary);font:inherit}.bfw-stage[aria-current=step]{background:var(--dsw-alias-bg-layer-1);border-color:var(--dsw-alias-border-l3);color:var(--dsw-alias-label-primary);box-shadow:0 .15em .5em #00000009}.bfw-stage-index{font:.75rem ui-monospace,monospace}.bfw-stage strong{font-size:.85rem;font-weight:600;overflow-wrap:anywhere}.bfw-stage-state{font-size:.7rem}.bfw-stage-state[data-stage-state=running]{color:var(--dsw-alias-brand-primary)}.bfw-stage-state[data-stage-state=failed]{color:var(--dsw-alias-state-error-primary)}.bfw-stage-state[data-stage-state=completed]{color:var(--dsw-alias-state-success-primary)}
.bfw-stage-progress{margin-block:1rem 1.5rem}.bfw-progress-caption{justify-content:space-between;font-size:.8rem;margin-block:.4em;overflow-wrap:anywhere}.bfw-stage-progress progress,.bfw-production progress,.bfw-progress-track{display:block;width:100%;height:.55rem;border:0;border-radius:1rem;overflow:hidden;background:var(--dsw-alias-bg-layer-2);accent-color:var(--dsw-alias-brand-primary)}.bfw-stage-progress progress::-webkit-progress-bar{background:var(--dsw-alias-bg-layer-2);border-radius:1rem}.bfw-stage-progress progress::-webkit-progress-value{background:var(--dsw-alias-brand-primary);border-radius:1rem}
.bfw-stage-heading{display:flex;align-items:flex-start;gap:.75rem;margin-block:1rem}.bfw-stage-heading h2{font-size:clamp(1.15rem,3cqi,1.6rem);margin:0}.bfw-stage-heading p{margin:.25em 0}.bfw-stage-number{font:1.35rem ui-monospace,monospace;color:var(--dsw-alias-brand-primary)}
.bfw-product{min-inline-size:0;min-block-size:20rem;border:1px solid var(--dsw-alias-border-l3);border-radius:1.25rem;background:var(--dsw-alias-bg-layer-1);padding:clamp(1rem,3cqi,2rem);margin-block:1rem}.bfw-product>h3{font-size:1rem;margin-block:0 1rem}.bfw-product .bfw-card{background:transparent}.bfw-stage-footer{display:flex;justify-content:space-between;gap:.5rem;margin-block:1rem}.bfw-stage-actions{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.75rem;align-items:center;margin-block:1rem}.bfw-production-source{flex:1 1 26ch}.bfw-tools{margin-block:1.25rem;border-block-start:1px solid var(--dsw-alias-border-l3);padding-block-start:.75rem}
.bfw-card{min-width:0;margin-block:1rem;border:1px solid var(--dsw-alias-border-l3);border-radius:.75rem;background:var(--dsw-alias-bg-layer-1)}.bfw-card h2{font-size:.95rem;font-weight:600;margin:0;padding:.8rem 1rem;border-block-end:1px solid var(--dsw-alias-border-l3)}.bfw-body{padding:clamp(.75rem,2cqi,1.25rem)}
.bfw-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,12ch),1fr));gap:.75rem;margin-block:1rem}.bfw-stat{border:1px solid var(--dsw-alias-border-l3);border-radius:.75rem;padding:.9rem;min-inline-size:0}.bfw-stat strong{display:block;font-size:clamp(1.25rem,3cqi,1.75rem);margin-block-start:.4rem}.bfw-details,.bfw-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,30ch),1fr));gap:1rem;min-inline-size:0}.bfw-form .bfw-wide{grid-column:1/-1}.bfw-textarea{width:100%;min-height:7em;resize:vertical;line-height:1.6}.bfw-evaluation-grid{display:flex;flex-wrap:wrap;gap:1.5rem;min-inline-size:0}.bfw-evaluation-config{flex:1 1 24ch;min-inline-size:0}.bfw-evaluation-questions{flex:3 1 40ch;min-inline-size:0}
.bfw-scroll{overflow:auto;max-inline-size:100%}.bfw-table{width:100%;border-collapse:collapse}.bfw-table td,.bfw-table th{text-align:start;padding:.65rem .75rem;border-block-end:1px solid var(--dsw-alias-border-l3);vertical-align:top;overflow-wrap:anywhere}.bfw-table th{font-size:.8rem;font-weight:500;color:var(--dsw-alias-label-secondary)}.bfw-table tr:last-child td{border:0}.bfw-table td>button{max-inline-size:100%}
.bfw-code,.bfw-json{font:.8rem/1.55 ui-monospace,monospace;overflow-wrap:anywhere;white-space:pre-wrap}.bfw-json{padding:.75rem;background:var(--dsw-alias-bg-layer-2);border-radius:.5rem;max-block-size:50vh;overflow:auto}.bfw-pill{display:inline-block;padding:.15em .6em;border-radius:2em;font-size:.75rem;background:var(--dsw-alias-bg-layer-2)}.bfw-pill.verified,.bfw-pill.completed{color:var(--dsw-alias-state-success-primary)}.bfw-pill.failed,.bfw-pill.rejected{color:var(--dsw-alias-state-error-primary)}.bfw-empty{padding:clamp(1rem,3cqi,2rem);color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}.bfw-error{padding:.75rem;border-inline-start:.2rem solid var(--dsw-alias-state-error-primary);background:var(--dsw-alias-bg-layer-2);white-space:pre-wrap;overflow-wrap:anywhere;margin-block:.75rem}
.bfw-artifact{padding-block:.75rem;border-block-end:1px solid var(--dsw-alias-border-l3)}.bfw-artifact:last-child{border:0}.bfw-detail-row{margin-block:.5rem;overflow-wrap:anywhere}.bfw-root summary{cursor:pointer}.bfw-version{display:block;max-inline-size:100%;overflow-wrap:anywhere}.bfw-pagination{justify-content:space-between;margin-block:1rem}.bfw-list-controls{display:grid;gap:.5rem;margin-block:.75rem}.bfw-list-controls .bfw-toolbar,.bfw-list-controls .bfw-pagination{margin:0}
.bfw-items,.bfw-gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,24ch),1fr));gap:1rem}.bfw-item,.bfw-preview-card{display:flex;flex-direction:column;min-inline-size:0;overflow:hidden;text-align:start;border:1px solid var(--dsw-alias-border-l3);border-radius:1rem;background:var(--dsw-alias-bg-layer-1);color:inherit;font:inherit}.bfw-item{padding:.75rem;cursor:pointer}.bfw-preview-card[data-selected=true]{border-color:var(--dsw-alias-brand-primary);background:var(--dsw-alias-bg-layer-2)}.bfw-preview-open{border:0;padding:0;display:flex;flex-direction:column;gap:.6rem;text-align:start;background:transparent;color:inherit;cursor:pointer;font:inherit}.bfw-preview-open img,.bfw-preview-open video,.bfw-document-thumb{width:100%;aspect-ratio:16/10;object-fit:contain;background:var(--dsw-alias-bg-layer-2)}.bfw-preview-open>strong,.bfw-preview-open>.bfw-muted,.bfw-preview-card>.bfw-code{padding-inline:.8rem;overflow-wrap:anywhere}.bfw-preview-open>.bfw-muted{padding-block-end:.6rem}.bfw-scene-check{display:flex;align-items:center;gap:.5em;padding:.8rem;border-block-start:1px solid var(--dsw-alias-border-l3)}.bfw-document-thumb{display:flex;flex-direction:column;justify-content:center;align-items:center;gap:.5em;padding:1rem;overflow:hidden}.bfw-document-thumb>span:first-child{font:2rem ui-monospace,monospace}.bfw-item img{width:100%;aspect-ratio:16/10;object-fit:contain;margin-block-end:.75rem}.bfw-item p{white-space:pre-wrap;overflow-wrap:anywhere}.bfw-question-preview{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.bfw-observation{display:block;max-inline-size:100%;max-block-size:65vh;object-fit:contain;margin:1rem auto}.bfw-question{white-space:pre-wrap;font-size:1rem;overflow-wrap:anywhere}
.bfw-preview-dialog{width:min(92vw,80rem);max-height:90vh;border:1px solid var(--dsw-alias-border-l3);border-radius:1.25rem;padding:clamp(1rem,3vw,2rem);background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}.bfw-preview-dialog::backdrop{background:#0008}.bfw-preview-header{justify-content:space-between}.bfw-preview-header h2{font-size:1.1rem;overflow-wrap:anywhere}.bfw-preview-dialog>img,.bfw-preview-dialog>video{display:block;max-width:100%;max-height:70vh;object-fit:contain;margin:auto}.bfw-plan-document{min-block-size:16rem;overflow-wrap:anywhere}.bfw-plan-document h3{font-size:1.25rem}.bfw-definition{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,20ch),1fr));gap:1rem}.bfw-definition dt{color:var(--dsw-alias-label-secondary)}.bfw-definition dd{margin:0;overflow-wrap:anywhere}
.bfw-annotation-image{position:relative;width:fit-content;max-inline-size:100%;margin-inline:auto}.bfw-annotation-image img{display:block;max-inline-size:100%;max-block-size:65vh;object-fit:contain}.bfw-annotation-image svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.bfw-production{border:1px solid var(--dsw-alias-border-l3);border-radius:.75rem;padding:.75rem;margin-block:1rem;overflow-wrap:anywhere}.bfw-production p{margin-block:.4em}.bfw-production-summary{display:flex;align-items:center;flex-wrap:wrap;gap:.5em}.bfw-live-details>summary{padding-block:.4rem;color:var(--dsw-alias-label-secondary)}.bfw-live-task,.bfw-live-line{padding-block:.75rem;border-block-start:1px solid var(--dsw-alias-border-l3);margin-block-start:.5rem}.bfw-callout,.bfw-notice{padding:.75rem 1rem;border-radius:.75rem;background:var(--dsw-alias-bg-layer-2);margin-block:.75rem;overflow-wrap:anywhere}.bfw-catalog{display:grid;gap:.75rem;margin-block:1rem}.bfw-template{border:1px solid var(--dsw-alias-border-l3);padding:.75rem;border-radius:.75rem;min-inline-size:0}.bfw-template header,.bfw-selected{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem}.bfw-template[data-selected=true]{border-color:var(--dsw-alias-brand-primary);background:var(--dsw-alias-bg-layer-2)}.bfw-selected{padding-block:.5rem;border-block-end:1px solid var(--dsw-alias-border-l3)}
.bfw-evaluation-launcher{font:inherit;color:var(--dsw-alias-label-primary);background:var(--dsw-alias-button-elevated-fill);border:1px solid var(--dsw-alias-border-l3);border-radius:.5rem;padding:.4em .7em;cursor:pointer}.bfw-evaluation-launcher:hover{background:var(--dsw-alias-button-floating-hover)}.bfw-evaluation-launcher:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}
`;

    function status(value, t) { return h('span', {className: 'bfw-pill ' + (value || 'unknown')}, t(value || 'unknown')); }
    function button(label, onClick, props = {}) { return h('button', {type: 'button', className: 'bfw-button', onClick, ...props}, label); }
    function card(title, children) { return h('section', {className: 'bfw-card'}, h('h2', null, title), h('div', {className: 'bfw-body'}, children)); }
    function empty(text) { return h('div', {className: 'bfw-empty'}, text); }
    function json(value) { return h('pre', {className: 'bfw-json'}, JSON.stringify(value, null, 2)); }
    function table(headers, rows) {
      return h('div', {className: 'bfw-scroll'}, h('table', {className: 'bfw-table'},
        h('thead', null, h('tr', null, headers.map((text, i) => h('th', {key: i}, text)))),
        h('tbody', null, rows.map((cells, i) => h('tr', {key: i}, cells.map((cell, j) => h('td', {key: j}, cell)))))));
    }
    function select(label, value, onChange, options) {
      return h('label', {className: 'bfw-label'}, label, h('select', {className: 'bfw-select', 'aria-label': label, value, onChange: (e) => onChange(e.target.value)},
        options.map(([id, text]) => h('option', {key: id, value: id}, text))));
    }
    function initialState(sessionId) {
      const fallback = {stage: 'S1', run: '', dataset: '', template: '', split: '', q: '', page: 1, size: 24, layout: 'table',
        runFilter: '', runListPage: 1, runListSize: 12, versionFilter: '', versionListPage: 1, versionListSize: 12};
      const saved = JSON.parse(localStorage.getItem('bfw:spatialforge:' + sessionId) || 'null');
      if (saved) {
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
    function useRecord(params, revision, interval = 0, active = true) {
      const key = params ? new URLSearchParams(params).toString() : '';
      const [record, setRecord] = React.useState({key: '', value: null, error: null, loading: false});
      React.useEffect(() => {
        if (!key) return;
        let stopped = false, timer, controller, inFlight = false;
        const load = async () => {
          if (stopped || inFlight) return;
          inFlight = true;
          controller = new AbortController();
          const deadline = setTimeout(() => controller.abort(), 16000);
          setRecord((old) => old.key === key ? {...old, loading: !old.value, refreshing: true} :
            {key, value: null, error: null, loading: true, refreshing: true});
          try {
            const response = await fetch('api/benchforge/workbench?' + key, {cache: 'no-store', signal: controller.signal});
            const value = await response.json();
            if (!response.ok) throw new Error(value.error || 'HTTP ' + response.status);
            if (!stopped) setRecord((old) => {
              if (value.scenes && old.key === key && old.value?.scenes) {
                const prior = old.value.scenes.runs || [];
                if (value.scenes.status === 'unavailable') value.scenes.runs = prior;
                else value.scenes.runs = (value.scenes.runs || []).map((row) => row.error
                  ? {...(prior.find((previous) => previous.run_id === row.run_id) || row), error: row.error} : row);
              }
              return {key, value, error: null, loading: false, refreshing: false, updatedAt: new Date().toISOString()};
            });
          } catch (error) {
            if (!stopped) setRecord((old) => ({...old, key, error: error.message, loading: false, refreshing: false}));
          } finally {
            clearTimeout(deadline); inFlight = false;
            if (!stopped && interval && active && document.visibilityState !== 'hidden') timer = setTimeout(load, interval);
          }
        };
        const resume = () => {
          clearTimeout(timer);
          if (active && document.visibilityState !== 'hidden') load();
        };
        load();
        if (interval) document.addEventListener('visibilitychange', resume);
        return () => {stopped = true; clearTimeout(timer); controller?.abort(); document.removeEventListener('visibilitychange', resume);};
      }, [key, revision, interval, active]);
      return record.key === key ? record : {value: null, error: null, loading: Boolean(key)};
    }

    function usePanelVisible(ref) {
      const [visible, setVisible] = React.useState(false);
      React.useEffect(() => {
        const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
        observer.observe(ref.current);
        return () => observer.disconnect();
      }, []);
      return visible;
    }
    const lifecycle = (value) => ({SUCCEEDED: 'completed', FAILED_FINAL: 'failed', CANCELED: 'canceled',
      READY: 'waiting', PENDING: 'waiting', RUNNING: 'running'}[value] || value || 'unknown');
    const sceneStage = (row) => row.workflow === 'dataset' ? 'S4' :
      ({review: 'S5', publish: 'S5', export: 'S5', dataset: 'S4', annotate: 'S3'}[row.phase] || 'S2');
    function stageState(id, pipeline, scene) {
      const current = (scene?.tasks || []).filter((row) => sceneStage(row) === id);
      if (current.length) {
        if (current.some((row) => row.state === 'FAILED_FINAL')) return 'failed';
        if (current.some((row) => row.queue)) return 'waiting';
        if (current.every((row) => row.state === 'SUCCEEDED')) return 'completed';
        if (current.some((row) => row.state === 'RUNNING')) return 'running';
        return lifecycle(scene.state);
      }
      const steps = (pipeline?.steps || []).filter((row) => row.stage === id);
      if (!steps.length) return 'unknown';
      if (steps.every((row) => row.state === 'completed')) return 'completed';
      return steps.find((row) => row.state !== 'completed' && row.state !== 'unknown')?.state ||
        (pipeline.current?.stage === id && pipeline.state !== 'completed' ? pipeline.state : 'unknown');
    }
    function Production({record, pipeline, scene, selected, selectScene, visible, conversationRunning, t}) {
      const value = record.value, jobs = value?.scenes?.runs || [];
      const tasks = scene?.tasks || [];
      const activeTask = tasks.find((row) => row.state === 'RUNNING') || tasks.find((row) => row.state !== 'SUCCEEDED') || tasks[0];
      const productionState = scene ? lifecycle(scene.state) : pipeline?.state || 'unknown';
      const visibleError = scene?.error || activeTask?.failure || activeTask?.progress?.error || pipeline?.current?.error || pipeline?.missing_binding;
      const unavailable = record.error || ['unavailable', 'partial'].includes(value?.scenes?.status) ||
        value?.sources?.some((source) => ['index_error', 'record_error'].includes(source.status));
      const details = [];
      if (pipeline) details.push(h('div', {className: 'bfw-live-line'},
        h('div', {className: 'bfw-muted'}, t('workspacePipeline')),
        h('span', {className: 'bfw-code', title: pipeline.label}, displayRef(pipeline.label), ' '),
        status(pipeline.state, t),
        h('p', null, t('persistedSteps') + ': ' + pipeline.completed + ' / ' + (pipeline.total ?? '—')),
        pipeline.total !== null && pipeline.total > 0 && h('progress', {max: pipeline.total, value: pipeline.completed, 'aria-label': t('persistedSteps')}),
        pipeline.current && h('p', null, t('currentStep') + ': ' + pipeline.current.id + ' · ' + (pipeline.current.uses || '') +
          (pipeline.current.state === 'unknown' ? ' · ' + t('unrecordedStep') : '')),
        (pipeline.missing_binding || pipeline.current?.error || pipeline.next) && h('p', {className: 'bfw-muted'},
          t('reason') + ': ' + (pipeline.missing_binding || pipeline.current?.error || pipeline.next))));
      if (jobs.length) details.push(select(t('sceneJobs'), selected, selectScene,
        jobs.map((row) => [row.run_id, row.run_id + ' · ' + t(lifecycle(row.state))])));
      if (scene) {
        details.push(h('p', null, status(lifecycle(scene.state), t), ' · ' + t('completedTasks') + ': ' +
          tasks.filter((row) => row.state === 'SUCCEEDED').length + ' / ' + tasks.length));
        if (scene.error) details.push(h('p', {className: 'bfw-error'}, scene.error));
        for (const row of tasks.slice(0, 12)) {
          const progress = row.progress || {}, revisions = row.evidence?.captured_revisions || [];
          details.push(h('div', {className: 'bfw-live-task', key: row.id, 'data-production-task': row.id},
            h('div', null, h('span', {className: 'bfw-code'}, row.id), ' ', status(lifecycle(row.state), t)),
            h('p', null, t('phase') + ': ' + (row.phase || '—') +
              (progress.stage ? ' · ' + t('workerStage') + ': ' + progress.stage : '') + ' · r' + row.revision),
            progress.age_seconds !== undefined && h('p', {className: 'bfw-muted'}, t('workerAge') + ': ' + progress.age_seconds + ' s'),
            progress.total_bytes > 0 && h('p', null, t('transfer') + ': ' +
              ((progress.bytes_received || 0) / 1048576).toFixed(1) + ' / ' + (progress.total_bytes / 1048576).toFixed(1) + ' MB'),
            row.queue && h('p', {className: 'bfw-warning'}, t('waiting') + ': ' + row.queue.reason + (row.queue.blocking_task_id ? ' · ' + row.queue.blocking_task_id : '')),
            (row.failure || progress.error) && h('pre', {className: 'bfw-json bfw-error'}, JSON.stringify(row.failure || progress.error, null, 2)),
            h('p', {className: 'bfw-muted'}, t('capturedViews') + ': ' + revisions.reduce((n, r) => n + r.views, 0) +
              ' · ' + t('actionTraces') + ': ' + revisions.reduce((n, r) => n + r.action_traces, 0)),
            row.summary && h('p', null, t('accepted') + ': ' + (row.summary.accepted ?? '—') + ' / ' + (row.summary.target_items ?? '—')),
            row.quality && h('p', {className: 'bfw-muted'}, t('publication') + ': ' + row.quality.publication_status + ' · ' +
              t('approval') + ': ' + t(row.quality.benchmark_approved ? 'yes' : 'no')),
            row.downloads?.length > 0 && h('p', {className: 'bfw-code'}, row.downloads.join(' · '))));
        }
        if (tasks.length > 12) details.push(h('p', {className: 'bfw-muted'}, t('taskLimit')));
      }
      if (!scene && !pipeline && !record.loading) details.push(empty(t('noProduction')));
      if (value?.operations?.length > 0) details.push(h('details', null,
        h('summary', null, t('recentOperations')),
        table([t('operator'), t('state'), t('updated')], value.operations.slice(0, 8).map((row) =>
          [row.tool, status(row.state, t), row.started_at || '—']))));
      return h('section', {className: 'bfw-production', 'data-production-monitor': true, 'aria-label': t('productionMonitor')},
        h('div', {className: 'bfw-toolbar'}, h('strong', null, t('productionMonitor')),
          h('span', {className: 'bfw-pill ' + (unavailable ? 'failed' : 'running'), 'data-live-state': unavailable ? 'stale' : record.loading ? 'loading' : 'live'},
            t(unavailable ? 'staleSnapshot' : record.loading ? 'loading' : visible ? 'autoRefresh' : 'pollingPaused'))),
        h('p', {className: 'bfw-production-summary'},
          h('span', {role: 'status', 'aria-live': 'polite', 'aria-atomic': true},
            status(productionState, t), ' ',
            activeTask && h('span', {className: 'bfw-code'}, activeTask.id), ' ',
            activeTask?.phase && h('span', null, t('phase') + ': ' + activeTask.phase), ' ',
            pipeline && h('span', null, t('persistedSteps') + ': ' + pipeline.completed + ' / ' + (pipeline.total ?? '—'))),
          h('span', {className: 'bfw-muted'}, t('lastObserved') + ': ' + (record.updatedAt ? new Date(record.updatedAt).toLocaleTimeString() : '—'))),
        record.error && h('p', {className: 'bfw-error', role: 'alert'}, t('retainedSnapshot') + ' · ' + record.error),
        unavailable && !record.error && h('p', {className: 'bfw-error'}, t('partialObservation')),
        visibleError && h('p', {className: 'bfw-error', role: 'alert'},
          typeof visibleError === 'string' ? visibleError : JSON.stringify(visibleError)),
        value?.scenes?.status === 'not_configured' && h('p', {className: 'bfw-muted'}, t('observerNotConfigured')),
        h('details', {className: 'bfw-live-details'},
          h('summary', null, t('productionDetails')),
          ...details));
    }

    function blueprintState(sessionId) {
      return JSON.parse(localStorage.getItem('bfw:blueprint:' + sessionId) || 'null') ||
        {objective: '', target: 300, budget: 100, source: 'simulator', templates: [], savedAt: null};
    }
    function allocations(blueprint) {
      const count = blueprint.templates.length;
      return blueprint.templates.map((template, i) => ({template_id: template.id,
        target_items: Math.floor(blueprint.target / count) + (i < blueprint.target % count ? 1 : 0)}));
    }
    function instruction(stage, blueprint, runLabel, version) {
      const actions = {
        S1: '请根据目标检索能力与出题模板，检查所选模板的实际适配器，制定可组合的生产计划，列出输入、数量、来源和预期产物；本轮只规划。',
        S2: '请基于已保存的需求和计划准备数据来源。场景任务先复用或生成场景，再采集公开观测与原生状态；检查本步实际需要的外部工具。保留参考、场景和采集回执。',
        S3: '请读取现有采集产物，整理证据、公开标定、对象和时序状态，绑定来源。区分模型候选标注和官方/程序/仿真 GT，保留产物父子关系和缺失证据。',
        S4: '请基于现有场景和已结构化证据，按所选模板与数量合成评测题。使用既有 pipeline 工具保存公开问题、媒体、分区和版本；信息不足时修复来源，不编造真值。',
        S5: '请对选定运行与数据集执行既有确定性验证，汇总公开信息充分性、GT来源、分区、覆盖和失败项，记录局部修复建议并生成报告和交付包。没有真实模型响应时不要拟合 IRT。',
      };
      return ['BenchForge ' + stage + ' / SpatialForge', actions[stage],
        JSON.stringify({objective: blueprint.objective, target_items: blueprint.target, storage_limit_gb: blueprint.budget,
          source: blueprint.source, template_allocations: allocations(blueprint), run: runLabel || null, dataset_version: version || null}, null, 2),
        '复用本会话工作区和现有工具；不修改 DSH 源码、模型部署、仿真器配置、验收规则或 GT。执行状态必须以实际产物回执为准。'].join('\n\n');
    }

    function Blueprint({blueprint, setBlueprint, catalog, catalogQuery, setCatalogQuery, catalogPage, setCatalogPage,
      capability, setCapability, save, prepare, retry, t}) {
      const update = (key, value) => setBlueprint((old) => ({...old, [key]: value, savedAt: null,
        ...(key === 'templates' ? {target: Math.max(old.target, value.length)} : {}),
        ...(key === 'target' ? {target: Math.max(value, old.templates.length)} : {})}));
      const selected = new Set(blueprint.templates.map((row) => row.id));
      const toggle = (row) => update('templates', selected.has(row.id)
        ? blueprint.templates.filter((item) => item.id !== row.id) : [...blueprint.templates, {id: row.id, title: row.title}]);
      return h(React.Fragment, null,
        card(t('blueprint'), h('div', {className: 'bfw-form'},
          h('label', {className: 'bfw-label bfw-wide'}, t('objective'), h('textarea', {className: 'bfw-input bfw-textarea',
            value: blueprint.objective, placeholder: t('objectivePlaceholder'), onChange: (e) => update('objective', e.target.value)})),
          h('label', {className: 'bfw-label'}, t('targetItems'), h('input', {className: 'bfw-input', type: 'number', min: 1, step: 1,
            value: blueprint.target, onChange: (e) => update('target', Math.max(1, Math.floor(Number(e.target.value) || 1)))})),
          h('label', {className: 'bfw-label'}, t('storageBudget'), h('input', {className: 'bfw-input', type: 'number', min: 1,
            value: blueprint.budget, onChange: (e) => update('budget', Math.max(1, Number(e.target.value) || 1))})),
          select(t('sourceType'), blueprint.source, (value) => update('source', value), ['simulator', 'program', 'official'].map((id) => [id, t(id)])))),
        card(t('selectedTemplates'), h(React.Fragment, null,
          blueprint.templates.length ? blueprint.templates.map((row, i) => h('div', {className: 'bfw-selected', key: row.id},
            h('span', null, h('span', {className: 'bfw-code'}, row.id), ' · ', row.title),
            h('span', null, allocations(blueprint)[i].target_items + ' ' + t('item')), button(t('removeTemplate'), () => toggle(row), {'aria-label': t('removeTemplate') + ' ' + row.id}))) : empty(t('noSelection')),
          h('div', {className: 'bfw-toolbar'}, button(t('saveBlueprint'), save), button(t('preparePlan'), prepare, {className: 'bfw-button bfw-action'})),
          blueprint.savedAt && h('p', {className: 'bfw-muted'}, t('savedAt') + ': ' + new Date(blueprint.savedAt).toLocaleString()))),
        card(t('templateCatalog'), h(React.Fragment, null,
          h('p', {className: 'bfw-muted'}, t('catalogDesign')),
          catalog.value && h('div', {className: 'bfw-counts'}, h('span', null, catalog.value.task_count + ' ' + t('task')), h('span', null, catalog.value.template_count + ' ' + t('template'))),
          h('div', {className: 'bfw-toolbar'}, h('input', {className: 'bfw-input', 'aria-label': t('searchTemplates'), value: catalogQuery,
            placeholder: t('search'), onChange: (e) => {setCatalogQuery(e.target.value); setCatalogPage(1);}}),
          select(t('capability'), capability, (id) => {setCapability(id); setCatalogPage(1);}, [['', t('all')], ...(catalog.value?.capabilities || []).map((id) => [id, id])])),
          catalog.error && h('p', {className: 'bfw-error', role: 'alert'}, catalog.error),
          catalog.loading ? empty(t('loading')) : catalog.error && !catalog.value ? button(t('retry'), retry) :
            !catalog.value?.items.length ? h('div', {className: 'bfw-empty', role: 'status'}, t('noMatchingTemplates'), ' ',
              button(t('clearFilters'), () => {setCatalogQuery(''); setCapability(''); setCatalogPage(1);})) :
            h('div', {className: 'bfw-catalog'}, (catalog.value?.items || []).map((row) =>
            h('article', {className: 'bfw-template', key: row.id, 'data-selected': selected.has(row.id)},
              h('header', null, h('strong', null, row.title), button(t(selected.has(row.id) ? 'removeTemplate' : 'selectTemplate'), () => toggle(row), {'aria-pressed': selected.has(row.id)})),
              h('p', {className: 'bfw-code'}, row.id + ' · ' + row.capabilities.join(' / ')),
              h('p', {className: 'bfw-muted'}, row.task_name),
              h('details', null, h('summary', null, t('details')), h('p', null, row.effective_measurement_conditions), h('p', null, row.prompt_template))))),
          h('div', {className: 'bfw-pagination'}, button(t('previous'), () => setCatalogPage(catalogPage - 1), {disabled: catalogPage <= 1}),
            h('span', null, catalogPage + ' / ' + (catalog.value?.pages || 1)),
            button(t('nextPage'), () => setCatalogPage(catalogPage + 1), {disabled: catalog.loading || !catalog.value || catalogPage >= catalog.value.pages})))));
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
            h('p', {className: 'bfw-muted'}, t('shapeNote')),
            record.artifacts_truncated && h('p', null, t('truncated')),
            artifacts.length ? artifacts.map((artifact) => h('details', {className: 'bfw-artifact', key: artifact.artifact_id},
              h('summary', null, status(artifact.status, t), ' ', artifact.artifact_type, ' · v', artifact.version),
              h('div', {className: 'bfw-code bfw-detail-row'}, artifact.artifact_id),
              h('div', {className: 'bfw-detail-row'}, t('producer') + ': ' + artifact.producer),
              h('div', {className: 'bfw-detail-row'}, t('parents')), json(artifact.parents),
              h('div', {className: 'bfw-detail-row'}, t('evidence')), json(artifact.evidence_refs),
              h('div', {className: 'bfw-detail-row'}, t('contracts')), json(artifact.contract_results))) : empty(t('noArtifacts')))),
          card(t('repairs'), h(React.Fragment, null,
            h('p', {className: 'bfw-muted'}, t('repairNote')),
            record.repairs.length ? record.repairs.map((repair, i) => h('details', {className: 'bfw-artifact', key: i},
              h('summary', null, status(repair.status, t), ' ', t(repair.operator)),
              h('div', {className: 'bfw-code bfw-detail-row'}, repair.artifact_id),
              h('p', null, t('reason') + ': ' + repair.reason),
              h('p', null, t('repairScope') + ': ' + repair.scope),
              h('p', null, t('newRun') + ': ' + t(repair.requires_new_run ? 'yes' : 'no')))) : empty(t('noRepairs'))))));
    }
    function StageProgress({stage, pipeline, scene, record, t}) {
      const tasks = (scene?.tasks || []).filter((row) => sceneStage(row) === stage.id);
      const steps = scene ? tasks.map((row) => ({id: row.id, state: lifecycle(row.state),
        label: row.progress?.stage || row.phase, error: row.failure || row.progress?.error,
        queue: row.queue, age: row.progress?.age_seconds})) : (pipeline?.steps || []).filter((row) => row.stage === stage.id)
        .map((row) => ({...row, label: row.uses}));
      const completed = steps.filter((row) => row.state === 'completed').length;
      const current = steps.find((row) => ['running', 'waiting', 'needs_evidence', 'failed'].includes(row.state)) ||
        steps.find((row) => row.state !== 'completed');
      const state = stageState(stage.id, pipeline, scene);
      const stale = record.error || ['partial', 'unavailable'].includes(record.value?.scenes?.status);
      return h('section', {className: 'bfw-stage-progress', 'data-stage-progress': stage.id, 'aria-label': t('stageProgress')},
        h('div', {className: 'bfw-progress-caption'}, h('strong', null, t('stageProgress')), status(state, t),
          h('span', {className: 'bfw-muted'}, steps.length ? completed + ' / ' + steps.length + ' · ' + t('observedSteps') : t('waitingForReceipt'))),
        steps.length ? h('progress', {max: steps.length, value: completed, 'aria-label': t('stageProgress')}) :
          h('div', {className: 'bfw-progress-track', 'aria-label': t('unmeasuredProgress')}),
        h('div', {className: 'bfw-progress-caption', role: 'status', 'aria-live': 'polite'},
          h('span', null, current ? current.id + (current.label ? ' · ' + current.label : '') : t(steps.length ? 'knownProgress' : 'noStageSteps')),
          h('span', {className: 'bfw-muted'}, t('lastObserved') + ': ' + (record.updatedAt ? new Date(record.updatedAt).toLocaleTimeString() : '—'))),
        stale && h('p', {className: 'bfw-error'}, t('staleSnapshot')),
        current?.error && h('p', {className: 'bfw-error', role: 'alert'}, typeof current.error === 'string' ? current.error : JSON.stringify(current.error)),
        current?.queue && h('p', null, t('waiting') + ': ' + current.queue.reason),
        steps.length > 0 && h('details', null, h('summary', null, t('stageProcess')),
          table([t('steps'), t('state'), t('phase')], steps.map((row) => [row.id, status(row.state, t), row.label || '—']))));
    }
    function PreviewDialog({item, close, t}) {
      const ref = React.useRef(null);
      const [content, setContent] = React.useState(null);
      const [error, setError] = React.useState('');
      React.useEffect(() => {
        const dialog = ref.current;
        const trigger = document.activeElement;
        dialog.showModal();
        return () => {dialog.close(); trigger?.focus();};
      }, []);
      React.useEffect(() => {
        if (item.data || !item.url || ['image', 'video'].includes(item.kind)) return;
        const controller = new AbortController();
        fetch(item.url, {signal: controller.signal}).then(async (response) => {
          if (!response.ok) throw new Error('HTTP ' + response.status);
          return item.kind === 'json' ? response.json() : response.text();
        }).then(setContent).catch((reason) => {if (reason.name !== 'AbortError') setError(reason.message);});
        return () => controller.abort();
      }, [item]);
      const data = item.data || content;
      return h('dialog', {ref, className: 'bfw-preview-dialog', 'aria-label': t('preview') + ' · ' + item.title,
        onCancel: (event) => {event.preventDefault(); close();}, onClick: (event) => {if (event.target === ref.current) close();}},
        h('div', {className: 'bfw-preview-header'}, h('h2', null, item.title), button(t('previewClose'), close)),
        item.kind === 'image' ? h('img', {src: item.url, alt: item.title}) : item.kind === 'video' ?
          h('video', {src: item.url, controls: true, preload: 'metadata'}) : error ? h('p', {role: 'alert'}, t('artifactReadFailed') + ' ' + error) :
          data ? h(React.Fragment, null,
            item.image_url && h('div', {className: 'bfw-annotation-image'}, h('img', {src: item.image_url, alt: item.title}),
              data.image_size?.width > 0 && h('svg', {viewBox: '0 0 ' + data.image_size.width + ' ' + data.image_size.height,
                role: 'img', 'aria-label': t('annotationGallery')}, (data.visible_objects || []).filter((row) => row.bbox_2d?.xyxy?.length === 4).map((row, index) => {
                  const [x1, y1, x2, y2] = row.bbox_2d.xyxy;
                  return h('g', {key: row.object_id || index}, h('rect', {x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: 'none', stroke: '#4ade80', strokeWidth: 2}),
                    h('text', {x: x1 + 4, y: Math.max(18, y1 - 5), fill: '#4ade80', stroke: '#102020', strokeWidth: .5,
                      fontSize: Math.max(14, data.image_size.width / 65)}, row.label || row.object_id));
                }))),
            typeof data === 'string' ? h('pre', {className: 'bfw-json'}, data) : json(data)) : empty(t('loading')));
    }
    function ArtifactGallery({items, selectable, selected, toggle, preview, t}) {
      if (!items.length) return empty(t('artifactPending'));
      return h(React.Fragment, null,
        selectable && h('p', {className: 'bfw-muted'}, t('chooseSceneHint') + ' · ' + t('selectedScenes') + ': ' + selected.length),
        h('div', {className: 'bfw-gallery'}, items.map((item) => h('article', {className: 'bfw-preview-card', key: item.url || item.title,
          'data-preview-kind': item.kind, 'data-selected': selected.some((row) => row.url === item.url)},
          h('button', {type: 'button', className: 'bfw-preview-open', onClick: () => preview(item), 'aria-label': t('preview') + ' ' + item.title},
            item.kind === 'image' || item.image_url ? h('img', {src: item.image_url || item.url, loading: 'lazy', alt: item.title}) : item.kind === 'video' ?
              h('video', {src: item.url, preload: 'metadata', muted: true, 'aria-label': item.title}) :
              h('div', {className: 'bfw-document-thumb'}, h('span', null, item.kind === 'json' ? '{ }' : '≡'), h('span', null, item.title)),
            h('strong', null, item.title), h('span', {className: 'bfw-muted'}, t('preview'))),
          selectable && h('label', {className: 'bfw-scene-check'}, h('input', {type: 'checkbox', checked: selected.some((row) => row.url === item.url),
            'aria-label': t('selectArtifact') + ' ' + item.title, onChange: () => toggle(item)}), t('selectArtifact')),
          item.task_id && h('div', {className: 'bfw-code bfw-muted'}, item.task_id + (item.revision === undefined ? '' : ' · r' + item.revision))))));
    }
    function SendDialog({payload, draft, attachmentCount, sending, error, confirm, close, t}) {
      const ref = React.useRef(null);
      React.useEffect(() => {
        const trigger = document.activeElement;
        const dialog = ref.current;
        dialog.showModal();
        return () => {dialog.close(); trigger?.focus();};
      }, []);
      return h('dialog', {ref, className: 'bfw-preview-dialog', 'data-stage-confirm': true, 'aria-label': t('confirmTitle'),
        onCancel: (event) => {event.preventDefault(); if (!sending) close();}},
        h('h2', null, t('confirmTitle')), h('p', null, t('confirmSendNote')),
        draft && h('details', {open: true}, h('summary', null, t('existingDraft')), h('pre', {className: 'bfw-json'}, draft)),
        attachmentCount > 0 && h('p', null, t('existingAttachments') + ': ' + attachmentCount),
        h('pre', {className: 'bfw-json'}, payload.text),
        error && h('p', {className: 'bfw-error', role: 'alert'}, error),
        h('div', {className: 'bfw-stage-actions'}, button(t('cancel'), close, {disabled: sending}),
          button(t(sending ? 'sending' : 'confirmSend'), confirm, {className: 'bfw-button bfw-action', disabled: sending})));
    }
    function PlanProduct({plan, blueprint, artifacts, preview, t}) {
      if (!plan) return h(React.Fragment, null, empty(t('planPending')),
        blueprint.objective && h('article', {className: 'bfw-plan-document'}, h('span', {className: 'bfw-pill'}, t('draftOnly')),
          h('h3', null, blueprint.objective), h('p', null, t('targetItems') + ': ' + blueprint.target + ' · ' + t('sourceType') + ': ' + t(blueprint.source)),
          table([t('template'), t('allocate')], allocations(blueprint).map((row) => [row.template_id, row.target_items]))));
      return h('article', {className: 'bfw-plan-document'}, h('span', {className: 'bfw-pill'}, t('persistedPlan')),
        h('h3', null, typeof plan.objective === 'string' ? plan.objective : plan.title || t('blueprint')),
        plan.inputs && h('dl', {className: 'bfw-definition'}, Object.entries(plan.inputs).map(([key, value]) => h('div', {key},
          h('dt', null, key), h('dd', null, typeof value === 'object' ? JSON.stringify(value) : String(value))))),
        plan.steps?.length ? table([t('steps'), t('operator'), t('details')], plan.steps.map((row) =>
          [row.id, row.uses, row.title || row.description || (row.depends_on || []).join(' → ') || '—'])) : null,
        artifacts.length > 0 && h(ArtifactGallery, {items: artifacts, selected: [], preview, t}),
        h('details', null, h('summary', null, t('plan')), json(plan)));
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
        h('dl', {className: 'bfw-definition'}, Object.entries(data).filter(([, value]) => value === null || typeof value !== 'object').map(([key, value]) =>
          h('div', {key}, h('dt', null, t(key)), h('dd', null, typeof value === 'boolean' ? t(value ? 'yes' : 'no') : String(value ?? '—'))))),
        h('details', null, h('summary', null, t('details')), json(data)));
    }
    function Quality({report, t}) {
      if (!report) return empty(t('noReport'));
      return h(React.Fragment, null,
        h('p', {className: 'bfw-muted'}, t('reportNote')),
        h('div', {className: 'bfw-stats'}, ['requested', 'accepted', 'shortfall', 'scene_groups'].map((key) =>
          h('div', {className: 'bfw-stat', key}, t(key), h('strong', null, report[key] ?? '—')))),
        h('p', null, t('approval') + ': ', report.benchmark_approved === undefined ? '—' : t(report.benchmark_approved ? 'yes' : 'no')),
        card(t('coverage'), table([t('template'), t('accepted')], Object.entries(report.per_template || {}))),
        card(t('rejections'), report.rejections?.length ? json(report.rejections) : empty(t('noRejections'))));
    }

    function Workbench({t, sessionId, useSessions, useInput, inputActions}) {
      const panelRef = React.useRef(null);
      const sampleHeadingRef = React.useRef(null);
      const sampleTriggerRef = React.useRef(null);
      const visible = usePanelVisible(panelRef);
      const [route, setRoute] = React.useState(() => initialState(sessionId));
      const [revision, setRevision] = React.useState(0);
      const [sample, setSample] = React.useState(null);
      const [search, setSearch] = React.useState(route.q);
      const [blueprint, setBlueprint] = React.useState(() => blueprintState(sessionId));
      const [notice, setNotice] = React.useState('');
      const [catalogQuery, setCatalogQuery] = React.useState('');
      const [catalogPage, setCatalogPage] = React.useState(1);
      const [capability, setCapability] = React.useState('');
      const [preview, setPreview] = React.useState(null);
      const [selectedScenes, setSelectedScenes] = React.useState([]);
      const [sendPayload, setSendPayload] = React.useState(null);
      const [sending, setSending] = React.useState(false);
      const [sendError, setSendError] = React.useState('');
      const submitLock = React.useRef(false);
      const inputState = useInput((state) => state);
      const update = (patch) => setRoute((old) => ({...old, ...patch}));
      const workspacePath = useSessions((state) => state.byId[sessionId]?.cwd || '');
      const conversationRunning = useSessions((state) => Boolean(state.byId[sessionId]?.running));
      const progress = useRecord(workspacePath ? {view: 'progress', workspace_path: workspacePath, session_id: sessionId} : null, revision, 3000, visible);
      const summary = useRecord(workspacePath ? {view: 'summary', workspace_path: workspacePath} : null, revision, 30000, visible);
      const selectedRunId = route.run || summary.value?.runs?.[0]?.id || '';
      const sceneJobs = progress.value?.scenes?.runs || [];
      const scene = sceneJobs.find((row) => row.run_id === route.production) || sceneJobs.find((row) => !row.terminal) || sceneJobs[0];
      const sourceScene = route.run ? null : scene;
      const run = useRecord(workspacePath && selectedRunId ? {view: 'run', run: selectedRunId, workspace_path: workspacePath} : null, revision, 10000, visible);
      const artifactScene = sourceScene?.run_id || (route.run ? run.value?.scene_ids?.[0] : '');
      const sceneArtifacts = useRecord(workspacePath && artifactScene ?
        {view: 'stage_artifacts', scene: artifactScene, run: route.run || '', session_id: sessionId, workspace_path: workspacePath} : null, revision, 10000, visible);
      const catalog = useRecord(route.stage === 'S1'
        ? {view: 'catalog', q: catalogQuery, capability, page: catalogPage, page_size: 12} : null, revision);
      const dataset = useRecord(workspacePath && ['S4', 'S5'].includes(route.stage) && route.dataset ?
        {view: 'dataset', dataset: route.dataset, template: route.template, split: route.split, q: route.q, page: route.page, page_size: route.size, workspace_path: workspacePath} : null, revision, 30000, visible);
      const sampleId = sample?.row_index;
      const currentSample = sample ? dataset.value?.items.find((row) => row.row_index === sampleId &&
        (row.item_id || row.id) === (sample.item_id || sample.id)) : null;
      React.useEffect(() => { localStorage.setItem('bfw:spatialforge:' + sessionId, JSON.stringify(route)); }, [route, sessionId]);
      React.useEffect(() => { setSample(null); }, [route.dataset, route.page, route.size, route.template, route.split, route.q]);
      React.useEffect(() => {setSelectedScenes([]); setPreview(null);}, [route.run, sourceScene?.run_id]);
      React.useEffect(() => {
        if (dataset.value && route.page > Math.max(1, dataset.value.pages)) update({page: Math.max(1, dataset.value.pages)});
      }, [dataset.value, route.page]);
      React.useEffect(() => {
        if (sample && dataset.value && !currentSample) {setSample(null); setNotice(t('sampleRemoved'));}
      }, [dataset.value, sample, currentSample]);
      React.useEffect(() => {
        if (route.stage !== 'S4') return;
        if (sample) sampleHeadingRef.current?.focus();
        else if (sampleTriggerRef.current) {
          const trigger = [...panelRef.current.querySelectorAll('[data-sample-row]')]
            .find((element) => element.dataset.sampleRow === sampleTriggerRef.current);
          (trigger || panelRef.current.querySelector('[aria-label="题目、ID 或任务"]'))?.focus();
          sampleTriggerRef.current = null;
        }
      }, [sampleId, route.stage]);
      const rows = summary.value?.runs || [];
      const datasets = summary.value?.datasets || [];
      const selectedDataset = summary.value?.datasets?.find((row) => row.id === route.dataset);
      const runListing = filteredPage(rows, route.runFilter, route.runListPage, route.runListSize,
        (row) => [row.label, row.id, row.state].join(' '));
      const versionListing = filteredPage(datasets, route.versionFilter, route.versionListPage, route.versionListSize,
        (row) => [row.workspace, row.version, row.run_id, row.state].join(' '));
      const stage = STAGES.find((step) => step.id === route.stage) || STAGES[0];
      const activeRun = rows.find((row) => row.id === selectedRunId);
      const pipeline = progress.value?.pipelines?.find((row) => row.id === selectedRunId) ||
        (!route.run ? progress.value?.pipelines?.find((row) => row.state !== 'completed') || progress.value?.pipelines?.[0] : null);
      const allStageFiles = [...(sourceScene ? [] : run.value?.stage_artifacts || []), ...(sceneArtifacts.value?.items || [])];
      const stageFiles = allStageFiles.filter((row) => row.stage === stage.id).map((row) => ({...row,
        image_url: row.stage === 'S3' && row.kind === 'json' ? allStageFiles.find((image) => image.kind === 'image' &&
          image.task_id === row.task_id && image.revision === row.revision && image.file === row.file?.replace(/\.json$/, '.png'))?.url : undefined}));
      const activePipeline = sourceScene ? null : pipeline;
      const persistedPlan = sourceScene ? sceneArtifacts.value?.plan : run.value?.plan;
      const saveBlueprint = () => {
        const next = {...blueprint, savedAt: new Date().toISOString()};
        localStorage.setItem('bfw:blueprint:' + sessionId, JSON.stringify(next));
        setBlueprint(next); setNotice(t('blueprintSaved'));
      };
      const stepInstruction = instruction(stage.id, blueprint, route.run ? activeRun?.label : sourceScene?.run_id || activeRun?.label, selectedDataset?.version) +
        (persistedPlan ? '\n\n当前已落盘计划（与浏览器草稿区分）：\n' + JSON.stringify(persistedPlan, null, 2) : '') +
        (selectedScenes.length ? '\n\n已选场景产物（请复用）：\n' + JSON.stringify(selectedScenes.map((row) =>
          ({task_id: row.task_id, revision: row.revision, file: row.file, title: row.title})), null, 2) : '');
      const prepare = () => {
        if (stage.id === 'S1' && !blueprint.objective.trim() && !persistedPlan) {setNotice(t('requiredGoal')); return;}
        if (typeof inputActions?.submit !== 'function') {setNotice(t('noSendInterface')); return;}
        saveBlueprint();
        const bundle = {schema: 'benchforge.stage_request/v1', stage: stage.id, session_id: sessionId,
          workspace_path: workspacePath, pipeline_run: route.run || null, scene_run: sourceScene?.run_id || null,
          dataset: selectedDataset ? {id: selectedDataset.id, version: selectedDataset.version} : null,
          blueprint, saved_plan: persistedPlan || null,
          selected_scenes: selectedScenes.map(({task_id, revision, file, title}) => ({task_id, revision, file, title})),
          artifacts: stageFiles.map(({task_id, revision, file, title, kind, url}) => ({task_id, revision, file, title, kind, url}))};
        setSendError('');
        setSendPayload({text: instruction(stage.id, blueprint, route.run ? activeRun?.label : sourceScene?.run_id || activeRun?.label,
          selectedDataset?.version) + '\n\nSpatialForge 任务包：\n```json\n' + JSON.stringify(bundle, null, 2) + '\n```', inserted: false});
      };
      const confirmSend = () => {
        if (submitLock.current || !sendPayload || sendPayload.submitted) return;
        if (['adjudicating', 'submitting'].includes(inputState.phase) || inputState.claim) {setSendError(t('sendBusy')); return;}
        submitLock.current = true; setSending(true); setSendError('');
        try {
          if (!sendPayload.inserted) {
            const span = inputActions.captureInsertion();
            if (!inputActions.insertText('\n' + sendPayload.text + '\n', {...span, end: span.start})) {
              setSendError(t('draftBusy')); return;
            }
            sendPayload.inserted = true;
          }
          inputActions.submit();
          sendPayload.submitted = true;
          setSendPayload(null); setNotice(t('sent'));
        } catch (error) {
          setSendError(t('sendFailed') + ' ' + error.message);
        } finally {submitLock.current = false; setSending(false);}
      };
      const openRun = (id) => update({run: id});
      const changeDataset = (id) => { update({dataset: id, template: '', split: '', q: '', page: 1}); setSearch(''); };
      const openDataset = (id) => {changeDataset(id); update({stage: 'S4'});};
      const openSample = (item) => {sampleTriggerRef.current = String(item.row_index); setSample(item);};
      const readFailure = () => h('div', {className: 'bfw-empty'}, t('readFailed'), ' ', button(t('retry'), () => setRevision((value) => value + 1)));
      const runTable = (items) => items.length ? table([t('workspace'), t('runs'), t('state'), t('steps'), t('artifacts'), t('updated')],
        items.map((item) => [item.workspace, button(displayRef(item.label), () => openRun(item.id), {title: item.label}), status(item.state, t), item.steps, item.artifact_total ?? '—', item.updated_at])) : empty(t('noRuns'));
      const versionOptions = [['', t('chooseDataset')], ...(summary.value?.datasets || []).map((row) =>
        [row.id, row.workspace + ' / ' + displayRef(row.version)])];
      const toggleScene = (item) => setSelectedScenes((old) => old.some((row) => row.url === item.url)
        ? old.filter((row) => row.url !== item.url) : [...old, item]);
      const chooseProduction = (value) => {
        setPreview(null);
        if (value.startsWith('scene:')) update({production: value.slice(6), run: ''});
        else update({run: value});
      };
      const productionOptions = [[sourceScene ? 'scene:' + sourceScene.run_id : '', t('automaticRecord')],
        ...sceneJobs.filter((row) => row.run_id !== sourceScene?.run_id).map((row) => ['scene:' + row.run_id, row.run_id + ' · ' + t(lifecycle(row.state))]),
        ...rows.map((row) => [row.id, displayRef(row.label) + ' · ' + t(row.state)])];
      const listControls = (listing, query, label, onQuery, onPage, pageSize, onPageSize) => h('div', {className: 'bfw-list-controls'},
        h('div', {className: 'bfw-toolbar'},
          h('input', {className: 'bfw-input', type: 'search', 'aria-label': label, placeholder: label, value: query, onChange: (e) => onQuery(e.target.value)}),
          select(t('pageSize'), String(pageSize), (value) => onPageSize(Number(value)), [12, 24, 48].map((value) => [String(value), String(value)])),
          h('span', {className: 'bfw-muted'}, t('matches') + ': ' + listing.total)),
        h('div', {className: 'bfw-pagination'},
          button(t('previous'), () => onPage(listing.page - 1), {disabled: listing.page <= 1}),
          h('span', null, t('page') + ' ' + listing.page + ' / ' + listing.pages),
          button(t('nextPage'), () => onPage(listing.page + 1), {disabled: listing.page >= listing.pages})));
      const data = dataset.value;
      const runHistory = h('details', {'data-run-history': true}, h('summary', null, t('runHistory')),
        h('p', {className: 'bfw-muted'}, t('scope')),
        h('div', {className: 'bfw-counts'}, h('span', null, t('runCount') + ': ' + (summary.value ? rows.length : '—')),
          h('span', null, t('datasetCount') + ': ' + (summary.value ? datasets.length : '—'))),
        listControls(runListing, route.runFilter, t('runFilter'),
          (value) => update({runFilter: value, runListPage: 1}), (page) => update({runListPage: page}),
          route.runListSize, (size) => update({runListSize: size, runListPage: 1})),
        summary.loading ? empty(t('loading')) : summary.error && !summary.value ? readFailure() :
          runListing.total ? runTable(runListing.items) : empty(rows.length ? t('noMatchingRuns') : t('noRuns')));
      const datasetDirectory = h('details', {'data-dataset-directory': true, open: !route.dataset},
        h('summary', null, t('directory')), h('p', {className: 'bfw-muted'}, t('datasetNote')),
        summary.loading ? empty(t('loading')) : summary.error && !summary.value ? readFailure() : datasets.length ? h(React.Fragment, null,
          listControls(versionListing, route.versionFilter, t('versionFilter'),
            (value) => update({versionFilter: value, versionListPage: 1}), (page) => update({versionListPage: page}),
            route.versionListSize, (size) => update({versionListSize: size, versionListPage: 1})),
          versionListing.total ? table([t('workspace'), t('version'), t('generationAccepted'), t('state'), t('open')], versionListing.items.map((row) =>
            [row.workspace, h('span', {className: 'bfw-code bfw-version', title: row.version}, displayRef(row.version)), row.report?.accepted ?? '—',
              status(row.state, t), button(t('browse'), () => openDataset(row.id))])) : empty(t('noMatchingVersions'))) : empty(t('noDatasets')));
      const datasetBrowser = h('div', {'data-dataset-browser': true},
        h('p', {className: 'bfw-muted'}, t('publicNote')),
        h('form', {className: 'bfw-toolbar', onSubmit: (e) => {e.preventDefault(); update({q: search, page: 1});}},
          select(t('template'), route.template, (id) => update({template: id, page: 1}), [['', t('all')], ...(data?.facets.templates || []).map((id) => [id, id])]),
          select(t('split'), route.split, (id) => update({split: id, page: 1}), [['', t('all')], ...(data?.facets.splits || []).map((id) => [id, id])]),
          h('input', {className: 'bfw-input', 'aria-label': t('search'), placeholder: t('search'), value: search, onChange: (e) => setSearch(e.target.value)}),
          h('button', {className: 'bfw-button', type: 'submit'}, t('apply'))),
        h('div', {className: 'bfw-toolbar'},
          select(t('pageSize'), String(route.size), (size) => update({size: Number(size), page: 1}), [24, 48, 96].map((size) => [String(size), String(size)])),
          button(t('grid'), () => update({layout: 'grid'}), {'aria-pressed': route.layout === 'grid'}),
          button(t('table'), () => update({layout: 'table'}), {'aria-pressed': route.layout === 'table'}),
          h('span', {className: 'bfw-muted'}, t('matches') + ': ' + (data?.total ?? '—') + ' / ' + t('total') + ': ' + (data?.all ?? '—'))),
        dataset.loading ? empty(t('loading')) : dataset.error && !dataset.value ? readFailure() : currentSample ? h(React.Fragment, null,
          button(t('close'), () => setSample(null)), h('h3', {className: 'bfw-code', ref: sampleHeadingRef, tabIndex: -1}, currentSample.item_id || currentSample.id),
          h('p', {className: 'bfw-question'}, currentSample.question), h('h3', null, t('media')),
          currentSample.media?.length ? currentSample.media.map((src, i) => h('img', {className: 'bfw-observation', key: src, src, alt: t('media') + ' ' + (i + 1)})) : empty(t('noMedia')),
          h('details', null, h('summary', null, t('details')), json({...currentSample, media: undefined}))) :
          !data?.items.length ? h('div', {className: 'bfw-empty'}, t('noItems'),
            (route.template || route.split || route.q) && button(t('clearFilters'), () => changeDataset(route.dataset))) : route.layout === 'table' ?
            table([t('item'), t('template'), t('split'), t('question'), t('open')], data.items.map((item) =>
              [item.item_id || item.id, item.template_id || '—', item.split || '—', item.question,
                button(t('open'), () => openSample(item), {'data-sample-row': String(item.row_index), 'aria-label': t('open') + ' ' + (item.item_id || item.id)})])) :
            h('div', {className: 'bfw-items'}, data.items.map((item) => h('button', {type: 'button', className: 'bfw-item', key: item.row_index,
              'data-sample-row': String(item.row_index), onClick: () => openSample(item)},
              item.media?.[0] && h('img', {src: item.media[0], loading: 'lazy', alt: t('media')}),
              h('span', {className: 'bfw-code'}, item.item_id || item.id), h('p', {className: 'bfw-question-preview'}, item.question),
              h('span', {className: 'bfw-muted'}, (item.template_id || '') + ' · ' + (item.split || ''))))),
        !currentSample && h('div', {className: 'bfw-pagination'},
          button(t('previous'), () => update({page: route.page - 1}), {disabled: route.page <= 1 || dataset.loading}),
          h('span', null, t('page') + ' ' + route.page + ' / ' + Math.max(1, data?.pages || 1)),
          button(t('nextPage'), () => update({page: route.page + 1}), {disabled: !data || route.page >= data.pages || dataset.loading})));
        const plan = sourceScene ? sceneArtifacts.value?.plan : run.value?.plan;
        const filesError = sceneArtifacts.error || run.error;
        const productFiles = stageFiles.filter((row) => row.url || row.data);
        let product;
        if (stage.id === 'S1') product = h(React.Fragment, null,
          h(PlanProduct, {plan, blueprint, artifacts: productFiles, preview: setPreview, t}),
          h('details', {className: 'bfw-plan-editor', open: !plan && !blueprint.objective}, h('summary', null, t('planEditor')),
            h(Blueprint, {blueprint, setBlueprint, catalog, catalogQuery, setCatalogQuery, catalogPage, setCatalogPage,
              capability, setCapability, save: saveBlueprint, prepare, retry: () => setRevision((value) => value + 1), t})),
          runHistory);
        else if (['S2', 'S3'].includes(stage.id)) product = h(React.Fragment, null,
          stage.id === 'S3' && h('p', {className: 'bfw-muted'}, t('annotationNote')),
          filesError && h('p', {className: 'bfw-error', role: 'alert'}, t('artifactReadFailed') + ' ' + filesError),
          (sceneArtifacts.loading || run.loading) && empty(t('loading')),
          h(ArtifactGallery, {items: productFiles, selectable: stage.id === 'S2', selected: selectedScenes,
            toggle: toggleScene, preview: setPreview, t}));
        else if (stage.id === 'S4') product = h('div', {className: 'bfw-evaluation-grid'},
          h('section', {className: 'bfw-evaluation-config'}, h('h3', null, t('evaluationConfig')),
            select(t('chooseDataset'), route.dataset, changeDataset, versionOptions),
            h('dl', {className: 'bfw-definition'},
              h('div', null, h('dt', null, t('version')), h('dd', null, selectedDataset ? displayRef(selectedDataset.version) : '—')),
              h('div', null, h('dt', null, t('targetItems')), h('dd', null, dataset.value?.report?.requested ?? plan?.inputs?.target_items ?? '—')),
              h('div', null, h('dt', null, t('sourceType')), h('dd', null, dataset.value?.report?.source || '—'))),
            productFiles.length > 0 && h(ArtifactGallery, {items: productFiles, selected: [], preview: setPreview, t}),
            datasetDirectory),
          h('section', {className: 'bfw-evaluation-questions'}, h('h3', null, t('questionTable')),
            route.dataset ? datasetBrowser : empty(t('chooseDataset'))));
        else product = h(React.Fragment, null,
          select(t('chooseDataset'), route.dataset, changeDataset, versionOptions),
          dataset.error && h('p', {className: 'bfw-error'}, dataset.error),
          (dataset.value?.report || selectedDataset?.report) && h(Quality, {report: dataset.value?.report || selectedDataset?.report, t}),
          h(ReportProduct, {item: productFiles[0], observedAt: sourceScene ? sceneArtifacts.updatedAt : run.updatedAt, t}),
          productFiles.length > 0 && h('details', null, h('summary', null, t('artifactFiles')),
            h(ArtifactGallery, {items: productFiles, selected: [], preview: setPreview, t})));
      const body = h(React.Fragment, null,
          h(StageProgress, {stage, pipeline: activePipeline, scene: sourceScene, record: progress, t}),
          h('div', {className: 'bfw-stage-heading'}, h('span', {className: 'bfw-stage-number'}, stage.id),
            h('div', null, h('h2', null, t(stage.key)), h('p', {className: 'bfw-muted'}, t(stage.key + 'Desc')))),
          h('div', {className: 'bfw-stage-actions'},
            h('div', {className: 'bfw-production-source'}, select(t('productionRecord'), route.run || (sourceScene ? 'scene:' + sourceScene.run_id : ''), chooseProduction, productionOptions)),
            button(t('insertStage'), prepare, {className: 'bfw-button bfw-action', 'data-insert-stage': stage.id})),
          h('section', {className: 'bfw-product', 'data-stage-product': stage.id, 'aria-label': t('keyProduct') + ' · ' + t(stage.key)}, product),
          h('details', null, h('summary', null, t('stepInstruction')),
            h('p', {className: 'bfw-muted'}, t('chatNote')), h('pre', {className: 'bfw-json'}, stepInstruction),
            button(t('copyInstruction'), async () => {try {await navigator.clipboard.writeText(stepInstruction); setNotice(t('copied'));} catch (error) {setNotice(error.message);}})),
          !sourceScene && run.value && h('details', {'data-run-details': true}, h('summary', null, t('runDetails')),
            h(RunDetails, {record: run.value, t})),
          h('div', {className: 'bfw-stage-footer'}, button(t('previousStep'), () => update({stage: STAGES[STAGES.indexOf(stage) - 1].id}), {disabled: stage.id === 'S1'}),
            button(t('nextStep'), () => update({stage: STAGES[STAGES.indexOf(stage) + 1].id}), {disabled: stage.id === 'S5'})));
      return h('div', {ref: panelRef, className: 'bfw-root', 'data-benchforge-workbench': 'true', 'data-spatialforge-panel': 'true'}, h('style', null, styles), h('div', {className: 'bfw-shell'},
        h('header', {className: 'bfw-header'}, h('div', null,
          h('div', {className: 'bfw-kicker'}, 'BENCHFORGEV2 / SPATIALFORGE'), h('h1', {className: 'bfw-title'}, t('panel')),
          h('div', {className: 'bfw-muted'}, t('subtitle'))), button(t('refresh'), () => setRevision((value) => value + 1), {disabled: summary.loading})),
        h('nav', {className: 'bfw-flow', 'aria-label': t('navigation')}, STAGES.map((step) => h('button', {
          className: 'bfw-stage', type: 'button', key: step.id, 'data-stage': step.id,
          'aria-current': stage.id === step.id ? 'step' : undefined,
          onClick: () => {update({stage: step.id}); setNotice('');}},
          h('span', {className: 'bfw-stage-index'}, step.id + ' / 05'), h('strong', null, t(step.key)),
          h('span', {className: 'bfw-stage-state', 'data-stage-state': stageState(step.id, route.run || !scene ? pipeline : null, route.run ? null : scene)},
            t(stageState(step.id, route.run || !scene ? pipeline : null, route.run ? null : scene)))))),
        notice && h('div', {className: 'bfw-notice', role: 'status'}, notice),
        [summary.error, run.error, dataset.error].filter(Boolean).map((error, i) => h('div', {className: 'bfw-error', role: 'alert', key: i}, error)),
        h('section', {id: 'bfw-content-' + sessionId, 'aria-label': t(stage.key)}, body),
        workspacePath && h('details', {className: 'bfw-tools'}, h('summary', null, t('productionMonitor')),
          summary.value && h('p', {className: 'bfw-muted'}, t('snapshot') + ': ' + summary.value.snapshot_at),
          table([t('workspace'), t('state'), t('details')], (summary.value?.sources || []).map((source) =>
            [source.workspace, t(source.status), source.error || (source.truncated ? t('truncated') : source.limit ? source.limit + ' ' + t('limit') : '—')])),
          h(Production, {record: progress, pipeline: activePipeline, scene: sourceScene, selected: scene?.run_id || '',
            selectScene: (id) => update({production: id, run: ''}), visible, conversationRunning, t})),
        preview && h(PreviewDialog, {key: preview.url || preview.title, item: preview, close: () => setPreview(null), t}),
        sendPayload && h(SendDialog, {payload: sendPayload, draft: inputState.draft, attachmentCount: inputState.attachmentIds.length,
          sending, error: sendError, confirm: confirmSend, close: () => setSendPayload(null), t})));
    }
    return {
      inject: ['slots', 'locale', 'sidebarRight', 'sidebarRightTabs'],
      apply(ctx) {
        ctx.effect(() => ctx.locale.register(NS, dictionaries));
        const t = ctx.locale.bind(NS);
        ctx.effect(() => ctx.sidebarRightTabs.register({id: PANEL, kind: PANEL, title: () => t('panel'), keepMounted: true}),
          'benchforge-spatialforge-ui: SpatialForge-only panel page');
        ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({
          name: 'sidebar.right.pane.tab', key: PANEL, locale: NS,
        }, ({useProjection, useSessions, useInput, sessionId, inputActions}) => useProjection('agentPreset') === SPATIALFORGE_PRESET
          ? h(Workbench, {key: sessionId, t, sessionId, useSessions, useInput, inputActions}) : null));
        ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register({
          name: 'conversation.session.header.utilities', id: 'spatialforge-evaluation-launcher', order: 80, locale: NS,
        }, ({useProjection}) => useProjection('agentPreset') === SPATIALFORGE_PRESET
          ? h('button', {type: 'button', className: 'bfw-evaluation-launcher', 'aria-label': t('openEvaluation'),
            title: t('openEvaluation'), onClick: () => ctx.sidebarRight.openTab(PANEL)}, t('openEvaluation')) : null));
      },
    };
  },
});

