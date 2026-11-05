# SpatialForge composable pipelines and exact task templates

The consolidated operator UI for these pipelines is documented in
[frontend-workbench-v2.md](frontend-workbench-v2.md). It maps plans, runs,
typed artifacts, contracts, repair proposals, dataset browsing and releases
without treating chat output as production state.

The production directory is `src/benchforge_core/pipelines/definitions/`. JSON files are editable recipes with IDs, input/output descriptions, registered operations and artifact references. `task_templates.json` imports the user-provided 出题模板.html: 89 tasks, 267 measurement templates and their common/individual protocols. N IDs are capability associations, C/P IDs identify tasks, and Cxx-Tyy identifies an exact measurement variant. Original design and legacy validation fields remain separate from adapter execution status.

## DSH entrypoints

- `benchforge_pipeline_catalog`: pipelines, capabilities, tasks, templates or common protocol. Supports Chinese search, exact IDs and capability selection. Read a template's conditions before executing it.
- `benchforge_pipeline_plan`: interpret a user goal and provide `selections=[{template_ids,count,reason}]`, or select an explicit capability/task/template. Plain text without IDs returns candidates for the host DSH semantic agent to select. Lexical retrieval is not an automatic capability verdict.
- `benchforge_pipeline_run`: execute or resume the saved plan. Supply `run` to resume. Returns `waiting`, `needs_input`, `needs_evidence`, `failed` or `completed` and artifact paths.
- `benchforge_pipeline_status`: read current step states without executing.
- `benchforge_pipeline_artifacts`: read the run's typed artifact manifest, parent references, evidence paths and shape-contract results without executing or retrying.
- `benchforge_pipeline_repair_plan`: create a reviewable repair proposal for a failed artifact. It chooses local field repair, template rebinding, candidate resynthesis, skill re-execution, upstream rollback or final rejection; it never edits GT or runs the repair.
- `benchforge_pipeline_evaluate`: evaluate saved answers with deterministic protocol scorers. No target model API calls.

Existing legacy `spatial_generate` remains for previous experiments; it does not generate these new document templates. Capability-data requests use the new catalog and pipeline tools. The SpatialForge development preset exposes these seven pipeline tools alongside existing learning and scene tools.

## Artifact lineage and bounded repair

Every persisted pipeline step writes `pipeline_run/artifacts.jsonl`. A record contains
`artifact_id`, `artifact_type`, `version`, `parents`, `producer`, declared evidence
references, contract results, status and the result path. The runner derives parent
references from explicit `$step_id` bindings and keeps old records when a waiting or
failed step is retried. The default status for a completed step is `candidate`; it is
not a benchmark approval. Operation-specific gates must explicitly promote a record
to `verified` later.

Execution failures and missing bindings also write `pipeline_run/repair-plans.jsonl`.
The proposal is deliberately separate from execution: inspect it, correct the task
input or evidence in a new run, then rerun the same contracts. No repair operation
changes an answer, GT, acceptance rule or remote service automatically. The manifest
is a small versioned JSONL record and does not perform content hashing or broad scans.

## One capability or several templates

One capability:

```json
{"objective":"生产距离感知训练数据","capability":"N01","target_items":120,"split":"train","seed":5013}
```

Explicit semantic decomposition:

```json
{"objective":"三维距离、二维区域面积和动力学公式训练数据","selections":[{"template_ids":["C01-T01","C01-T02","C01-T03"],"count":30,"reason":"分别测中心距离、表面距离和点距离"},{"template_ids":["P001-T01","P001-T02","P001-T03"],"count":30,"reason":"填充面积含凹形和孔洞"},{"template_ids":["C43-T01","C44-T01"],"count":20,"reason":"匀速时间与静止释放落体时间"}],"split":"train","seed":6013}
```

`count` belongs to each selection and divides across its selected variants. Counts are recorded per template. If some variants need source evidence, production writes `production_spec.json` with exact protocols, missing counts, evidence schema and next action. DSH should produce that evidence and resume; it must not deliver the gap as a completed dataset or replace it with unrelated legacy questions.

## Recipe composition

`steps` may call another registered recipe with `uses="pipeline"` and `pipeline_id`. Primitive artifact references use `$inputs.name` or `$step_id.output` and support list indices. Example:

