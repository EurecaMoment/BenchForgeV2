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

Publish a complete new snapshot with the same `handoff_id` to update it. `list` returns one current record per handoff and filters that current state by status, role or agent; a resolved blocker will not reappear from an earlier version. `read` returns the same latest snapshot. Use `list` with `history: true` for earlier versions, including old blockers and agent assignments. The append-only file keeps all versions for inspection.

A receiving agent can use `spatialforge_status` or `spatialforge_wait` with a shared capture's `run_id`. When its session has no capture submission, this explicit observation lets the existing delivery review load that completed capture and its images. The submitting agent's conversation is not required. Repeated observations do not repeat the review; unrelated turns do not reopen the task. Generation and dataset operations keep their own behavior. A received handoff or review message does not establish that the user's requirements are complete.

## Test the code without production jobs

Delivery review follows the latest capture across turns when the agent resumes
that run through status, wait or task evidence. An unrelated follow-up leaves old
captures alone. Once the review has been issued, later status reads do not repeat
it. This tracks delivery feedback; it does not certify that the user's task is complete.

```bash
python integrations/spatialforge/smoke.py
```

Python uses a local HTTP server to verify the request contract. Node replays
the actual review functions, including failed physics, missing image visibility,
reference/render attachments and broken delivery links. The former fixture that
simply asserted `success=true` and `loadable=true` has been removed.

With a built DSH checkout, test real subagent creation and resumption:

```bash
node integrations/spatialforge/tests/replay_subagents.mjs \
  --dsh-root /path/to/deepseek-harness --output /tmp/spatialforge-subagent-replay
```

This starts two overlapping child agents through DSH's `subagent` tool, exercises
their inherited collaboration tool, lets them settle, and resumes one through
`send_message` using its persisted session. It checks that the parent can read
the resolved handoff while the earlier blocker remains in history. JSON session
events and the report are saved under `--output`; each run uses a fresh workspace.
The adapter uses scripted responses and labeled fixture artifacts, with no model
API, service request or Isaac process. It tests orchestration and persistence,
not autonomous model decisions or scene quality. `--plugin` can select another
deployed SpatialForge `tools.mjs` for the same replay.

## Install the bundled service

The service, PostgreSQL/BenchClaw engine, SAM worker adapters and desktop executor
are under `components/`. Use [the installation guide](../../docs/SPATIALFORGE_INSTALL.md)
to create a new service and attach one Windows desktop. The root
`spatialforge_app.py dsh-setup` and `dsh-start` commands use the locally generated
service credentials automatically. Model setup is documented separately so a
capture or existing-mesh task does not require installing unused models.
