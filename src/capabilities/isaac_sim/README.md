# Scene production

Authors scene programs, queues remote asset generation and Isaac captures, reviews
evidence and maintains accepted scene revisions.

| Directory | Responsibility |
| --- | --- |
| `contracts/` | Serializable scene schemas and tool responses |
| `server/scene_program/` | Authoring, catalogs, geometry, cameras and admission |
| `server/asset_generation/` | Generated assets and representation conversion |
| `server/production_queue/` | Scheduling, request ownership and task workspaces |
| `server/capture_evidence/` | Review, observation, transfer, recovery and lookup |
| `server/scene_library/` | Scene catalog, selections, repair and previews |
| `server/storage/` | Database schema, state transitions and projections |
| `server/isaac_sim/` | gRPC, worker/resident, capture, scene, appearance and rendering |
| `dsh/` | Scene tools and Host query adapters |
| `client/` | Browser gallery components |
| `resources/` | Native asset/material metadata and previews |
| `deploy/` | Database and external dispatcher deployment |

Install from the repository root with `python -m pip install -e '.[production]'`.
Start the HTTP service with `python -m server.http_api --config <server-config>`.
Start a worker with `python -m capabilities.isaac_sim.processes.worker --config <worker-config>`.

Model inference uses HTTP providers. Isaac uses gRPC or the configured local worker.
The mock gRPC server returns explicitly synthetic evidence for transport checks.
Cross-feature callers use `scene_production.api` and contracts.
See the [complete source tree](../README.md) and [deployment guide](../../README.md).
