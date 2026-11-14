# BenchForge runtime

`benchforge_backend/` manages scene programs, assets, the PostgreSQL job queue,
capture transport and delivery. `model_clients.py` calls the configured HTTP
providers and saves their outputs as task artifacts. Each provider runs its
own inference service.

`benchforge_backend/isaac/` contains the gRPC client, capture protocol and
loopback mock. `desktop/` contains the capture queue worker and the optional
local Isaac resident. Configure the transport under `providers.IssacSim4A100`
in the root configuration.

`deploy/dispatcher/` contains the source bundle for the external worker
dispatcher. Its capture acknowledgement uses the backend Store.

Install the backend in its Python environment with
`python -m pip install -e src/backend` from the repository root. See the
[root README](../../README.md) for setup and the [project notice](../../NOTICE)
for source attribution.
