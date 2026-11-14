# BenchForge DSH integration

| Directory | Responsibility |
| --- | --- |
| `presets/` | Compose DSH presets and Host plugins, generate the deployment overlay and install profile updates. |
| `tools/` | Register Agent tools, shell and execution plugins, and preset-scoped policies. |
| `host/` | Own capture observation, session operations and the authenticated workbench Gateway routes. |
| `ui/` | Declare the Web Client package and render the workbench from Gateway responses. |
| `shared/` | Configuration, tool names, templates and collaboration used across DSH entry points. |
| `task_support/` | Python helpers and reference data used by tools and preparation sessions. |
| `maintenance/` | Operator commands for scene library and question-set repairs. |

The bundle uses the [Python core](../benchforge_core/) and the
[BenchForge HTTP service](../backend/). The Web Client calls the DSH Gateway.

The bundle exposes two custom presets. Official `standard`, `ptc`,
`minimal` and `cordis` presets remain unchanged.

| Display name | Purpose | Stable session identity |
| --- | --- | --- |
| **BenchForge** | BenchForge scene/data production in the standard DSH conversation | `benchforge` |
| **BenchForge_UI** | The same production capabilities with the visual workbench | `benchforge-ui` |

The DSH preset integration resolves saved conversations to the current preset
names while preserving their session history, workspace and saved artifacts.
Active sessions retain their bound tool version until DSH releases it.

The two presets share `presets/preset_definition.py`. The UI variant
adds workbench guidance and registers the Web package. `presets/build_preset.py` composes the common
DSH plugins, `presets/build_presets.py` generates the catalog, and
`presets/profile_migration.py` retires the old preset declaration during profile merges.
Existing session files stay in their workspace.

## Evaluation workbench UI

`npm ci --prefix src/dsh` builds the workbench after installing dependencies.
After editing workbench sources, rerun `npm run build:benchforge-ui --prefix src/dsh`.
The build uses the DSH Typert generator with the Host project's TypeScript
declarations, then compiles the Host and bundles the generated Remote
contribution into the Web Client. The Host package exports `./typert` and `./remote`.

`ui/client/` renders runs, artifacts, datasets and quality reports. Its JSON
requests use the DSH Gateway's `benchforgeWorkbench` unary Remote methods. The Host
owns data access, pagination and Fetch routes for downloadable artifacts.
Install or refresh the workbench in a running DSH with
`python src/dsh/presets/install_workbench.py`.
The Host mounts capture observation and session operations as Cordis services.
The Gateway routes consume those services, and the scene tools use the same
session operations for preparation. The client mounts the workbench for
`benchforge-ui` and previously saved workbench sessions. `install_workbench.py` and
`hot_update.py` use the same migration logic and preserve configured historical
workspace roots.
The workbench uses the configured service URL and operator token to read run
history and the shared scene catalog over the BenchForge API. The backend owns
the database queries and serves observations and stage retries through its API.

The workbench and Python core share the assessment and task templates in
`src/benchforge_core/pipelines/`. The npm pack step copies them into the published
bundle so it can load templates outside the source checkout. It also includes
the capture acknowledgement module used by the external dispatcher source bundle.

## Current FIT simulation route

The current production route is:

```text
DSH on FIT
  → FIT BenchForge service and queue
  → external a800-remote-fit dispatcher
  → FIT 127.0.0.1:18766 reverse-SSH endpoint
  → thunlp-node1, Isaac Sim 6.2.0 on A800
  → capture and evidence returned to FIT
```

`desktop-isaac` is a retained database lease name; the active remote worker is
`a800-remote-fit`. FIT's loopback port is a tunnel endpoint, not a local Isaac
process. The dispatcher and the Isaac installation on A800 are deployed outside
this repository. A successful real DSH task has verified this route, but that
receipt does not prove present service health or throughput. The Windows worker
described by the self-hosted install guide is an alternative deployment, not the
current FIT production worker.

## FIT checkout location

