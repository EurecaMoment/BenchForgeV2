# BenchForgeV2 DSH integration

This directory is the Node plugin subpackage of the **same BenchForgeV2
repository**. It declares public entrypoints and a DSH bundle manifest. Python
business code and the existing BenchForgeV2 HTTP service remain separate runtime
dependencies; installing the bundle does not provision or restart them.

The bundle exposes two custom presets. Official `standard`, `ptc`,
`minimal` and `cordis` presets remain unchanged.

| Display name | Purpose | Stable session identity |
| --- | --- | --- |
| **BenchForgeV2** | BenchForgeV2 scene/data production in the standard DSH conversation | `benchforgev2` |
| **BenchForgeV2_UI** | The same production capabilities with the visual workbench | `spatialforge-standard-ptc` |

`BenchForgeV2_UI` deliberately retains the original workbench preset identity. DSH
resolves the displayed name from its current preset roster, so old conversations
show the new name without rewriting their session history. Their workspace,
session ID, artifact routes and data ownership stay intact. Active sessions keep
their already-bound tool generation until DSH releases it.

The two V2 presets share `spatialforge/preset_definition.py`. The UI variant
adds workbench guidance and the host reader. `dsh/build_preset.py` composes the common
DSH plugins, `dsh/build_presets.py` generates the catalog, and
`dsh/profile_migration.py` retires the old preset declaration during profile merges.
Existing session files stay in their workspace.

## Evaluation workbench UI

`spatialforge/ui` is a separate root UI plugin in this same repository. It adds
the DSH BenchForgeV2_UI session workbench with persisted runs/artifacts, version-isolated dataset
browsing, server-side pagination and generation quality reports. It does not edit
official DSH source or start model/simulator services. Install or refresh it in an
already running DSH with `python integrations/spatialforge/install_workbench.py`.
The reader is registered once at the host level so already-bound conversations
can still browse their history. The client mounts the workbench only for the
retained `spatialforge-standard-ptc` identity. BenchForgeV2 and official
presets keep their normal conversation interface. `install_workbench.py` and
`hot_update.py` use the same migration logic and preserve configured historical
workspace roots.
The workbench uses the backend configuration and its database connection to read
session-owned runs and the shared scene catalog.

## Current FIT simulation route

The current production route is:

```text
DSH on FIT
  → FIT BenchForgeV2 service and queue
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
both V2 preset definitions use this maintained checkout. Do not delete old `published`,
`legacy` directories or compatibility symlinks while retained sessions still use
them; migration updates declarations, not in-flight tool bindings.
Model weights, environments, simulator installations and production artifacts
remain in their existing runtime locations.

### Consolidate an existing profile without changing DSH

After integrating this revision into the deployment checkout, run the following
with its existing Python environment. `--pull` only fast-forwards its current
branch; it does not switch branches or replace uncommitted deployment edits.

```bash
cd /home/maqiang/GitHub/BenchForgeV2
.deployment/python-development integrations/spatialforge/hot_update.py --pull
```

The script fast-forwards the checkout's current branch when requested, consolidates the two
V2 presets in the user's web profile and waits for the runtime to adopt both
names and revisions. It preserves unrelated profile entries, configured
model options and historical workbench roots. Canonical plugin URLs participate
in DSH hot reload; the revision is stored in configuration.
It never edits DSH source or official presets, restarts DSH, or starts model/GPU
services. Already-bound sessions keep their previous tool revision and acquire
the current display name. New sessions use the updated composition. To use code
already deployed, omit `--pull`. The profile is backed up under `.deployment/`
and restored if runtime adoption fails.

The private files `config/benchforge.local.json`,
`config/generated/spatialforge.local.json` and `.deployment/python-development`
must already exist. Configure available model endpoints under `model_services`
in the shared BenchForge configuration.

## Install and configure

Use DSH `0.1.7-rc.1` with Node `^22.19.0 || >=24`. The manifest pins the API version
verified for these adapters; upgrade the pins together after testing against the
target Harness. A linked checkout shares the running Harness packages through
the public peer dependencies. Standalone tests use the matching dev dependencies.

For a fresh checkout or CI runner, install the locked Node dependencies before
running the integration smoke checks:

```bash
npm ci --prefix integrations
python integrations/spatialforge/smoke.py
```

Installing Python extras alone does not install the public DSH Node packages.

From the repository root:

```bash
pip install -e '.[dsh]'
dsh plugin --profile web add ./integrations
dsh --profile web --dump-config
```

The portable bundle expects `python3`, `config/benchforge.local.json` and
`config/spatialforge.local.json` relative to the DSH launch working directory. Copy the appropriate
example configs and use the existing service endpoint; credentials belong in
the DSH launch environment, not this package. To select another Python
environment or absolute config paths, generate a deployment overlay:

```bash
python integrations/dsh/build_presets.py \
  --dsh-resolve-from /path/to/dsh-cli/package.json \
  --node /path/to/current/node \
  --python /path/to/python \
  --config /private/benchforge-config.json \
  --service-config /private/spatialforge-config.json \
  --output /private/benchforge-presets.patch.yml
python integrations/dsh/install_preset.py \
  --profile /private/dsh/profiles/web/cordis.patch.yml \
  --preset /private/benchforge-presets.patch.yml
```

`--dsh-root /path/to/deepseek-harness` remains compatible with a source install.
It only supplies a Node module lookup location; the builder resolves official
`@deepseek-ai/dsh-web-app/presets/*.patch.yml` exports rather than reading private
`packages/...` source paths. `--node` can also be set with `BENCHFORGE_DSH_NODE`.
The generated overlays reference this checkout, and the distributed bundle uses
the public subpackage exports, including `@eurecamoment/benchforge-dsh/spatialforge-ui`.
Neither path edits official preset files. Use one installation source for the
V2 declarations: the portable bundle for a fresh installation, or the merged
profile for an existing deployment. Do not add duplicate preset declarations on
top of an already-installed bundle.

Regenerate the distributed bundle after changing composition:

```bash
python integrations/dsh/build_presets.py --package-imports --output integrations/cordis.patch.yml
```

The merge keeps existing Cordis row IDs, collapses duplicate declarations with
the same preset identity, and preserves deployment-specific extra plugins and
environment options. It never renames or moves data directories. Test output,
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
DSH `0.1.7-rc.1`. It copies the standard interaction capabilities, adds PTC in
`both` mode, the owner-scoped persistent shells and Cordis tools, then adds the
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
values come from the launch snapshot. Do not forward the entire host environment.

On FIT, explicit `spatial_train(action="start")` and `backend(action="start")`
transfer to their own systemd user service before returning. Their result includes
`pid`, `service` and `owner`; the run/job log remains in the configured workspace.
Cancelling an ordinary call does not terminate a job that has already transferred
ownership. Existing HTTP service run IDs retain the same background ownership.
