# BenchForge integration

`plugin/tools.mjs` contains the production tool definitions and the delivery
review hooks, using public DSH package imports, service URL and token environment
variable. `../dsh/preset_definition.py`
shares production capabilities between **BenchForge** (standard conversation)
and **BenchForge_UI** (visual workbench). Previously saved conversations can
open in their corresponding preset and workbench. `../dsh/build_presets.py` generates
both presets together. The installable
Node bundle and supported package/Node versions are documented in
[the integration guide](../README.md).

Operator commands for repairing the scene library, removing proxy scenes and
rewriting question sets live in [`maintenance/`](maintenance/). Worker deployment
and the external dispatcher bundle live in [the backend deployment directory](../../components/benchforge/deploy/dispatcher/).

## Current FIT service connection

The active FIT route for scene work is:

```text
DSH on FIT
  → FIT BenchForge service and queue
  → external a800-remote-fit dispatcher
  → FIT 127.0.0.1:18766 reverse-SSH endpoint
  → thunlp-node1, Isaac Sim 6.2.0 on A800
  → capture and evidence returned to FIT
```

`desktop-isaac` is the retained database lease name; the current worker identity
is `a800-remote-fit`. The FIT loopback address is a tunnel endpoint, not a local
Isaac process. The dispatcher and A800 Isaac installation are external to this
repository and are not started or migrated by this plugin. A real DSH task has
verified the route, but that receipt is not a current health or throughput claim.

The Windows single-instance worker remains a supported self-hosted alternative.
This client never starts a second worker, simulator, tunnel or model service;
do not configure both workers to claim the same queue without an explicit server
capacity policy.

Use `config/benchforge.local.json` to configure the service. To connect to an
existing service, set `client.service_config` to its server JSON or use the
client's `service_url` and `operator_token_env`. Generate the client settings,
verify the connection and start the Web profile:

```bash
python benchforge_app.py sync
python integrations/benchforge/cli.py status --config config/generated/benchforge-client.local.json
python integrations/benchforge/cli.py status --config config/generated/benchforge-client.local.json --run-id sf_YOUR_RUN
python benchforge.py setup
python benchforge.py start
```

Without a run ID, status calls authenticated `POST /catalog`; with an ID it calls
`POST /observe`. BenchForge has no run-status `GET /status` endpoint.
Missing config or credentials fails with an actionable error.

## Multi-agent collaboration

The combined preset exposes `benchforge_collaboration` and the BenchForge plugin exposes `benchforge_scene_collaboration` for lightweight, shared-workspace handoffs. Agents can publish a role, status, inputs, findings, artifact paths, blockers, decisions and next actions, relate or reply to earlier handoffs, then list or read the record when another agent resumes the task. This is an artifact protocol rather than a fixed orchestration graph: agents can work sequentially or in parallel, and the parent agent decides how to merge their findings.

Useful roles include planning, asset/layout construction, visual review, interaction/physics review, dataset/export review and delivery editing. Handoffs can reply to or relate earlier work and can carry a decision and confidence when a parent agent needs to reconcile parallel findings. Keep them short and concrete. Independent work may run in parallel; the single configured Isaac queue remains the shared execution boundary.

Publish a complete new snapshot with the same `handoff_id` to update it. `list` returns one current record per handoff and filters that current state by status, role or agent; a resolved blocker will not reappear from an earlier version. `read` returns the same latest snapshot. Use `list` with `history: true` for earlier versions, including old blockers and agent assignments. The append-only file keeps all versions for inspection.

A receiving agent can use `benchforge_scene_status` or `benchforge_wait` with a shared capture's `run_id`. When its session has no capture submission, this explicit observation lets the existing delivery review load that completed capture and its images. The submitting agent's conversation is not required. Repeated observations do not repeat the review; unrelated turns do not reopen the task. Generation and dataset operations keep their own behavior. A received handoff or review message does not establish that the user's requirements are complete.

## Saved workbench scene movies

The workbench exports an H.264 MP4 from each completed scene's declared public
capture views. Export runs in the background when production is observed, with
one encoder at a time. Movies are saved under `.deployment/scene-previews/` by
task and revision and reused when a user opens, closes, or reloads the player.
Playback serves an existing file with byte ranges; it never records a canvas or
starts an encoder. These movies summarize the recorded viewpoints.

Use a system `ffmpeg`, or install the optional encoder in the isolated UI runtime:

```bash
python3 -m pip install --target .deployment/preview-runtime --no-deps \
  -r integrations/benchforge/ui/requirements-preview.txt
```

