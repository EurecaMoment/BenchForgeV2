# BenchForge runtime

The bundled `benchforge/` package manages scene programs, generated and native
assets, the PostgreSQL job queue, capture transport, delivery and the desktop
dispatcher. It includes SAM3 and SAM3D worker dependencies under `src/pic2sim/`.
The Isaac executor and model deployments require their own installed runtimes,
assets and weights.

`benchforge/deploy/dispatcher/` contains the source bundle for the external
worker dispatcher. Its capture acknowledgement uses the backend Store.
`benchforge/deploy/trellis/` contains the TRELLIS service setup and benchmark.

See the [root README](../README.md) for setup and the [project notice](../NOTICE)
for source attribution.
