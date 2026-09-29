# Benchmark Quality Contract

This file is the general, model-readable quality contract for BenchClaw Stage4.
It is not tied to one dataset or one failure case. A small local Qwen model
should be able to read this contract plus the Stage4 manifests and produce a
benchmark generator that is answerable, auditable, and resistant to shortcuts.

## Core Lifecycle

Every benchmark item must follow this lifecycle:

```text
Stage3 evidence
  -> normalized GT fields
  -> model-visible visual/text anchor
  -> deterministic answer rule
  -> validated item
  -> model-visible test row + hidden answer/audit row
  -> deterministic scorer + package audit
```

If any link is missing, disable the template or block the package. Do not fill a
gap with model guesses, random choices, subjective judgement, or hidden GT text
in the question.

Stage4 also has a two-format output lifecycle: accepted audit items are first
written in the universal audit format (`benchmark_items.jsonl`,
`template_registry.json`, `generation_report.json`, `benchmark_assets/`) and
then projected into the Stage5-safe package (`data/test.jsonl`, `images/`,
`ground_truth/`, `metrics/`). The two formats must come from the same accepted
items; do not sample or regenerate them separately.

## Universal Item Requirements

An item is valid only when all requirements below hold:

- **Answerable**: the answer is uniquely determined from Stage3 GT or a
  deterministic transform declared by the template.
- **Visible anchor**: the model can identify the referenced entity, region,
  time step, view, or candidate from model-visible content.
- **Model-visible answerability proof**: the hidden audit row must explicitly
  state which model-visible media path and visible anchor make the answer
  decidable. A question whose answer is determined only by private simulator
  state, pose coordinates, depth maps, object ids, bbox/mask values, trajectory
  logs, or annotation metadata is invalid unless those facts have first been
  rendered into a neutral model-visible processed RGB asset such as an RGB
  depth-visualization panel, RGB top-down pose/map overlay, RGB trajectory
  panel, RGB candidate panel, RGB crop, or A/B/C/D marker image. Raw depth maps,
  raw semantic/instance segmentation maps, all-entity mask atlases, and other
  privileged rasters must never be used as question images or model-visible
  media.
- **Hidden answer separation**: `data/test.jsonl` contains no answer, metadata,
  evidence refs, object ids, bbox/mask/depth/area fields, annotation paths, or
  provenance.
- **Auditability**: hidden files preserve the exact evidence refs, answer rule,
  visual label mapping, and source media needed to reproduce the answer.
- **Scorability**: the primary metric is offline and deterministic; LLM judges
  are allowed only as secondary analysis.
- **No shortcuts**: the answer cannot be inferred from option formatting,
  option defects, file names, item ids, record ordering, duplicate images, or
  leaked metadata.
- **Media integrity**: every model-visible media path exists, is readable,
  bundle-local, non-symlinked, and has a safe filename.
- **Processed-RGB-only media**: every model-visible image used for answering is
  a processed RGB image derived from RGB observations or an RGB-rendered overlay
  / panel. Depth arrays, raw depth PNGs, semantic masks, instance masks,
  all-entity segmentation atlases, GT rasters, and other privileged non-RGB
  images may be kept only in hidden audit or intermediate directories.
- **Media informativeness**: model-visible images must not be all-black,
  all-white, near-empty, tiny placeholder-like files, or low-information frames
  that cannot support the question. Such media must be rejected or filtered with
  a recorded reason instead of counted toward benchmark scale.

## Private-GT-To-Visible-Anchor Rule

The following GT families are private by default and cannot be asked about from
raw RGB alone:

- simulator or robot pose, coordinate bins, navmesh state, route optimality, and
  trajectory steps;
- depth, metric distance, area, size, bbox/mask geometry, object ids, instance
  ids, and annotation metadata;
- hidden scene names, file names, record ids, frame ids, or source provenance;
- any label that is not visible or inferable from the model-visible media.

If a template consumes one of these fields, it must declare the exact
model-visible transform that exposes the needed evidence as a processed RGB
asset: e.g. RGB-rendered depth visualization, metric scale overlay, candidate
marker panel, map/pose overlay, trajectory panel, crop/inset, or multi-view
grid. The generated item must carry a hidden
`answerability_proof` with at least:

```json
{
  "visible_media": ["./images/..."],
  "visible_anchor_type": "rgb_depth_visualization|bbox_label_overlay|pose_map_overlay|trajectory_panel|candidate_panel|safe_rgb",
  "question_references_visible_anchor": true,
  "private_gt_fields_used_for_answer": ["..."],
  "why_visible_anchor_is_sufficient": "..."
}
```

If this proof cannot be written honestly, the item is invalid.

## Visual Anchor Policy

Use this policy whenever an item refers to a particular object, region,
trajectory, view, frame, or candidate that is not self-evident from the natural
image alone.

1. Create a processed model-facing asset: neutral bbox labels, point labels,
   crop panel, inset zoom, candidate panel, multi-view grid, RGB-rendered depth
   visualization panel, or trajectory/top-down panel.