An existing scene can be exported ahead of browsing with
`ui/scene_preview_video.py --config <operator-config> --session <session-id>
--scene <scene-run-id>` using the configured production Python. Export and media
access retain the existing session and revision checks. While a new movie is
unavailable, a scene's recorded views remain directly browsable.

## Shared scene library and source selection

The workbench registers completed captured scenes from the configured operator
service in `<workspace>/scene-library/catalog.json`. This includes past and new
productions, with a stable task ID, revision, name and original source directory.
The index retains original media and scene programs in their existing locations.
The workbench fetches scene metadata from the backend in pages and loads
capture-view metadata for the displayed page. Configure the artifact directory
so the workbench can read the saved evidence and media it serves.

The scene page supports search, current-conversation/history filters, pagination,
per-scene checkboxes and select/clear for the displayed page. Preview remains
available for unchecked scenes. Selections are saved atomically to
`scene-library/selections/<session-id>.json`, independently for each conversation.
The first selection includes that conversation's available captures. An explicit
selection never silently gains newly indexed scenes.

Each production demand and stage-change request reads the saved selection before
calling the native submission API. Its source contract includes exact task IDs,
revisions, capture directories, scene-program paths and the selection file.
Unchecked existing scenes are excluded. The separate **Allow new scenes** checkbox
controls whether generation is permitted. Empty selections with generation disabled,
missing scene files, changed revisions and failed constraint reads block submission.
Concurrent windows use a version check to prevent lost changes. The authenticated
DSH connection dispatches the selection POST; the browser's origin is not compared
with the bridge's internal virtual Request origin.

## Test the code without production jobs

The native Isaac SpatialTree trajectory option extends action recordings with RGB, depth,
semantic/instance annotators, camera/object poses and action timestamps from the
same simulator state.

For focused iteration, `benchforge_capture` accepts optional
`capture_options: {view_indices: [2], export_scene: false}`. This captures the
third program camera as `view_2` and skips USD/resource export. The complete
SceneProgram, all physics actions and requested action recordings still run.
Use `view_indices: []` for action evidence alone. Omitting `capture_options`
captures all cameras and exports the scene, including after a focused run.
The report records the selection in `capture_scope`; skipped views are not
visually assessed, and a skipped export provides no new loadable USD.
Choose the outputs needed for the current task; no iteration mode is mandatory.

Delivery review follows the latest capture across turns when the agent resumes
that run through status, wait or task evidence. An unrelated follow-up leaves old
captures alone. Once the review has been issued, later status reads do not repeat
it. This tracks delivery feedback; it does not certify that the user's task is complete.

After a capture or observation tool returns, the next model decision receives
the capture facts and images before it chooses further tools or closes a goal.
This also reads nested PTC tool results when `run_code` returns. It does not
interrupt a running PTC program, alter goal state, reject completion calls, or
impose a repair sequence. The existing turn-end hook covers other finalization
paths and uses the same review deduplication.

```bash
python integrations/benchforge/smoke.py
```

Python uses a local HTTP server to verify the request contract. Node replays
the actual review functions, including failed physics, missing image visibility,
reference/render attachments and broken delivery links. The former fixture that
simply asserted `success=true` and `loadable=true` has been removed.

With a built DSH checkout, test real subagent creation and resumption:

```bash
node integrations/benchforge/tests/replay_subagents.mjs \
  --dsh-root /path/to/deepseek-harness --output /tmp/benchforge-subagent-replay
```

This starts two overlapping child agents through DSH's `subagent` tool, exercises
their inherited collaboration tool, lets them settle, and resumes one through
`send_message` using its persisted session. It checks that the parent can read
the resolved handoff while the earlier blocker remains in history. JSON session
events and the report are saved under `--output`; each run uses a fresh workspace.
The adapter uses scripted responses and labeled fixture artifacts, with no model
API, service request or Isaac process. It tests orchestration and persistence,
not autonomous model decisions or scene quality. `--plugin` can select another
deployed BenchForge `tools.mjs` for the same replay.

## Install the bundled service

The BenchForge service, PostgreSQL storage, SAM worker adapters and desktop executor
are under `components/benchforge/`. See the [installation instructions](../../README.md)
to create a new service and attach one Windows desktop. The root
`benchforge_app.py dsh-setup` and `dsh-start` commands use the locally generated
service credentials automatically. Model setup is documented separately so a
capture or existing-mesh task does not require installing unused models.
