# SpatialForge integration

This directory connects the BenchForge DSH mode to the SpatialForge scene and
interaction harness without bundling private FIT paths, credentials, model
weights, or Isaac installations.

## Offline verification

From the repository root, run:

```powershell
python integrations/spatialforge/smoke.py
```

The smoke test replays a small capture receipt and checks that the delivery
contract keeps capture, visual review, interaction, and scene-file status
separate. It does not call a model API, start Isaac, or require a service.

## Real deployment

Copy `config.example.json` to a private file and set `SPATIALFORGE_CONFIG` to
that file. The configuration must point at an already deployed FIT service and
desktop worker. Credentials stay outside Git. The adapter is intentionally
thin: DSH chooses the operation and SpatialForge owns scene execution,
evidence, and delivery artifacts.

```powershell
$env:SPATIALFORGE_CONFIG = (Resolve-Path .\integrations\spatialforge\config.local.json)
python integrations/spatialforge/cli.py status
```

Isaac Sim and GPU model services are optional for the offline command and must
be installed and configured separately for real capture. Do not run a second
Isaac instance on a shared worker.
