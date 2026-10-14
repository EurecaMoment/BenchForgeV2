# Desktop Isaac process reuse

The desktop dispatcher uses one installed Isaac process for sequential captures.
The FIT queue still owns the task and attempt token; no second queue or remote
simulator is introduced. DSH and model services do not change.

`desktop/worker.py` sends request/output paths through a local file mailbox to
`desktop/isaac_resident.py`. The resident creates `SimulationApp` for its first
request, calls the existing SceneProgram executor, then detaches annotators,
destroys the render product, stops physics, clears SimulationContext callbacks
and singleton, and closes the USD stage. It publishes a completion receipt only
after cleanup. The worker can then upload immediately while Isaac remains idle.
Each task restores the boot renderer settings before applying its exposure and
sampling overrides. Scene geometry, cameras, GT and evidence are rebuilt for
each request; this does not reuse a previous scene's answers.

Compatible renderer, resolution and extension configurations reuse the process.
An incompatible configuration retires the old process before launching its
replacement. Cleanup errors also retire it. Cancellation and timeout terminate
only the owned resident process tree. A supervisor restart adopts the current
attempt and waits for its receipt rather than launching the same task again.
Transport retries reuse completed native output files.

The worker configuration accepts:

```json
{
  "isaac_resident": true,
  "isaac_idle_seconds": 300,
  "capture_timeout_seconds": 1800
}
```

After five idle minutes the engine releases Isaac/GPU resources. Set
`isaac_resident` to `false` to use one process per capture. Before switching modes
or opening a separate local viewer, wait for the owned engine to exit. Do not
run two workers or simulators. Mailbox and execution receipts live under
`<runs>/resident` and `<runs>/<attempt>`; `resident/isaac.log` records the engine.
An existing `report.json` alone is not proof that resident cleanup finished.

This optimization preserves resolution, path-tracing sampling, requested views,
RGB/depth/semantic/instance outputs, physics evidence and scene export. Its
benefit is removing repeated application startup/shutdown and the old eight
second process polling delay. Asset preparation, scene building, rendering and
artifact upload still take time; measure cold and warm requests separately.
