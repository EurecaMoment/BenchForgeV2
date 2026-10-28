# BenchForge five-step evaluation workbench

Open a **SpatialForge** conversation in DSH and select **评测集** in its header.
The conversation remains available beside the workbench. Other agent presets
do not display the launcher or panel.

| Step | Page functions | Recorded outputs |
| --- | --- | --- |
| S1 · 需求蓝图 / Intent blueprinting | Goal, item quantity, storage limit, source, capability search, template selection and quantity allocation | Session-local blueprint draft; production plan after it is submitted in chat |
| S2 · 数据采集 / Data collection | Scene-first collection instructions and selection of an existing production run | Scene, reference, asset and capture artifacts |
| S3 · 证据与状态结构化 / Evidence & state structuring | Evidence/state instructions; inspect artifact parents, evidence references and contract results | Evidence, calibration, annotation and trajectory artifacts |
| S4 · 评测题合成 / Benchmark synthesis | Template-based synthesis instructions; dataset version selection and full dataset browser | Public questions, media, splits and dataset versions |
| S5 · 验证与报告 / Verification & reporting | Verification/report/package instructions; quality results and saved repair proposals | Quality, evaluation, report and package artifacts |

The five steps organize work; they do not introduce a compulsory scheduler.
Navigation is independent of completion. Artifact type/producer labels determine
which recorded artifacts appear in a step; absence of a matching record is not
proof that the step was never executed.

“填入对话” inserts the selected step and blueprint into the current session's
native DSH composer using `inputActions.captureInsertion/insertText`. It does not
submit a model request. The user reviews and sends it through the normal DSH
conversation. Existing tools execute the operation and retain its artifacts.
This keeps failures and follow-up changes in the same conversation.

“保存蓝图草稿” saves in this browser, keyed by session. It is not a server-side
pipeline plan. Once sent, DSH must persist its actual plan/run in the workspace.

The template picker reads `task_templates.json` through the authenticated
`GET /api/benchforge/workbench?view=catalog` endpoint. It supports capability and
text filtering and 12-item pagination. Catalog designs and executable adapters
remain separate; selecting a template does not assert that it has a working
generator. The endpoint exposes no oracle fields.

Existing overview, run/artifact, dataset and quality tabs remain available.
Dataset versions are isolated, samples are paginated and filterable, and sample
details expose public observations only. Missing verification stays unknown;
generation acceptance does not become benchmark approval. Model response data
is required before IRT diagnostics can be reported.

All implementation is in `integrations/spatialforge/ui`; official DSH source,
model deployments, weights and simulator configuration are external. When
updating an existing deployment, preserve its root-level plugin placement and
SpatialForge client gate. Do not use a query string in a local plugin file path.

Validation:

```sh
node --test integrations/spatialforge/tests/test_workbench.mjs
```

Browser acceptance additionally checks all five steps, template selection,
blueprint persistence and native draft insertion without submitting inference.


Live production
---------------

The production panel reads `view=progress` automatically, scheduling its next
request three seconds after the previous request completes. It shows the last
observation time, pipeline completed/total steps and unfinished step, actual
SpatialForge lifecycle/phase, desktop-device queue reason, failures, capture
and action-trace counts, reported transfer bytes and release counts/status.
The five navigation steps display observed execution states independently of
which step the user is viewing. Execution success never implies benchmark approval.

The lightweight progress route reads at most `maxRuns` workspace operation
rows plus their small persisted plans/state files. It does not scan datasets or
artifact manifests every three seconds. Full summaries and selected dataset
pages refresh every 30 seconds; selected run artifacts every 10 seconds. Requests
do not overlap within a feed. Hidden panels and background documents pause
scheduled polling and resume when visible. Navigation, selected version, filters,
page and public detail remain in place. Read failures retain the last successful
snapshot and visibly mark the observation as stale until recovery.

Direct `spatialforge_run/capture/asset/...` submissions are also observed:
`production_observer.py` queries existing PostgreSQL request keys matching the
current `dsh:<session_id>:` prefix, then calls the existing read-only `/observe`
API. Explicit `sf_` run IDs in persisted pipeline results are also included.
The most recent 12 jobs are bounded, with active jobs prioritized; this is not
a global production count. The observer constructs no Store/Repository, creates
no schema, starts no jobs and exposes no task result/answer payload. Its local
service configuration and credentials stay on the server.

Configure the UI plugin with `productionConfig` pointing to the existing
SpatialForge server config (containing harness DB config path and operator token)
and `productionPython` pointing to the existing Python with SQLAlchemy. Without
this configuration the UI explicitly reports that only workspace pipelines are
observed. Custom request keys without the DSH session prefix are discoverable
only through persisted pipeline references. Ad-hoc shell jobs without either
record are not claimed as tracked. A worker that does not report intermediate
progress remains at its last reported phase; no synthetic percentage is shown.

For an already cached UI backend, `ui/production.js` is a distinct backend entry;
`ui/index.js` remains the public package export. Use official plugin management
to disable and enable **only** the existing root workbench plugin when replacing
its module. Changing its entry/config alone may leave the previous handler active.
Do not restart DSH while a session is running. Preserve the root placement,
SpatialForge preset gate, model services, simulator services and other plugins.
