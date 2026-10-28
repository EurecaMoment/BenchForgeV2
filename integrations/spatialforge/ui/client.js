window.__ModuleLoader__.load({
  id: '@eurecamoment/benchforge-spatialforge-ui',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const PANEL = 'benchforge-spatialforge-evaluation';
    const SPATIALFORGE_PRESET = 'spatialforge-standard-ptc';
    const NS = 'benchforgeWorkbench';
    const STAGES = [
      {id: 'S1', key: 'blueprint', artifact: /blueprint|intent|design|plan|literature/},
      {id: 'S2', key: 'collection', artifact: /scene|capture|asset|layout|acquire|collect|reference/},
      {id: 'S3', key: 'structure', artifact: /evidence|state|annotation|normalize|clean|trajectory|structure/},
      {id: 'S4', key: 'synthesis', artifact: /question|item|template|synthesi|dataset|produce/},
      {id: 'S5', key: 'verification', artifact: /quality|evaluat|report|package|screen|diagnos|verif/},
    ];
    const dictionaries = {
      zh: {
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
        workflow: '五步工作流', blueprint: '需求蓝图', collection: '数据采集', structure: '证据与状态结构化', synthesis: '评测题合成', verification: '验证与报告',
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
        workflow: 'Five-step workflow', blueprint: 'Intent blueprinting', collection: 'Data collection', structure: 'Evidence & state structuring', synthesis: 'Benchmark synthesis', verification: 'Verification & reporting',
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
    const styles = [
      '.bfw-root{height:100%;overflow:auto;box-sizing:border-box;padding:28px 32px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font:14px/1.5 system-ui,sans-serif}',
      '.bfw-shell{max-width:1180px;margin:auto;min-width:0}.bfw-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:20px}.bfw-title{font-size:24px;margin:3px 0 8px}.bfw-kicker{font-size:11px;letter-spacing:.08em}.bfw-muted,.bfw-kicker{color:var(--dsw-alias-label-secondary)}',
      '.bfw-toolbar,.bfw-pagination,.bfw-tabs{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.bfw-toolbar{margin:14px 0}.bfw-tabs{border-bottom:1px solid var(--dsw-alias-border-l3);margin-bottom:20px;gap:2px}.bfw-tab{padding:10px 14px;border:0;border-bottom:2px solid transparent;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer}.bfw-tab[aria-selected=true]{color:var(--dsw-alias-label-primary);border-bottom-color:var(--dsw-alias-brand-primary)}',
      '.bfw-button,.bfw-input,.bfw-select{font:inherit;color:inherit;border:1px solid var(--dsw-alias-border-l3);border-radius:7px;padding:7px 10px;background:var(--dsw-alias-button-elevated-fill);max-width:100%;box-sizing:border-box}.bfw-button{cursor:pointer;white-space:nowrap}.bfw-button:hover{background:var(--dsw-alias-button-floating-hover)}.bfw-button:disabled{opacity:.5;cursor:default}.bfw-input{min-width:150px;flex:1}.bfw-button:focus-visible,.bfw-select:focus-visible,.bfw-input:focus-visible,.bfw-tab:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}',
      '.bfw-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:18px 0}.bfw-stat,.bfw-card{border:1px solid var(--dsw-alias-border-l3);border-radius:9px;background:var(--dsw-alias-bg-layer-1)}.bfw-stat{padding:14px}.bfw-stat strong{display:block;font-size:25px;margin-top:8px}.bfw-card{margin:14px 0;min-width:0}.bfw-card h2{font-size:15px;font-weight:600;margin:0;padding:13px 16px;border-bottom:1px solid var(--dsw-alias-border-l3)}.bfw-body{padding:16px}.bfw-scroll{overflow:auto}.bfw-table{width:100%;border-collapse:collapse}.bfw-table td,.bfw-table th{text-align:left;padding:10px 12px;border-bottom:1px solid var(--dsw-alias-border-l3);vertical-align:top}.bfw-table th{font-size:12px;font-weight:500;color:var(--dsw-alias-label-secondary)}.bfw-table tr:last-child td{border-bottom:0}',
      '.bfw-code,.bfw-json{font:12px/1.55 ui-monospace,monospace;overflow-wrap:anywhere;white-space:pre-wrap}.bfw-json{padding:12px;background:var(--dsw-alias-bg-layer-2);border-radius:6px;max-height:380px;overflow:auto}.bfw-pill{display:inline-block;padding:2px 8px;border-radius:12px;font-size:12px;background:var(--dsw-alias-bg-layer-2);white-space:nowrap}.bfw-pill.verified{color:var(--dsw-alias-state-success-primary)}.bfw-pill.failed,.bfw-pill.rejected{color:var(--dsw-alias-state-error-primary)}.bfw-empty{padding:24px 16px;color:var(--dsw-alias-label-secondary)}.bfw-error{padding:12px;border-left:3px solid var(--dsw-alias-state-error-primary);background:var(--dsw-alias-bg-layer-2);white-space:pre-wrap;margin:12px 0}',
      '.bfw-details{display:grid;grid-template-columns:1fr 1fr;gap:16px;min-width:0}.bfw-artifact{padding:14px 0;border-bottom:1px solid var(--dsw-alias-border-l3)}.bfw-artifact:last-child{border:0}.bfw-detail-row{margin:8px 0;overflow-wrap:anywhere}.bfw-artifact summary{cursor:pointer}.bfw-version{display:block;max-width:540px;overflow-wrap:anywhere}.bfw-pagination{justify-content:flex-end;margin-top:16px}.bfw-label{display:grid;gap:5px;font-size:12px;max-width:100%}',
      '.bfw-items{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}.bfw-item{display:flex;flex-direction:column;text-align:left;cursor:pointer;min-width:0;border:1px solid var(--dsw-alias-border-l3);border-radius:8px;background:var(--dsw-alias-bg-layer-1);color:inherit;padding:12px;font:inherit}.bfw-item img{width:100%;height:145px;object-fit:contain;background:var(--dsw-alias-bg-layer-2);margin-bottom:10px}.bfw-item p{white-space:pre-wrap;margin:8px 0;overflow-wrap:anywhere}.bfw-item .bfw-question-preview{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.bfw-observation{display:block;max-width:100%;max-height:560px;object-fit:contain;margin:12px auto}.bfw-question{white-space:pre-wrap;font-size:16px;overflow-wrap:anywhere}.bfw-counts{display:flex;flex-wrap:wrap;gap:16px;margin-top:10px}',
      '.bfw-root[data-spatialforge-panel=true]{padding:12px 10px}.bfw-root[data-spatialforge-panel=true] .bfw-shell{max-width:none}.bfw-root[data-spatialforge-panel=true] .bfw-header{display:block;margin-bottom:12px}.bfw-root[data-spatialforge-panel=true] .bfw-header>.bfw-button{margin-top:8px}.bfw-root[data-spatialforge-panel=true] .bfw-title{font-size:18px}.bfw-root[data-spatialforge-panel=true] .bfw-tabs{flex-wrap:nowrap;overflow:auto;margin-bottom:12px}.bfw-root[data-spatialforge-panel=true] .bfw-tab{padding:8px 9px;white-space:nowrap}.bfw-root[data-spatialforge-panel=true] .bfw-stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:10px 0}.bfw-root[data-spatialforge-panel=true] .bfw-stat{padding:10px}.bfw-root[data-spatialforge-panel=true] .bfw-stat strong{font-size:20px}.bfw-root[data-spatialforge-panel=true] .bfw-details{grid-template-columns:1fr;gap:8px}.bfw-root[data-spatialforge-panel=true] .bfw-card{margin:8px 0}.bfw-root[data-spatialforge-panel=true] .bfw-body{padding:10px}.bfw-root[data-spatialforge-panel=true] .bfw-toolbar>.bfw-label,.bfw-root[data-spatialforge-panel=true] .bfw-toolbar>.bfw-input{width:100%;min-width:0}.bfw-root[data-spatialforge-panel=true] .bfw-table{min-width:500px}.bfw-root[data-spatialforge-panel=true] .bfw-items{grid-template-columns:1fr}.bfw-root[data-spatialforge-panel=true] .bfw-pagination{justify-content:space-between}',
      '.bfw-evaluation-launcher{font:inherit;color:var(--dsw-alias-label-primary);background:var(--dsw-alias-button-elevated-fill);border:1px solid var(--dsw-alias-border-l3);border-radius:7px;padding:6px 10px;cursor:pointer}.bfw-evaluation-launcher:hover{background:var(--dsw-alias-button-floating-hover)}.bfw-evaluation-launcher:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}',
      '@media(max-width:760px){.bfw-root{padding:18px 14px}.bfw-header{display:block}.bfw-header>.bfw-button{margin-top:12px}.bfw-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.bfw-details{grid-template-columns:1fr}.bfw-table{min-width:560px}.bfw-tabs{flex-wrap:nowrap;overflow:auto}.bfw-tab{white-space:nowrap}.bfw-items{grid-template-columns:1fr}.bfw-select{width:100%}.bfw-toolbar>.bfw-label{width:100%}}',
      '.bfw-flow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin:16px 0}.bfw-stage{display:flex;flex-direction:column;align-items:flex-start;gap:7px;text-align:left;color:inherit;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l3);border-radius:10px;padding:12px 10px;cursor:pointer;min-width:0;font:inherit}.bfw-stage[aria-current=step]{border-color:var(--dsw-alias-brand-primary);background:var(--dsw-alias-bg-layer-2)}.bfw-stage-index{font:12px ui-monospace,monospace;color:var(--dsw-alias-label-secondary)}.bfw-stage strong{font-size:13px;font-weight:600;overflow-wrap:anywhere}.bfw-stage-heading{display:flex;gap:12px;align-items:flex-start;margin:18px 0}.bfw-stage-number{font:24px ui-monospace,monospace;color:var(--dsw-alias-brand-primary)}.bfw-stage-heading h2{font-size:20px;margin:0 0 5px}.bfw-stage-heading p{margin:0}.bfw-form{display:grid;grid-template-columns:1fr 1fr;gap:12px}.bfw-form .bfw-wide{grid-column:1/-1}.bfw-textarea{width:100%;min-height:96px;resize:vertical;line-height:1.6}.bfw-callout{padding:14px;border-radius:8px;background:var(--dsw-alias-bg-layer-2);margin:12px 0;overflow-wrap:anywhere}.bfw-callout p{margin:5px 0}.bfw-action{background:var(--dsw-alias-brand-primary);color:var(--dsw-alias-label-onbrand,#fff);border-color:transparent;white-space:normal;text-align:left}.bfw-catalog{display:grid;gap:8px;margin:12px 0}.bfw-template{border:1px solid var(--dsw-alias-border-l3);padding:12px;border-radius:8px;min-width:0}.bfw-template header{display:flex;justify-content:space-between;align-items:center;gap:8px}.bfw-template p{margin:7px 0}.bfw-template[aria-selected=true]{background:var(--dsw-alias-bg-layer-2);border-color:var(--dsw-alias-brand-primary)}.bfw-selected{display:flex;align-items:center;gap:8px;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--dsw-alias-border-l3)}.bfw-stage-footer{display:flex;justify-content:space-between;gap:8px;margin:18px 0}.bfw-notice{padding:10px 12px;background:var(--dsw-alias-bg-layer-2);border-radius:8px;margin:10px 0}.bfw-root[data-spatialforge-panel=true] .bfw-flow{grid-template-columns:repeat(5,minmax(0,1fr));gap:4px}.bfw-root[data-spatialforge-panel=true] .bfw-stage{padding:9px 5px;gap:4px}.bfw-root[data-spatialforge-panel=true] .bfw-stage strong{font-size:12px}.bfw-root[data-spatialforge-panel=true] .bfw-stage-heading h2{font-size:18px}.bfw-root[data-spatialforge-panel=true] .bfw-form{grid-template-columns:1fr}.bfw-root[data-spatialforge-panel=true] .bfw-form .bfw-wide{grid-column:auto}.bfw-root[data-spatialforge-panel=true] .bfw-selected{flex-wrap:wrap}.bfw-root[data-spatialforge-panel=true] .bfw-input{min-width:0;width:100%}.bfw-stage:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}',
    ].join('\n');

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
      const fallback = {tab: 'workflow', stage: 'S1', run: '', dataset: '', template: '', split: '', q: '', page: 1, size: 24, layout: 'grid'};
      const saved = JSON.parse(localStorage.getItem('bfw:spatialforge:' + sessionId) || 'null');
      if (saved && ['workflow', 'overview', 'runs', 'datasets', 'quality'].includes(saved.tab)) {
        return {...fallback, ...saved, size: [24, 48, 96].includes(saved.size) ? saved.size : 24,
          page: Number.isSafeInteger(saved.page) && saved.page > 0 ? saved.page : 1,
          layout: saved.layout === 'table' ? 'table' : 'grid'};
      }
      return fallback;
    }
    function useRecord(params, revision) {
      const key = params ? new URLSearchParams(params).toString() : '';
      const [record, setRecord] = React.useState({key: '', value: null, error: null, loading: false});
      React.useEffect(() => {
        if (!key) return;
        const controller = new AbortController();
        setRecord({key, value: null, error: null, loading: true});
        fetch('api/benchforge/workbench?' + key, {cache: 'no-store', signal: controller.signal})
          .then(async (response) => {
            const value = await response.json();
            if (!response.ok) throw new Error(value.error || 'HTTP ' + response.status);
            if (!controller.signal.aborted) setRecord({key, value, error: null, loading: false});
          }).catch((error) => {
            if (!controller.signal.aborted) setRecord({key, value: null, error: error.message, loading: false});
          });
        return () => controller.abort();
      }, [key, revision]);
      return record.key === key ? record : {value: null, error: null, loading: Boolean(key)};
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
      capability, setCapability, save, prepare, t}) {
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
            h('span', null, allocations(blueprint)[i].target_items + ' ' + t('item')), button(t('removeTemplate'), () => toggle(row)))) : empty(t('noSelection')),
          h('div', {className: 'bfw-toolbar'}, button(t('saveBlueprint'), save), button(t('preparePlan'), prepare, {className: 'bfw-button bfw-action'})),
          blueprint.savedAt && h('p', {className: 'bfw-muted'}, t('savedAt') + ': ' + new Date(blueprint.savedAt).toLocaleString()))),
        card(t('templateCatalog'), h(React.Fragment, null,
          h('p', {className: 'bfw-muted'}, t('catalogDesign')),
          catalog.value && h('div', {className: 'bfw-counts'}, h('span', null, catalog.value.task_count + ' ' + t('task')), h('span', null, catalog.value.template_count + ' ' + t('template'))),
          h('div', {className: 'bfw-toolbar'}, h('input', {className: 'bfw-input', 'aria-label': t('templateCatalog'), value: catalogQuery,
            placeholder: t('search'), onChange: (e) => {setCatalogQuery(e.target.value); setCatalogPage(1);}}),
          select(t('capability'), capability, (id) => {setCapability(id); setCatalogPage(1);}, [['', t('all')], ...(catalog.value?.capabilities || []).map((id) => [id, id])])),
          catalog.error && h('p', {className: 'bfw-error', role: 'alert'}, catalog.error),
          catalog.loading ? empty(t('loading')) : h('div', {className: 'bfw-catalog'}, (catalog.value?.items || []).map((row) =>
            h('article', {className: 'bfw-template', key: row.id, 'aria-selected': selected.has(row.id)},
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

    function Workbench({t, sessionId, useSessions, inputActions}) {
      const [route, setRoute] = React.useState(() => initialState(sessionId));
      const [revision, setRevision] = React.useState(0);
      const [sample, setSample] = React.useState(null);
      const [search, setSearch] = React.useState(route.q);
      const [blueprint, setBlueprint] = React.useState(() => blueprintState(sessionId));
      const [notice, setNotice] = React.useState('');
      const [catalogQuery, setCatalogQuery] = React.useState('');
      const [catalogPage, setCatalogPage] = React.useState(1);
      const [capability, setCapability] = React.useState('');
      const update = (patch) => setRoute((old) => ({...old, ...patch}));
      const workspacePath = useSessions((state) => state.byId[sessionId]?.cwd || '');
      const summary = useRecord(workspacePath ? {view: 'summary', workspace_path: workspacePath} : null, revision);
      const selectedRunId = route.run || summary.value?.runs?.[0]?.id || '';
      const run = useRecord(workspacePath && ['workflow', 'runs'].includes(route.tab) && selectedRunId ? {view: 'run', run: selectedRunId, workspace_path: workspacePath} : null, revision);
      const catalog = useRecord(route.tab === 'workflow' && route.stage === 'S1'
        ? {view: 'catalog', q: catalogQuery, capability, page: catalogPage, page_size: 12} : null, revision);
      const dataset = useRecord(workspacePath && ['datasets', 'quality'].includes(route.tab) && route.dataset ?
        {view: 'dataset', dataset: route.dataset, template: route.template, split: route.split, q: route.q, page: route.page, page_size: route.size, workspace_path: workspacePath} : null, revision);
      React.useEffect(() => { localStorage.setItem('bfw:spatialforge:' + sessionId, JSON.stringify(route)); }, [route, sessionId]);
      React.useEffect(() => { setSample(null); }, [route.dataset, route.page, route.template, route.split, route.q]);
      const rows = summary.value?.runs || [];
      const datasets = summary.value?.datasets || [];
      const selectedDataset = summary.value?.datasets?.find((row) => row.id === route.dataset);
      const stage = STAGES.find((step) => step.id === route.stage) || STAGES[0];
      const activeRun = rows.find((row) => row.id === selectedRunId);
      const stepArtifacts = (run.value?.artifacts || []).filter((row) => stage.artifact.test(row.artifact_type + ' ' + JSON.stringify(row.producer)));
      const saveBlueprint = () => {
        const next = {...blueprint, savedAt: new Date().toISOString()};
        localStorage.setItem('bfw:blueprint:' + sessionId, JSON.stringify(next));
        setBlueprint(next); setNotice(t('blueprintSaved'));
      };
      const stepInstruction = instruction(stage.id, blueprint, activeRun?.label, selectedDataset?.version);
      const prepare = () => {
        if (stage.id === 'S1' && !blueprint.objective.trim()) {setNotice(t('requiredGoal')); return;}
        saveBlueprint();
        if (!inputActions) {setNotice(t('nativeInputMissing')); return;}
        const inserted = inputActions.insertText('\n' + stepInstruction + '\n', inputActions.captureInsertion());
        setNotice(t(inserted ? 'draftReady' : 'draftBusy'));
      };
      const openRun = (id) => update({tab: 'runs', run: id});
      const openDataset = (id) => { update({tab: 'datasets', dataset: id, template: '', split: '', q: '', page: 1}); setSearch(''); };
      const runTable = (items) => items.length ? table([t('workspace'), t('runs'), t('state'), t('steps'), t('artifacts'), t('updated')],
        items.map((item) => [item.workspace, button(item.label, () => openRun(item.id)), status(item.state, t), item.steps, item.artifact_total ?? '—', item.updated_at])) : empty(t('noRuns'));
      const versionOptions = [['', t('chooseDataset')], ...(summary.value?.datasets || []).map((row) => [row.id, row.workspace + ' / ' + row.version])];
      let body;
      if (route.tab === 'workflow') {
        body = h(React.Fragment, null,
          h('div', {className: 'bfw-stage-heading'}, h('span', {className: 'bfw-stage-number'}, stage.id),
            h('div', null, h('h2', null, t(stage.key)), h('p', {className: 'bfw-muted'}, t(stage.key + 'Desc')))),
          stage.id === 'S1' ? h(Blueprint, {blueprint, setBlueprint, catalog, catalogQuery, setCatalogQuery, catalogPage, setCatalogPage,
            capability, setCapability, save: saveBlueprint, prepare, t}) : h(React.Fragment, null,
            h('div', {className: 'bfw-callout'}, h('strong', null, t('stepOutput') + ' · ' + t(stage.key + 'Output')),
              h('p', null, t(stage.id === 'S2' ? 'sceneFirstNote' : stage.id === 'S5' ? 'qualityPolicy' : 'evidencePolicy'))),
            h('div', {className: 'bfw-toolbar'}, button(t('prepareStage'), prepare, {className: 'bfw-button bfw-action'}),
              button(t('copyInstruction'), async () => {try {await navigator.clipboard.writeText(stepInstruction); setNotice(t('copied'));} catch (error) {setNotice(error.message);}})),
            h('p', {className: 'bfw-muted'}, t('chatNote')),
            select(t('chooseProduction'), selectedRunId, (id) => update({run: id}), [['', t('chooseRun')], ...rows.map((row) => [row.id, row.label])]),
            card(t('stageEvidence'), h(React.Fragment, null,
              run.loading ? empty(t('loading')) : stepArtifacts.length ? stepArtifacts.map((artifact) => h('details', {className: 'bfw-artifact', key: artifact.artifact_id},
                h('summary', null, status(artifact.status, t), ' ', artifact.artifact_type),
                h('p', {className: 'bfw-code'}, artifact.artifact_id), h('p', null, t('producer') + ': ' + JSON.stringify(artifact.producer)),
                json({parents: artifact.parents, evidence_refs: artifact.evidence_refs, contract_results: artifact.contract_results}))) : empty(t('noStepArtifacts')),
              activeRun && button(t('openRun'), () => openRun(selectedRunId)))),
            ['S4', 'S5'].includes(stage.id) && card(t('directory'), datasets.length ? h(React.Fragment, null,
              select(t('chooseDataset'), route.dataset, (id) => update({dataset: id}), versionOptions),
              h('div', {className: 'bfw-toolbar'}, button(t('openData'), () => route.dataset ? openDataset(route.dataset) : update({tab: 'datasets'})),
                button(t('openQuality'), () => update({tab: 'quality'}))),
              stage.id === 'S5' && selectedDataset && h(Quality, {report: selectedDataset.report, t})) : empty(t('noDatasets')))),
          h('div', {className: 'bfw-stage-footer'}, button(t('previousStep'), () => update({stage: STAGES[STAGES.indexOf(stage) - 1].id}), {disabled: stage.id === 'S1'}),
            button(t('nextStep'), () => update({stage: STAGES[STAGES.indexOf(stage) + 1].id}), {disabled: stage.id === 'S5'})));
      } else if (route.tab === 'overview') {
        body = workspacePath ? h(React.Fragment, null,
          h('div', {className: 'bfw-counts'}, h('span', null, t('runCount') + ': ' + (summary.value?.runs.length ?? '—')),
            h('span', null, t('datasetCount') + ': ' + (summary.value?.datasets.length ?? '—'))),
          h('div', {className: 'bfw-stats'}, ['draft', 'candidate', 'verified', 'rejected', 'superseded'].map((key) =>
            h('div', {className: 'bfw-stat', key}, t(key), h('strong', null, summary.value?.counts?.[key] ?? '—')))),
          card(t('recent'), runTable(rows.slice(0, 8))),
          card(t('sources'), table([t('workspace'), t('state'), t('details')], (summary.value?.sources || []).map((source) =>
            [source.workspace, t(source.status), source.error || (source.truncated ? t('truncated') : source.limit ? source.limit + ' ' + t('limit') : '—')])))) : empty(t('noWorkspace'));
      } else if (route.tab === 'runs') {
        body = h(React.Fragment, null,
          card(t('runs'), runTable(rows)),
          run.loading ? empty(t('loading')) : h(RunDetails, {record: run.value, t}));
      } else if (route.tab === 'quality') {
        body = h(React.Fragment, null,
          select(t('chooseDataset'), route.dataset, (id) => update({dataset: id, page: 1}), versionOptions),
          card(t('report'), dataset.loading ? empty(t('loading')) : h(Quality, {report: dataset.value?.report || selectedDataset?.report, t})));
      } else {
        const data = dataset.value;
        body = h(React.Fragment, null,
          card(t('directory'), h(React.Fragment, null,
            h('p', {className: 'bfw-muted'}, t('datasetNote')),
            datasets.length ? table([t('workspace'), t('version'), t('generationAccepted'), t('state'), t('open')], datasets.map((row) =>
              [row.workspace, h('span', {className: 'bfw-code bfw-version'}, row.version), row.report?.accepted ?? '—', status(row.state, t), button(t('browse'), () => openDataset(row.id))])) : empty(t('noDatasets')))),
          route.dataset && card(t('datasets'), h(React.Fragment, null,
            select(t('chooseDataset'), route.dataset, openDataset, versionOptions),
            h('p', {className: 'bfw-muted'}, t('publicNote')),
            h('form', {className: 'bfw-toolbar', onSubmit: (e) => { e.preventDefault(); update({q: search, page: 1}); }},
              select(t('template'), route.template, (id) => update({template: id, page: 1}), [['', t('all')], ...(data?.facets.templates || []).map((id) => [id, id])]),
              select(t('split'), route.split, (id) => update({split: id, page: 1}), [['', t('all')], ...(data?.facets.splits || []).map((id) => [id, id])]),
              h('input', {className: 'bfw-input', 'aria-label': t('search'), placeholder: t('search'), value: search, onChange: (e) => setSearch(e.target.value)}),
              h('button', {className: 'bfw-button', type: 'submit'}, t('apply'))),
            h('div', {className: 'bfw-toolbar'},
              select(t('pageSize'), String(route.size), (size) => update({size: Number(size), page: 1}), [24, 48, 96].map((size) => [String(size), String(size)])),
              button(t('grid'), () => update({layout: 'grid'}), {'aria-pressed': route.layout === 'grid'}),
              button(t('table'), () => update({layout: 'table'}), {'aria-pressed': route.layout === 'table'}),
              h('span', {className: 'bfw-muted'}, t('matches') + ': ' + (data?.total ?? '—') + ' / ' + t('total') + ': ' + (data?.all ?? '—'))),
            dataset.loading ? empty(t('loading')) : sample ? h(React.Fragment, null,
              button(t('close'), () => setSample(null)), h('p', {className: 'bfw-code'}, sample.item_id || sample.id),
              h('p', {className: 'bfw-question'}, sample.question),
              h('h3', null, t('media')), sample.media?.length ? sample.media.map((src, i) => h('img', {className: 'bfw-observation', key: src, src, alt: t('media') + ' ' + (i + 1)})) : empty(t('noMedia')),
              h('details', null, h('summary', null, t('details')), json({...sample, media: undefined}))) :
              !data?.items.length ? empty(t('noItems')) : route.layout === 'table' ?
                table([t('item'), t('template'), t('split'), t('question'), t('open')], data.items.map((item) =>
                  [item.item_id || item.id, item.template_id || '—', item.split || '—', item.question, button(t('open'), () => setSample(item))])) :
                h('div', {className: 'bfw-items'}, data.items.map((item) => h('button', {type: 'button', className: 'bfw-item', key: item.row_index, onClick: () => setSample(item)},
                  item.media?.[0] && h('img', {src: item.media[0], loading: 'lazy', alt: t('media')}),
                  h('span', {className: 'bfw-code'}, item.item_id || item.id), h('p', {className: 'bfw-question-preview'}, item.question),
                  h('span', {className: 'bfw-muted'}, (item.template_id || '') + ' · ' + (item.split || ''))))),
            h('div', {className: 'bfw-pagination'},
              button(t('previous'), () => update({page: route.page - 1}), {disabled: route.page <= 1 || dataset.loading}),
              h('span', null, t('page') + ' ' + route.page + ' / ' + (data?.pages || 1)),
              button(t('nextPage'), () => update({page: route.page + 1}), {disabled: !data || route.page >= data.pages || dataset.loading})))));
      }
      return h('div', {className: 'bfw-root', 'data-benchforge-workbench': 'true', 'data-spatialforge-panel': 'true'}, h('style', null, styles), h('div', {className: 'bfw-shell'},
        h('header', {className: 'bfw-header'}, h('div', null,
          h('div', {className: 'bfw-kicker'}, 'BENCHFORGEV2 / SPATIALFORGE'), h('h1', {className: 'bfw-title'}, t('panel')),
          h('div', {className: 'bfw-muted'}, t('subtitle'))), button(t('refresh'), () => setRevision((value) => value + 1), {disabled: summary.loading})),
        h('nav', {className: 'bfw-flow', 'aria-label': t('navigation')}, STAGES.map((step) => h('button', {
          className: 'bfw-stage', type: 'button', key: step.id, 'data-stage': step.id,
          'aria-current': route.tab === 'workflow' && stage.id === step.id ? 'step' : undefined,
          onClick: () => {update({tab: 'workflow', stage: step.id}); setNotice('');}},
          h('span', {className: 'bfw-stage-index'}, step.id + ' / 05'), h('strong', null, t(step.key))))),
        h('nav', {className: 'bfw-tabs', role: 'tablist', 'aria-label': t('panel')}, ['workflow', 'overview', 'runs', 'datasets', 'quality'].map((key) =>
          h('button', {type: 'button', key, className: 'bfw-tab', role: 'tab', 'aria-selected': route.tab === key, onClick: () => update({tab: key})}, t(key)))),
        h('p', {className: 'bfw-muted'}, route.tab === 'workflow' ? t('workflowNote') : t('scope')),
        notice && h('div', {className: 'bfw-notice', role: 'status'}, notice),
        summary.value && h('div', {className: 'bfw-kicker'}, t('snapshot') + ': ' + summary.value.snapshot_at),
        [summary.error, run.error, dataset.error].filter(Boolean).map((error, i) => h('div', {className: 'bfw-error', role: 'alert', key: i}, error)),
        summary.loading && route.tab !== 'workflow' && empty(t('loading')), body));
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
        }, ({useProjection, useSessions, sessionId, inputActions}) => useProjection('agentPreset') === SPATIALFORGE_PRESET
          ? h(Workbench, {key: sessionId, t, sessionId, useSessions, inputActions}) : null));
        ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register({
          name: 'conversation.session.header.utilities', id: 'spatialforge-evaluation-launcher', order: 80, locale: NS,
        }, ({useProjection}) => useProjection('agentPreset') === SPATIALFORGE_PRESET
          ? h('button', {type: 'button', className: 'bfw-evaluation-launcher', 'aria-label': t('openEvaluation'),
            title: t('openEvaluation'), onClick: () => ctx.sidebarRight.openTab(PANEL)}, t('openEvaluation')) : null));
      },
    };
  },
});

