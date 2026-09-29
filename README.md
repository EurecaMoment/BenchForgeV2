# BenchForge

An independent, composable benchmark-production mode for agent harnesses.

Repository: https://github.com/EurecaMoment/BenchForge

## Start the DSH-based application

Install Python 3.10+, Git and Node.js 22.19+ (or 24+), then:

```bash
git clone https://github.com/EurecaMoment/BenchForge.git
cd BenchForge
python benchforge.py setup
python benchforge.py start
```

Setup retrieves the pinned MIT-licensed DSH source into `third_party/`, installs/builds it once, prepares BenchForge's Python environment and generates the independent mode. First setup downloads and builds DSH; subsequent launches reuse it. To reuse an existing built checkout, use `python benchforge.py setup --dsh-root /path/to/deepseek-harness`.

The launcher uses a project-local DSH home and an overlay. Configure your model provider in DSH's UI, then select **BenchForge** in a new conversation. Model credentials are not bundled. GPU annotation and simulator environments are optional and configured separately. This is not a claim that every GPU dependency installs in a few seconds.

For an immediate offline core demonstration, run `python benchforge.py demo`. See the validation document for the distinction between verified core behavior and unverified fresh DSH builds / GPU integrations.

[中文快速开始](docs/QUICKSTART.zh-CN.md)

```bash
python quickstart.py
```

Run from the downloaded repository with Python 3.10+. The default demo needs no pip install, network, API key, GPU or DSH. To add the mode to an existing DSH installation:

```bash
python quickstart.py --dsh-root /path/to/deepseek-harness --profile /path/to/profile/cordis.patch.yml
```

This creates a project-local environment, generates the preset and installs only its own row with a backup. Omit `--profile` to generate without installing. Real annotation and simulation require their separately configured backends.

BenchClaw's planning, acquisition, annotation, construction and evaluation capabilities become individual tools. The host agent can inspect results, write task code, run independent work in parallel and correct a task without walking a mandatory five-stage DAG.

This repository does not import, modify, install into or require SpatialForge. It does not modify official DSH presets. It generates a separate **BenchForge** preset.

## SpatialForge scene integration

The optional `integrations/spatialforge/` adapter connects this repository to an
already deployed SpatialForge FIT service and desktop worker. It does not ship
private paths, tokens, model weights, or Isaac Sim. Verify the integration
without any external service first:

```powershell
python integrations/spatialforge/smoke.py
```

For a real deployment, copy `integrations/spatialforge/config.example.json` to
a private config file, set `SPATIALFORGE_CONFIG`, and run
`python integrations/spatialforge/cli.py status`. Configure the FIT service,
Windows worker, Isaac Sim, and model providers separately. The offline smoke
test is the repository-only runnable path; a successful service status does not
claim that a GPU capture or visual acceptance has run.

## What is implemented

- DSH Standard interaction, direct tools and PTC, inherited subagents, separate persistent shells and read-only runtime inspection.
- Individual SAM3, YOLOE, Depth Anything 3 and local VLM service clients. No automatic service restarts.
- Bundled Habitat, LIBERO and CARLA collectors adapted from BenchClaw; independent native Isaac cuboid/camera collector.
- Source evidence import with JSON-pointer replay, public question/media packaging, separate authority data and collection statistics.
- Offline exact-match scoring, including missing predictions; no automatic model API evaluation.
- SQLite operation history with requests, results and failure logs. The agent chooses which operation to rerun; prior artifacts remain.
- Original template registry as searchable reference knowledge.

The benchmark-specific question generator, data cleaning and custom oracle/metric remain editable task code. This is intentional: the host agent supplies task reasoning rather than a second hidden planning model or a fixed roster of stage agents.

## Install and run

Python 3.10+; the core has no third-party dependency.

```bash
python -m pip install -e .
benchforge catalog --workspace ./runs/example
python examples/offline_demo.py --workspace ./runs/offline-demo
python -m unittest discover -s tests -v
```

The demo is a two-item arithmetic fixture. It exercises real local evidence replay, packaging and scoring, not GPU inference or simulator acceptance.

Copy `config.example.json` to `config.local.json`, then configure only the services and simulator runtimes you use. Paths in an annotation request must be visible to its backend. No model weights, service installers or private host paths are included.

```bash
benchforge sam3 --workspace ./runs/example --config config.local.json --input request.json
benchforge evidence --workspace ./runs/example --input import-request.json
benchforge status --workspace ./runs/example
```

`catalog` returns request examples. The DSH tools expose each operation separately with named arguments. `benchforge_view_image` returns actual image attachments; ordinary host image tools remain available.

## DSH mode

```bash
python -m pip install -e '.[dsh]'
python integrations/dsh/build_preset.py \
  --dsh-root /path/to/deepseek-harness \
  --python /path/to/python \
  --config /path/to/BenchForge/config.local.json \
  --output benchforge.local.yml
```

Add the generated patch as a separate preset using your DSH profile's configuration mechanism. The generator never installs it, edits official presets, switches existing sessions or touches another custom mode. Generate again after upgrading DSH. Installed DSH internals are version-sensitive; see `docs/VALIDATION.md` for tested coverage.

## Evidence format

Create source records from original labels or simulator outputs:

```json
{"id":"e1","media":["image.png"],"provenance":{"kind":"official","path":"labels.json"},"selectors":{"answer":"/annotations/0/answer"}}
```

`evidence` resolves paths and derives selected facts from the source. `build` replays the source selector rather than trusting a caller's proposed answer. A task item binds the question to that field:

```json
{"id":"q1","question":"Your task-specific question","evidence_id":"e1","answer_field":"answer","template":"your-template","split":"dev"}
```

For a program oracle, save the program, inputs and computed JSON output as task artifacts; point selectors at that output. Pointer replay proves derivation from a supplied file, not authenticity of that file or semantic correctness of a question. The core is a trusted local workflow, not a hostile-agent sandbox.

Predictions from segmentation, detection and inferred depth are marked `prediction`; they cannot directly become benchmark GT. Preserve original labels, human annotations and simulator state. Source authenticity, calibration, task-specific oracle tests and dataset quality remain explicit acceptance work.

`benchmark-public.zip` contains only selected question fields and media. Authority answers and source records stay outside it. Collection statistics show counts, answer distribution, template distribution and a majority baseline; they do not certify benchmark quality.

## Simulators

- **Habitat**: configure its Python/Conda environment; supply `--scenes`. Captures RGB, depth and agent state.
- **LIBERO**: configure its environment and SDK dataset paths, optionally `LIBERO_BDDL_ROOT` / `LIBERO_DATASET_ROOT`. Captures observations and replayed action/state records.
- **CARLA**: connect to an already available server with `--host` / `--port`. The imported collector retains its explicit optional server-restart argument; normal requests do not enable it.
- **Isaac**: run on the machine with Isaac installed; set its Python launcher in config. The bundled collector handles native cuboids, cameras, depth, instance labels and a pose trajectory. `examples/isaac-scene.json` is the scene schema example. Complex asset reconstruction is not implemented here. A separate remote dispatcher may be configured through `script`; this repository does not silently reuse SpatialForge's desktop worker.

Use the host's background-job tools for long CLI runs. Operation history records running/completed/failed calls but is not an autonomous queue or process supervisor; a forcibly terminated worker can leave a running record. Review artifacts before rerunning. Do not launch overlapping Isaac instances.

See `docs/MIGRATION.md` for the old-to-new capability map, `docs/VALIDATION.md` for verification limits and `NOTICE` for upstream attribution. Licensed under Apache-2.0.
