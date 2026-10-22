# BenchForgeV2 DSH integration

This directory is the Node plugin subpackage of the **same BenchForgeV2
repository**. It declares public entrypoints and a DSH bundle manifest. Python
business code and the existing SpatialForge HTTP service remain separate runtime
dependencies; installing the bundle does not provision or restart them.

The bundle adds one independent **BenchForgev2** preset. It does not replace
`standard`, `ptc`, `minimal`, `cordis`, the first-generation **BenchForge** preset,
or the separately configured **SpatialForge** development preset. Their existing
deployment bindings remain owned by the user profile. These are three modes in
one DSH installation, not three maintained application repositories.

## Evaluation workbench UI

`spatialforge/ui` is a separate root UI plugin in this same repository. It adds
the DSH sidebar workbench with persisted runs/artifacts, version-isolated dataset
browsing, server-side pagination and generation quality reports. It does not edit
official DSH source or start model/simulator services. Install or refresh it in an
already running DSH with `python integrations/spatialforge/install_workbench.py`.
See [the workbench guide](../docs/frontend-workbench-v2.md) for data boundaries,
configuration and acceptance requirements.

## Current FIT simulation route

The current production route is:

```text
DSH on FIT
  → FIT SpatialForge service and queue
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

The maintained FIT checkout is `/home/maqiang/GitHub/BenchForgeV2`, on the
`SpatialForge` development branch. Update this checkout in place; do not create
a new top-level directory for each commit. Task templates are under
`src/benchforge_core/pipelines/task_templates.json` and pipeline recipes under
`src/benchforge_core/pipelines/definitions/`.

Machine-local `.deployment/` holds the retained `published` and `legacy`
versions, Python launchers, deployment receipts and `history/`. These files are
ignored by Git. The three DSH modes remain distinct: SpatialForge uses the
checkout root, BenchForgev2 uses `.deployment/published`, and BenchForge uses
`.deployment/legacy`. Historical external paths may remain compatibility
symlinks for existing sessions; they are not additional maintained checkouts.
Model weights, environments, simulator installations and production artifacts
remain in their existing runtime locations.

### Hot-update SpatialForge without changing DSH

Run the following in the fixed FIT checkout with its existing Python environment:

```bash
cd /home/maqiang/GitHub/BenchForgeV2
.deployment/python-development integrations/spatialforge/hot_update.py --pull
```

The script fast-forwards the existing `SpatialForge` branch, updates only that
custom preset in the user's web profile and waits for the official runtime to
adopt it. Revisioned plugin URLs also refresh the local SpatialForge helpers.
It never edits DSH source or official presets, restarts DSH, or starts model/GPU
services. Already-bound sessions keep their previous revision; a new SpatialForge
session uses the update. To use code already deployed, omit `--pull`.

The private files `.deployment/model-services.json`,
`.deployment/spatialforge.local.json` and `.deployment/python-development`
must already exist. See [independent model clients](../docs/MODEL_SERVICES.md)
for endpoint configuration and the eight callable interfaces.

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

The portable bundle expects `python3`, `config.local.json` and
`spatialforge.local.json` in the DSH launch working directory. Copy the appropriate
example configs and use the existing service endpoint; credentials belong in
the DSH launch environment, not this package. To select another Python
environment or absolute config paths, generate a deployment overlay:

```bash
python integrations/spatialforge/build_preset.py \
  --dsh-resolve-from /path/to/dsh-cli/package.json \
  --node /path/to/current/node \
  --python /path/to/python \
  --config /private/benchforge-config.json \
  --service-config /private/spatialforge-config.json \
  --output /private/benchforgev2.patch.yml
dsh --profile web --patch /private/benchforgev2.patch.yml --dump-config
```

`--dsh-root /path/to/deepseek-harness` remains compatible with a source install.
It only supplies a Node module lookup location; the builder resolves official
`@deepseek-ai/dsh-web-app/presets/*.patch.yml` exports rather than reading private
`packages/...` source paths. `--node` can also be set with `BENCHFORGE_DSH_NODE`.
The generated overlays reference this checkout, and the distributed bundle uses
the public subpackage exports. Neither path edits official preset files.

## Persistent shell configuration

`@eurecamoment/benchforge-dsh/persistent-shell` delegates to the official
`@deepseek-ai/dsh-tool-bash-persistent` or `dsh-tool-pwsh-persistent` package.
Its `Config` accepts `shell`, `backendType`, `timeoutMs`, `maxOutputChars` and
`description`. Defaults are the official `shell` backend, 300000 milliseconds
and 16000 output characters. The wrapper preserves the tool names
`persistent_bash` and `persistent_pwsh`; the official package still owns shell
session isolation, cancellation and disposal. Legacy `dshRoot` is accepted but
no longer participates in runtime imports.

The checked-in bundle preset was composed from the public preset exports in
DSH `0.1.7-rc.1`. It copies the standard interaction capabilities, adds PTC in
`both` mode, the owner-scoped persistent shells and Cordis tools, then adds the
two business plugins. Static configuration fields are validated by their plugin
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
