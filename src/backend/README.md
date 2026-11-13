# BenchForge runtime

`benchforge_backend/` manages scene programs, generated and native assets, the
PostgreSQL job queue, capture transport and delivery. `pic2sim/` provides the
SAM3 and SAM3D workers. `desktop/` contains the desktop dispatcher and native
capture helpers, and `grpc/` contains the Isaac transport and local test server.
The Isaac executor and model deployments use their own runtimes, assets and
weights.

`deploy/dispatcher/` contains the source bundle for the external worker
dispatcher. Its capture acknowledgement uses the backend Store.
`deploy/trellis/` contains the TRELLIS service setup and benchmark.

Install the backend in its Python environment with
`python -m pip install -e src/backend` from the repository root. See the
[root README](../../README.md) for setup and the [project notice](../../NOTICE)
for source attribution.
