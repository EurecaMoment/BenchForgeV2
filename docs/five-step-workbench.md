# BenchForge five-step evaluation workbench

Open a **SpatialForge** conversation in DSH. The workbench replaces that preset's
main conversation view through `main.conversation`; the original chat and composer
are hidden. There is no separate sidebar launcher to find. Other agent presets
keep their ordinary conversation interface.

Wait for **完全权限已开启**, enter a natural-language request in the persistent
**数据集生产需求** form, set **目标题量**, and select **开始生产**. The initial target
is 100 items; it is a request, not a claim of existing or accepted output.
**能力或模板要求（可选）** may be left blank for DSH to decompose against its existing
capability graph and templates. The advanced target scene count and storage budget
are optional. A single submission asks the current DSH agent to execute all five
stages using its integrated tools, rather than stopping at a written plan.

Opening a SpatialForge session applies the official session command
`/permission danger-full-access`; this is not sent to the model. Production submission
is disabled until the permissions projection confirms it. Setup failures offer a
retry action and remain visible. This document describes the implementation;
target-deployment and browser acceptance must be recorded separately.

| Step | Page functions | Recorded outputs |
| --- | --- | --- |
| S1 · 评测计划 | Persisted production plan and collapsible read-only template reference | Actual plan produced in this conversation |
| S2 · 场景预览 | Scene gallery and full-size image/video preview | Actual scene, reference, asset and capture artifacts |
| S3 · 标注预览 | Public annotation preview; declared matching image with recorded boxes when available | Evidence, calibration, annotations and trajectories |
| S4 · 评测配置与题目表 | Actual configuration and explicitly selected dataset's searchable, paginated questions | Public questions, media, splits and dataset versions |
| S5 · 最终报告 | Saved report and selected dataset quality results | Quality, evaluation, report and package artifacts |

The five steps organize work; they do not introduce a compulsory scheduler.
Navigation is independent of completion. Artifact type/producer labels determine
which recorded artifacts appear in a step; absence of a matching record is not
proof that the step was never executed.

Products are previews, not forms or material to send back into chat. The persistent
demand form provides **追加要求** for the current production task; an active session
queues the request rather than creating a hidden second task. **新建生产任务** changes
the form mode within this conversation, not the DSH session. Each stage also retains
**提出修改要求**, opening an independent blank textarea. **确认发送** submits that
written requirement with official `captureInsertion/insertText/submit` actions;
no second composer Send click is needed and no artifact bundle is attached.

If the hidden original composer contains text or attachments, their contents are
shown for review. Submission requires explicitly checking whether to include them;
otherwise they remain unchanged and are not sent. This rule applies to both the
persistent demand form and the stage-request dialog. Cancel leaves them unchanged.
A busy input or slash command prevents submission. A synchronous submission error
retains the request for retry without inserting it a second time. Submission is
not production completion: the native conversation owns queueing, execution and
failure receipts.

**最新执行反馈** shows the most recent assistant text without restoring the original
chat interface. **停止当前执行** cancels the current assistant turn; it does not claim
to cancel all submitted background jobs or queued requests. Those retain their own
status and receipts. Five-stage navigation and Previous/Next only change the view.

The workbench displays only current-conversation records. Every artifact request
carries `session_id` as well as `workspace_path`. The BenchForge tool adapter
passes the actual DSH session/call IDs to Runtime; `request.json` stores them in
`context`, and pipeline state retains its associated `context.session_ids`.
Missing historical associations are excluded rather than guessed. An explicitly
requested `scope=workspace` supports history access; the live panel never uses it.
Old browser state without route version 3 no longer selects a workspace run.

The visible current-conversation status subscribes directly to native `useSession`
and `useInput` state: idle, submitting, running, load/prompt/agent error, and queue
length. It does not infer chat activity from an old pipeline's completion state.
An empty new chat has no plan, scene, annotation, dataset or report until it produces
one. Switching to another conversation remounts the session-bound panel.