```json
{"objective":"复用已有场景采集并按指定协议出题","inputs":{"scene_program_path":"/workspace/scene.json","service_config":"/home/maqiang/GitHub/SpatialForge/service.local.json"},"steps":[{"id":"capture","uses":"pipeline","pipeline_id":"scene.capture","arguments":{"scene_program_path":"$inputs.scene_program_path","service_config":"$inputs.service_config"}},{"id":"observations","uses":"spatialforge.evidence","arguments":{"task_id":"$capture.outputs.capture_ready.tasks.0.id","file":"capture/evidence.json","workspace_id":"capability-data"}},{"id":"adapter","uses":"spatialforge.task_code","arguments":{"workspace_id":"capability-data","code":"# Write a task-specific oracle and evidence JSONL here. Use copied observations and exact protocol conditions."}},{"id":"questions","uses":"templates.produce","arguments":{"selections":[{"template_ids":["C63-T01"],"count":20,"reason":"指定视点可见性"}],"evidence":"$inputs.evidence","seed":6013,"split":"train"}},{"id":"release","uses":"data.package","arguments":{"dataset":"$questions.dataset"}}]}
```

This is a composition skeleton. The task-specific adapter must supply actual oracle logic and input evidence; the comment alone is not executable production. `scene.capture` submits to the existing API and single desktop Isaac queue; repeated resume polls reuse the original submission. No second simulator is launched. Recipe requests use persistent request keys; completed step inputs are frozen, while missing downstream bindings can be supplied on resume.

## Supported production modes

1. Built-in program generators currently cover 17 exact variants: C01-T01..03, C04-T01..03, C43-T01/T03, C44-T01..03, P001-T01..03 and P002-T01..03. They create explicit-rule problems, calibrated orthographic views, polygon/hole observations or detection images with deterministic answers. These are controlled program worlds, not real-world or Isaac acceptance.
2. All 267 templates can bind official/program/simulation records. DSH writes task code or uses an existing source/collector to produce the required observation, oracle result and admission record. Records specify all prompt parameters, public media, provided information, exact template/protocol IDs, JSON source pointers, frame/units and scene-group identity.
3. Interactive templates require executed episodes and frozen interface/budget/terminal conditions. History templates require a history access mode. Static answers cannot replace an episode. New generic pipeline scoring covers numeric outputs, ordering, 2D boxes and detection sets; path/interactive tasks continue to need their task-specific constraint/episode scorers and are not silently exact-matched.

Example evidence JSONL record:

```json
{"template_id":"C63-T01","parameters":{"...":"all exact template parameters"},"media":["view.png"],"provided_information":["public camera convention"],"provenance":{"kind":"simulation","path":"oracle_source.json"},"answer_selector":"/oracle/answer","admission_selector":"/admission","oracle_version":"visibility-oracle-v1","reference_frame":"world Z-up, metre","scene_group_id":"scene-family-17","split":"train"}
```

The referenced admission object binds `template_id`, `protocol_id` and actual information-sufficient/oracle-executed/media-consistent/no-answer-leakage checks. This is source-backed admission, not a new claim of independently verified measurement validity. Preserve the generator and source evidence so it is reviewable.

## Outputs and reproducibility

- `questions.jsonl`: public question/media/measurement conditions and capability associations, no answer or private scene.
- `authority.jsonl` and `authority/sources`: answers, oracle provenance, source selectors, scoring and admission.
- `sft.jsonl`: supervised answers only for train.
- `protocols.json`, `quality_report.json`, `production_spec.json` on shortfall.
- Public, authority and optional training ZIPs are separate. Only referenced observation media enters the public ZIP.
- Workspace `pipeline-groups.sqlite` fixes source-world groups to a partition across separate runs. Variants of the same task/seed world stay together. Independent workspaces still require a shared source split manifest; seed alone does not establish real-scene independence.
- `pipeline_run/state.json` and per-step request/result files record resume state. Process cancellation uses the existing managed DSH subprocess mechanism; remote scene jobs retain their existing service ownership.

Local check: `python -m unittest discover -s tests -p test_pipelines.py -v`. Complete core checks and real official DSH native/PTC calls are used before deployment. This feature does not assert full 267-template generator deployment, successful Qwen training or benchmark approval.
