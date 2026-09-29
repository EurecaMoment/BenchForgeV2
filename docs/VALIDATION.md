# Validation — 2026-09-27

Machine-readable evidence: [production-20260927.json](validation/production-20260927.json).
Implementation and acceptance are separate; no universal perfect-parity claim.

## DSH and deployed Qwen

DSH `dsh-v0.1.7-rc.1`, Node 22.22.2 and deployed
`Qwen/Qwen3.8-Flash-Next` were used in an isolated DSH instance. Its 37 BenchForge
tools registered. The user's existing DSH/Qwen services and SpatialForge were not
modified or restarted.

The first production session (`session-ac332b0f-284f-4eb2-8478-3621c9581f40`)
needed an explicit tool-entrypoint correction after excessive source inspection.
It captured 30 Habitat frames from three scenes, selected eight marked pairs from
six native views, generated 24 questions and called the real model. With its
documented response normalization, 23/24 scored correctly (one blank answer).
This is guided repair evidence, not an autonomous first-pass success.

The final session (`session-8262f815-7959-4e00-bdf8-24f8b6ad5722`) used the published
Habitat pair adapter, reusable compiler and public scorer. It generated exactly
24 questions (8 left/right, 8 above/below, 8 camera-distance), with 0 invalid items.
Qwen answered 24/24 correctly, 0 API failures, 0 missing. First-option and seeded
random baselines scored 0.5833 and 0.3750. Source allocation was 9/9/6; declared
complexity was 16 medium and 8 hard. Template majority rates were 0.5/0.625/0.625.
These are small acceptance samples, not validated benchmark difficulty or model
ranking. The final diagnostic matrix has one real model and two proxy controls;
full IRT suitability is explicitly false.

Actual images were inspected. GT came from native states and deterministic
programs; no model reviewer changed answers. Qwen still performed extra inspection
and one unnecessary small MD5 media count despite task instructions; the core
does not require or generate content hashes. Efficient perfect instruction
following by the host model is not guaranteed.

## Defects found and fixed

- LIBERO/CARLA adapter filenames shadowed SDK imports.
- Annotation clients used incorrect interpreters/default paths; services now use
  explicit configuration. DA3 initially could not reach Hugging Face; a configured
  mirror downloaded weights. Cold download took about 20 minutes on this server.
- Generic preview markers collided with question markers; spatial generation now
  starts from clean RGB and declares its generated visible transform.
- A generation limit double-counted the current sink and dropped the last item.
- The installed and portable scorers differed; both now use one implementation,
  with perfect/negative/missing controls and a single-answer JSON envelope.
- Blank model responses were counted as present; they now count as missing, and
  model evaluation retains raw attempts and retries empty responses.
- The composer emitted `bundle/...` references that broke when renamed to
  `reproduce/`; package relocation now normalizes this prefix.
- Original pre-adapter evidence is retained so selection can be replayed over
  the whole input pool. CARLA instance maps now use lossless PNG.
- Collection gates cover source count, evidence reuse, answer concentration and
  duplicate evidence/question pairs without expensive hashes or model review.

The final standalone ZIP was transferred from Linux to Windows. Without a
`bundle` symlink, source checkout or simulator installation, it regenerated all
24 answers exactly, reselected 8 pairs from the retained 30-frame pool, replayed
16 native camera-range measurements with 0 errors, and scored saved real Qwen
responses at 1.0. NumPy and Pillow are the reproduction dependencies.

## Real optional capabilities

| Capability | Actual acceptance |
|---|---|
| Annotation | Qwen → YOLOE → SAM3 → DA3 completed on one actual room image; 29 candidate instances, original-resolution 480×640 raw depth and semantic/mask images; review queue retained; no GT written |
| YOLOE | CPU fallback because its installed CUDA/PyTorch was newer than the driver; SAM3 and DA3 used CUDA |
| LIBERO | One task, 4 zero-action steps, 2 camera streams and native observations; 4 adapter records; no manipulation-success claim |
| CARLA | Town01, 2 frames, front/top views, lossless instance rasters and native actor/camera states; 4 adapter records; actual images inspected |
| ERQA | 3 Parquet records, 3 images and original answers normalized |
| Data-Juicer | Actual HTML/link cleaning plus short-record filter; 1 accepted / 1 rejected; official answers unchanged |
| Literature | Habitat primary PDF downloaded (6,108,339 bytes), text extracted and one original passage checked |

Annotation outputs are model predictions. Their existence does not certify
segmentation quality or metric depth calibration. The CARLA first run timed out;
reusing the owned server with a longer RPC timeout completed. Collector-owned
process groups are cleaned on failure; shared servers are outside those groups.

## Installation and targeted checks

15 targeted tests cover source replay/privacy, metrics and response coverage,
empty-response retry, native depth drift, temporal semantics, collection answer
shortcuts, durable failures and configuration errors. A wheel installed into a
fresh Windows virtual environment ran the four-image visual production demo.
The demo consumes design bindings and exercises original compiler dependencies,
deterministic recipes, screening, scorer controls and packaging.

After publication, a fresh GitHub clone on Linux ran both the no-install core
demo and visual production demo successfully, using the existing Python SDK
environment. A Windows HTTPS clone attempt hit a network connection reset;
the source ZIP and installed wheel were validated on Windows.

Fresh DSH dependency compilation and clean installation of every GPU SDK were
not repeated; a built DSH and existing optional SDK environments were reused.
CI is configured for Windows/Linux and Python 3.10/3.12; hosted CI status is not
claimed here. ISAAC was not available on the test server. Its independent
collector and unsupported CARLA temporal/planning families remain outside real
acceptance. The original 55-skill mapping documents these limits.