2. Use neutral labels such as `A/B/C/D`, `P1/P2`, `View 1/View 2`, or
   `Step 1/Step 2`. Do not write semantic class names, object ids, answer words,
   or GT field names into the overlay.
3. Store the label-to-GT mapping only in hidden audit data or image manifest
   fields consumed by the generator/scorer.
4. The model-facing question or options must reference the visible labels.
   A question that says "the target object" or uses a hidden object name without
   a visible marker is invalid.
5. If a required marker/crop/panel cannot be generated from GT geometry, reject
   the item. Do not ask an LLM to infer missing geometry.

Templates that compare, identify, order, count among candidates, localize, track,
or reason about object relations must declare `visual_marker_policy` in
`template_manifest.jsonl`.

## Template Enablement Rules

Enable a template only when the manifest row can answer these questions:

- What exact evidence fields are consumed?
- What model-visible anchor lets the model know which entity/candidate/view is
  being asked about?
- What deterministic answer rule produces the gold value?
- What invalid conditions make the item filtered?
- Which metric scores the answer, and what prediction format is required?
- Which hidden audit fields prove the answer after packaging?

Disable or block templates that require unavailable geometry, ambiguous natural
references, subjective visual judgement, hidden object names, unbounded numeric
answers, or unsupported metrics.

## Option And Answer Design

For choice questions:

- All option values must be complete natural phrases or stable labels.
- Options must remain distinct after trivial normalization such as whitespace,
  punctuation, and generic filler removal.
- Distractors must be plausible under the same visible anchor. Do not create one
  malformed, shorter, longer, uniquely punctuated, or uniquely named option that
  reveals the answer.
- Do not include "cannot determine", "insufficient information", or equivalent
  escape choices unless the benchmark task is explicitly about uncertainty and
  the metric supports it.
- Do not use bare numeric answers when tolerances matter. Prefer intervals,
  ordered bins, or deterministic tolerance metrics.

For open or numeric answers, define a parser, normalization rule, tolerance, and
failure behavior before enabling the template.

## Package Quality Gate

Every packaged evalset must contain:

```text
README.md
manifest.json
checksums.json
data/test.jsonl
ground_truth/answers.jsonl
ground_truth/audit_items_with_answers.jsonl
metrics/score_predictions.py
cards/benchmark_card.md
images/
```

The internal full-synthesis artifact must also contain:

```text
audit_format/benchmark_items.jsonl
audit_format/template_registry.json
audit_format/generation_report.json
audit_format/benchmark_assets/
```

This audit format may contain answers, provenance, GT values, answerability
proofs, and quality flags. It is modeled after the LIBERO temporal package
shape, but dataset-specific capabilities and templates must come from the
current Stage1/Stage3/Stage4 evidence. Reusing the same task taxonomy for every
data source is a quality failure.

The package must pass `scripts/audit_evalset_quality.py`. The audit is a quality
gate, not a best-effort report. Failures such as missing audit sidecars, partial
prediction full-score behavior, model-visible hidden GT, malformed options, or
duplicate media identities must block release.

Question images in `WORKSPACE_ROOT/EVALSET_DATASET/images/` must be processed
RGB assets only. The Stage5 package must not contain raw depth maps, raw
segmentation maps, all-entity masks, mask atlases, or GT raster files as media
targets. If depth or segmentation is needed for answerability, render it into an
RGB overlay/panel first and keep the raw source file only in hidden audit or
intermediate evidence.

`WORKSPACE_ROOT/EVALSET_DATASET` is the Stage5 consumption package. It must not
also contain root-level answer-bearing files such as `dataset.jsonl`,
`items.jsonl`, or `audit_items.jsonl`; these files are too easy to feed to a
model by mistake. Answer-bearing rows belong only under `ground_truth/` in the
evalset package, or under `stage4/artifacts/data_22_full_benchmark_dataset/`
when keeping an internal audit artifact.

`cards/benchmark_card.md` must be usable by an evaluator without reading the
pipeline logs. It must include source datasets/simulators, collection or
synthesis settings, task families, visible inputs, hidden GT boundaries,
metric/scorer CLI, known limitations, license/usage boundary, item counts and
difficulty/template distribution.

## Small-Qwen Generation Protocol

When a small local Qwen model writes runtime code, keep its task narrow:

1. Give it this contract, `ONE_CLICK_SYNTHESIZER_CONTRACT.md`,
   `UNIVERSAL_EVALSET_FORMAT_CONTRACT.md`, the Stage4 plan, contributor
   contracts, field catalog, GT kinship summary, image manifest schema/samples,
   enabled template rows, and metric rows.
2. Ask for complete Python files that adapt fields, bind enabled templates, and
   implement deterministic answer functions.
3. Do not give it full hidden answers or large raw GT dumps. Provide compact,
   redacted examples and field families.
4. Treat the output as untrusted code. Accept it only after `py_compile`,
   item-generation smoke, positive/negative scoring, partial-prediction check,
   packaging smoke, leakage check, difficulty check, and evalset audit pass.

The model may help write code, but deterministic scripts decide whether the
benchmark is valid.
