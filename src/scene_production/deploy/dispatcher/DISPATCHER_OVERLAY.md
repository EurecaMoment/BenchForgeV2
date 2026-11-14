# External Isaac dispatcher control overlay

This source overlay carries the owned retry-context and canonical acknowledgement
fixes for an existing `dsh_a800_worker.py`. The renderer, Isaac installation,
`isaac_client`, queue capacity and worker supervisor remain external prerequisites.

`/worker/context` and `/worker/finish` run the capture control script in the explicitly
configured **backend Python**. Its native Store validates the existing task ID,
revision, token and transport retry; the overlay never reads management `/inspect`
or changes database fields. Context preserves the full resume receipt. Finish
preserves the outcome, error, stopped-process flag and complete native receipt.
Control errors and timeout return promptly, without a management fallback or a
new capture. The existing remote-executor failure acknowledgement is unchanged.

Use the configured BenchForge backend Python with its SQLAlchemy and PostgreSQL
dependencies. The dispatcher and renderer use their existing interpreter.

## Prepare and install

Copy `dispatcher_overlay.example.json` to a private settings file and fill the
existing dispatcher path and backend Python. A null adapter path selects this
backend's `dispatcher_control.py` or the bundle's `capture_finish.py`. Service
configuration comes from the dispatcher's existing `CONFIG`, so control and
worker HTTP use the same store.
The module is loaded by an absolute path. Keep this source directory in place.

On existing FIT checkouts, install the backend from its new location with
`python -m pip install -e src/scene_production` in the backend environment. Set a previous
explicit `adapter_path` to the new `src/scene_production/server/isaac_sim/processes/dispatcher_control.py`
path or use a null value. Reapply the overlay to update the installed dispatcher
paths. It also updates the helper path embedded by the late-cancel patch.

```bash
python src/scene_production/deploy/dispatcher/deploy_dispatcher_overlay.py --config /private/dispatcher-overlay.json \
  --output /private/dsh_a800_worker.candidate.py
```

After reviewing the candidate, install it on the existing dispatcher host:

```bash
python src/scene_production/deploy/dispatcher/deploy_dispatcher_overlay.py --config /private/dispatcher-overlay.json --apply
```

Installation backs up and atomically replaces only the named dispatcher source.
It does not call a service, signal a process, start another worker or restart
DSH, a model, BenchForge or Isaac. The existing FIT supervisor observes its
source modification time and performs its normal slot handoff; an already bound
child keeps its current code until that handoff. Job directories, tokens, prior
remote jobs and successful native files are retained. Restore the printed backup
to the same dispatcher path to roll back through that same source reload mechanism.

The transformer supports the current context-aware control block and the earlier
finish-only block with its old retry-context prefix. Unrecognized source fails
before installation. It checks the unchanged HTTP transport, execution/resume
body and all unrelated functions by AST equality; no hashes or artifact scans
are performed. It does not replace the complete external dispatcher with a
repository snapshot.

## Publish a source bundle

The Node client package intentionally does not install an external Isaac worker.
Ship this overlay from the repository checkout or build its independent zip:

```bash
python src/scene_production/deploy/dispatcher/deploy_dispatcher_overlay.py \
  --bundle /tmp/benchforge-dispatcher-overlay.zip
```

The zip includes this module, deployment script, example settings, this guide,
`capture_finish.py` and `worker_cancellation.py`. It contains no credentials,
service configuration, Isaac runtime, Client package or native backend source.
Extract it into a stable directory on the dispatcher host, then prepare/install
using that directory's script. The existing configured native backend and its
current recovery/acceptance implementation must already be installed. This
bundle is not evidence that a target installation or capture has passed.
