# Universal Evalset Format Contract

This contract defines the stable audit format that Stage4 synthesizers should
emit before creating the Stage5 model-visible package. The shape is inspired by
`an earlier LIBERO temporal benchmark` and
`benchmark_items.template.jsonl`,
but it is a format contract, not a LIBERO-only task contract.

## Two Derived Outputs

A Stage4 full synthesis run must derive two outputs from the same accepted audit
items:

```text
data_22_full_benchmark_dataset/audit_format/
  benchmark_items.jsonl
  template_registry.json
  generation_report.json
  benchmark_assets/

EVALSET_DATASET/
  data/test.jsonl
  images/
  ground_truth/answers.jsonl
  ground_truth/audit_items_with_answers.jsonl
  metrics/score_predictions.py
  cards/benchmark_card.md
```

`audit_format/benchmark_items.jsonl` may contain answers, provenance,
GT-derived values, answerability proofs, and quality flags. `EVALSET_DATASET`
is the Stage5 consumption package: `data/test.jsonl` must be model-visible only,
while answers and audit rows live under `ground_truth/`.

The two outputs must not be generated independently. Package the same accepted
audit item rows into both layouts.

All model-visible assets used for answering must be processed RGB images. Raw
depth maps, raw semantic/instance segmentation maps, all-entity mask atlases,
GT rasters, and other privileged non-RGB images may be preserved for audit, but
must not be referenced by `benchmark_items.jsonl`, copied into
`EVALSET_DATASET/images/`, or referenced from `data/test.jsonl`. If depth,
segmentation, mask geometry, or other privileged raster evidence is required,
render it first into a neutral RGB overlay, RGB panel, RGB crop, or RGB
candidate image.

## Canonical Audit Item Fields

Every audit item should preserve these fields when applicable:

```json
{
  "id": "stable item id",
  "sample_id": "stable item id or source sample id",
  "scene_id": "scene or source group id",
  "split": "train|dev|test|unknown",
  "image": "benchmark_assets/item.jpg",
  "images": ["benchmark_assets/item.jpg"],
  "source_image_count": 1,
  "input_modalities": ["rgb"],
  "sequence_semantics": "single_capture|ordered_sequence|multi_view|candidate_panel",
  "template_id": "template id",
  "capability_id": "capability id",
  "capability_name": "capability name",
  "question_type": "single_choice|multi_choice|ordered_list|interval_choice|yes_no",
  "question_type_name": "human-readable question type",
  "question": "model-facing question text",
  "options": {"A": "option A"},
  "answer": "A",
  "answer_type": "single_choice",
  "scoring": "Exact Match",
  "provenance": {
    "source_root": "source identifier",
    "source_frames": [],
    "gt_values": {},
    "template_gt_rule": "deterministic rule"
  },
  "answerability_proof": {},
  "quality_flags": {
    "uses_only_available_gt": true,
    "deterministic_unique_answer": true,
    "model_visible_anchor_present": true
  }
}
```

Dataset-specific fields are allowed, but they must not replace the core fields
above. Keep source-specific facts under `provenance` or `quality_flags` unless
they are model-visible by design.

## Registry And Report

`template_registry.json` must describe capabilities, question types, enabled
templates, answer types, deterministic GT rules, required visible transforms,
metric ids, and known invalid conditions. It should make clear why this dataset
has its particular task mix instead of forcing every dataset into LIBERO-style
temporal tasks.

`generation_report.json` must include item counts by template, capability,
question type, difficulty, source domain/split when available, answer-position
balance, rejected/filtered counts, quality checks, and generation config.

## Portability Rules

- Use `benchmark_assets/...` paths inside `audit_format/benchmark_items.jsonl`.
- Copy or render assets into `audit_format/benchmark_assets/`; do not point to
  symlinks, URLs, or external workspace paths.
- Store only processed RGB answer assets in `audit_format/benchmark_assets/`
  and `EVALSET_DATASET/images/`. Raw depth, segmentation, all-entity mask, and
  GT raster files belong only in hidden audit/intermediate evidence directories.
- Keep hidden provenance and GT values in audit format only. Stage5
  `data/test.jsonl` must remove them.
- Preserve `answerability_proof` and enough provenance to reproduce each answer.
- Different datasets should specialize capabilities, templates, sequence
  semantics, and asset composers. The common part is the contract shape and
  validation lifecycle, not the task taxonomy.