For an existing FIT installation, update its maintained checkout at
`/home/maqiang/GitHub/BenchForgeV2` on the explicitly selected branch. Standalone
installations follow the root README and use their own directory. Task templates are under
`src/benchforge_core/pipelines/task_templates.json` and pipeline recipes under
`src/benchforge_core/pipelines/definitions/`.

Machine-local `.deployment/` holds Python launchers, deployment receipts and
retained historical revisions. These files are ignored by Git. After migration,
both preset definitions use this maintained checkout. Do not delete old `published`,
`legacy` directories or compatibility symlinks while retained sessions still use
them; migration updates declarations, not in-flight tool bindings.
Model weights, environments, simulator installations and production artifacts
remain in their existing runtime locations.

### Consolidate an existing profile without changing DSH

Fast-forward the deployment checkout on the selected branch, then run the updater
from its new path with the existing Python environment.

```bash
cd /home/maqiang/GitHub/BenchForgeV2
git pull --ff-only
.deployment/python-development src/dsh/presets/hot_update.py
```

The updater consolidates the two presets in the user's web profile and waits for the runtime to adopt both
names and revisions. It preserves unrelated profile entries, configured
model options and historical workbench roots. Canonical plugin URLs participate
in DSH hot reload; the revision is stored in configuration.
It never edits DSH source or official presets, restarts DSH, or starts model/GPU
services. Already-bound sessions keep their previous tool revision and acquire
the current display name. New sessions use the updated composition. For later
updates from this layout, `--pull` fast-forwards the current branch and runs the
updated script. The profile is backed up under `.deployment/` and restored if
runtime adoption fails.

Keep the deployment's settings in `config/benchforge.local.json` and run
`python benchforge_app.py sync` to prepare the client configuration for hot
update. The updater also uses the deployment's `.deployment/python-development`
launcher. Configure the DSH model, HTTP providers and Isaac capture in
`config/benchforge.local.json`.

## Install and configure

Use the DSH `0.2.2-rc.3` fork pinned by BenchForge with Node `>=24.9.0`. The manifest pins the API version
verified for these adapters; upgrade the pins together after testing against the
target Harness. A linked checkout shares the running Harness packages through
the public peer dependencies. Standalone tests use the matching dev dependencies.

For a fresh checkout or CI runner, install the locked Node dependencies before
running the integration smoke checks:

```bash
npm ci --prefix src/dsh
python src/dsh/smoke.py
```

Installing Python extras alone does not install the public DSH Node packages.

From the repository root:

```bash
pip install -e '.[dsh]'
dsh plugin --profile web add ./src/dsh
dsh --profile web --dump-config
```

The portable bundle uses `python3`, `config/benchforge.local.json` and the generated
`config/generated/benchforge-client.local.json` relative to the DSH launch directory.
Use `benchforge_app.py init` to create the local file and `sync` after setting
`client` and `providers`. Pass credentials through the launch environment.
Use the generated local overlay to install the configured DSpark model at Host
scope. The portable bundle imports the preset and tool definitions.
Check the operator connection with
`python src/dsh/cli.py status --config config/generated/benchforge-client.local.json`.
Add `--run-id sf_YOUR_RUN` to read a specific run.
To select another Python environment or explicit config paths, generate a
deployment overlay:

```bash
python src/dsh/presets/build_presets.py \
  --dsh-resolve-from /path/to/dsh-cli/package.json \
  --node /path/to/current/node \
  --python /path/to/python \
  --config /private/benchforge-config.json \
  --service-config /private/generated/benchforge-client.local.json \
  --output /private/benchforge-presets.patch.yml
python src/dsh/presets/install_preset.py \
  --profile /private/dsh/profiles/web/cordis.patch.yml \
  --preset /private/benchforge-presets.patch.yml
```

