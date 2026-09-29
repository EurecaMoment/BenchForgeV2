# SpatialForge integration

`plugin/tools.mjs` contains the production tool definitions and the delivery
review hooks, adapted to a configured DSH root, service URL and token environment
variable. No private host paths or tokens are embedded. `build_preset.py` combines
them with BenchForge in a separate **BenchForgeV2** preset.

## Existing service connection

Run DSH on the SpatialForge service machine: returned evidence paths are local
to that machine. Configure the service's existing Windows desktop worker and use
its single Isaac queue. This client never starts another worker or simulator.

Copy `config.example.json` to a private `spatialforge.local.json`. Set
`SPATIALFORGE_OPERATOR_TOKEN` in the environment used to launch DSH, then:

```bash
python integrations/spatialforge/cli.py status --config spatialforge.local.json
python integrations/spatialforge/cli.py status --config spatialforge.local.json --run-id sf_YOUR_RUN
python benchforge.py setup --spatialforge-config spatialforge.local.json
python benchforge.py start
```

Without a run ID, status calls authenticated `POST /catalog`; with an ID it calls
`POST /observe`. SpatialForge has no run-status `GET /status` endpoint.
Missing config or credentials fails with an actionable error.

## Multi-agent collaboration

The combined preset exposes `benchforge_collaboration` and the SpatialForge plugin exposes `spatialforge_collaboration` for lightweight, shared-workspace handoffs. Agents can publish a role, status, inputs, findings, artifact paths, blockers, decisions and next actions, relate or reply to earlier handoffs, then list or read the record when another agent resumes the task. This is an artifact protocol rather than a fixed orchestration graph: agents can work sequentially or in parallel, and the parent agent decides how to merge their findings.

Useful roles include planning, asset/layout construction, visual review, interaction/physics review, dataset/export review and delivery editing. Handoffs can reply to or relate earlier work and can carry a decision and confidence when a parent agent needs to reconcile parallel findings. Keep them short and concrete. Independent work may run in parallel; the single configured Isaac queue remains the shared execution boundary.

## Test the code without production jobs

```bash
python integrations/spatialforge/smoke.py
```

Python uses a local HTTP server to verify the request contract. Node replays
the actual review functions, including failed physics, missing image visibility,
reference/render attachments and broken delivery links. The former fixture that
simply asserted `success=true` and `loadable=true` has been removed.

## Install the bundled service

The service, PostgreSQL/BenchClaw engine, SAM worker adapters and desktop executor
are under `components/`. Use [the installation guide](../../docs/SPATIALFORGE_INSTALL.md)
to create a new service and attach one Windows desktop. The root
`spatialforge_app.py dsh-setup` and `dsh-start` commands use the locally generated
service credentials automatically. Model setup is documented separately so a
capture or existing-mesh task does not require installing unused models.