The template picker reads `task_templates.json` through the authenticated
`GET /api/benchforge/workbench?view=catalog` endpoint. It supports capability and
text filtering and 12-item pagination. Catalog designs and executable adapters
remain separate; viewing a template does not assert that it has a working
generator. The endpoint exposes no oracle fields.

The five stages are the only page navigation. Previous overview, run/artifact,
dataset and quality tabs are merged into their stage: S1 has searchable and
paginated past plans/runs; current-run provenance and repair details expand
within the active stage; S4 includes the dataset-version directory plus the full
filtered/paginated table or grid and public sample detail; S5 contains quality
results and the final report. Snapshot/source metadata stays inside production details instead of
adding a second header between the five stages and their content.
Dataset versions are isolated, and sample details expose public observations only.
Missing verification stays unknown;
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

Browser acceptance checks all five key products, stage progress, previews,
the production demand form, permission gating, target-versus-output semantics,
stage requests, explicit draft/attachment inclusion, confirmation and exactly one
native submission using controlled input actions. It must also check preset
isolation, main-view replacement, latest assistant feedback and current-turn
cancellation. Controlled fixtures never submit live inference and are not real
production acceptance; earlier sidebar acceptance does not validate this layout.


Live production
---------------

The production panel reads `view=progress` automatically, scheduling its next
request three seconds after the previous request completes. It shows the last
observation time, pipeline completed/total steps and unfinished step, actual
SpatialForge lifecycle/phase, desktop-device queue reason, failures, capture
and action-trace counts, reported transfer bytes and release counts/status.
The five navigation steps display observed execution states independently of
which step the user is viewing. Execution success never implies benchmark approval.
Each page also shows its own recorded stage steps and progress. Missing totals
remain unmeasured; a saved final report is required to show report contents.

`view=stage_artifacts` lists bounded files for a scene belonging to this session,
or for a scene explicitly referenced by the selected workspace pipeline's saved
state. `view=stage_media` streams authenticated same-origin previews, supports
video byte ranges and projects only public annotation data. Model/operator
credentials stay server-side. Missing output directories do not discard an
already saved plan; authentication or network failures remain visible.

The lightweight progress route reads at most `maxRuns` workspace operation
rows plus their small persisted plans/state files. It does not scan datasets or
artifact manifests every three seconds. Full summaries and selected dataset
pages refresh every 30 seconds; selected run artifacts every 10 seconds. A native
conversation-status change or changed pipeline receipt refreshes products promptly.
Requests
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

For the five-product UI backend, `ui/stage_products.js` is the implementation and
live entry; `ui/production.js` and `ui/index.js` remain compatibility exports.
The distinct entry also avoids an already cached legacy production module.
Official server HMR must watch the owned integration directories to invalidate
ESM modules. For example, `hmr` can set `base` to the BenchForgeV2 checkout and
`root` to `['integrations/spatialforge/ui', 'integrations/dsh']`. Plain plugin
disable/enable does not clear Node's ESM module cache. Preserve any existing roots.
Do not duplicate the backend into versioned implementation files to bypass it.
Do not restart DSH while a session is running. Preserve the root placement,
SpatialForge preset gate, model services, simulator services and other plugins.

Usability behavior
------------------

The live monitor defaults to a compact summary with expandable details. Run and
dataset-version directories have search and 12/24/48-row pagination. Five-step
navigation responds to its actual main-view container width. Stage buttons
support native keyboard activation.

Changing a dataset version clears that version's template, split and query
filters across workflow, quality and dataset views. Public sample details read
from the current successful dataset response, so refresh updates changed items
and returns to the list when the selected item disappears. Opening a sample
focuses its heading; returning restores focus to its original list button.
If a dataset shrinks, an out-of-range page is corrected and reloaded. Empty
search results offer clear filters. Read errors offer retry and do not imply
that records or quality reports are absent.