`--dsh-root /path/to/deepseek-harness` remains compatible with a source install.
It only supplies a Node module lookup location; the builder resolves official
`@deepseek-ai/dsh-web-app/presets/*.patch.yml` exports rather than reading private
`packages/...` source paths. `--node` can also be set with `BENCHFORGE_DSH_NODE`.
The generated overlays reference this checkout, and the distributed bundle uses
the public subpackage exports, including `@eurecamoment/benchforge-dsh/benchforge-ui`.
Neither path edits official preset files. Use one installation source for the
V2 declarations: the portable bundle for a fresh installation, or the merged
profile for an existing deployment. Do not add duplicate preset declarations on
top of an already-installed bundle.

Regenerate the distributed bundle after changing composition:

```bash
python src/dsh/presets/build_presets.py --package-imports --output src/dsh/cordis.patch.yml
```

The merge updates built-in preset row IDs, keeps custom Cordis row IDs, collapses
duplicate preset declarations, and preserves deployment-specific plugins, environment
options and data directories. Test output,
profile backups and deployment receipts belong outside tracked source files.

## Persistent shell configuration

`@eurecamoment/benchforge-dsh/persistent-shell` delegates to the official
`@deepseek-ai/dsh-tool-bash-persistent` or `dsh-tool-pwsh-persistent` package.
Its `Config` accepts `shell`, `backendType`, `timeoutMs`, `maxOutputChars` and
`description`. Defaults are the official `shell` backend, 300000 milliseconds
and 16000 output characters. The wrapper preserves the tool names
`persistent_bash` and `persistent_pwsh`; the official package still owns shell
session isolation, cancellation and disposal. Legacy `dshRoot` is accepted but
no longer participates in runtime imports.

The checked-in bundle presets are composed from the public preset exports in
DSH `0.2.2-rc.3`. It copies the standard interaction capabilities and mounts a
tool executor for both direct calls and `run_code`. It adds persistent shells and Cordis tools, then adds the
selected business plugins. Static configuration fields are validated by their plugin
schemas. The bundle ships no weights, credentials, backend executable or model
service configuration.

## Tool process ownership

Business CLI calls use the Harness `subprocess` provider. Cancellation and plugin
unload join the complete owned range before returning. JSON output defaults to
16 MiB of bounded collection (`maxOutputBytes`); oversized results fail explicitly
instead of parsing a truncated tail. `graceMs` defaults to 1000 milliseconds.

The subprocess provider scrubs ambient credential-shaped and `DSH_*` variables.
Set `forwardEnvironment` to the specific variable names required by your private
business configuration, or supply explicit entries in `environment`; forwarded
values come from the launch snapshot. Model tool invocations also forward the
credential named by their provider configuration to that invocation.

On FIT, explicit `spatial_train(action="start")` and `backend(action="start")`
transfer to their own systemd user service before returning. Their result includes
`pid`, `service` and `owner`; the run/job log remains in the configured workspace.
Cancelling an ordinary call does not terminate a job that has already transferred
ownership. Existing HTTP service run IDs retain the same background ownership.

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
  -r src/dsh/host/workbench/requirements-preview.txt
```

An existing scene can be exported ahead of browsing with
`host/workbench/scene_preview_video.py --config <operator-config> --session <session-id>
--scene <scene-run-id>` using the configured production Python. Export and media
access retain the existing session and revision checks. While a new movie is
unavailable, a scene's recorded views remain directly browsable.

## Shared scene library and source selection

The workbench registers completed captured scenes from the configured operator
service in `<workspace>/scene-library/catalog.json`. This includes past and new
productions, with a stable task ID, revision, name and original source directory.
The index retains original media and scene programs in their existing locations.
The workbench reads scene metadata in pages and loads capture-view metadata for
the displayed page. Configure the artifact directory so the workbench can read
the saved evidence and media it serves.

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
python src/dsh/smoke.py
```

Python uses a local HTTP server to verify the request contract. Node replays
the actual review functions, including failed physics, missing image visibility,
reference/render attachments and broken delivery links. The former fixture that
simply asserted `success=true` and `loadable=true` has been removed.

With a built DSH checkout, test real subagent creation and resumption:

```bash
node src/dsh/tests/replay_subagents.mjs \
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
