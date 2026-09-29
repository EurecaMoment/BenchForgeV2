# Release 0.2.0

Repository: https://github.com/EurecaMoment/BenchForge

This release exposes the original benchmark production methods and algorithms
as composable DSH capabilities, with real Qwen/Habitat acceptance, real annotation
chain execution, CARLA/LIBERO captures and cross-machine package replay.
See [validation](VALIDATION.md) for measured scope and remaining limits.

Run `python benchforge.py demo` for the no-install core check, or install
`.[production,research]` and run `examples/production_demo.py` for visual
compilation. `python benchforge.py setup` / `start` launch the DSH application.

Only code, attribution, methods, configuration examples and sanitized validation
summaries are published. Model weights, source datasets, private credentials,
local service files and built DSH dependencies are excluded.
