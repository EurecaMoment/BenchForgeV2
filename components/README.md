# Bundled runtime components

- `spatialforge/`: scene service, native asset/material catalog, task sandbox,
  generated-asset adapters, durable capture transport, and Windows Isaac executor.
- `benchclaw/`: PostgreSQL repository, dataset specification, deterministic spatial
  question algorithms, template engine and data export used by SpatialForge.
- `spatialforge/src/pic2sim/`: the SAM3/SAM3D worker dependency closure from the
  author's Pic2Sim/BenchForge_v2 implementation. The old pipeline is not launched.

These sources were imported from the author's working implementations for this
publication. The original BenchClaw Apache-2.0 LICENSE is retained. Upstream SAM3,
SAM3D, diffusion software, model weights and Isaac assets are installed separately
under their own licenses. Existing benchmark algorithms retain their notices.

Engineering changes in this import configure paths and credentials, bundle missing
dependencies and initialize the fresh task sandbox. Simulator/GT semantics and
the delivery-review rules were preserved. Historical scene evidence does not count
as acceptance of this fresh installation.
