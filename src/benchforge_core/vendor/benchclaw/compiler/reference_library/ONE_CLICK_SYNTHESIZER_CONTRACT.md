# One-click Evalset Synthesizer Contract

This contract is the generation target for `answer-program-generation`, especially
when a local Qwen model is asked to write dataset-specific runtime code. The
reference shape is `a strict standalone benchmark synthesizer`: a strict,
auditable, deterministic generator with a small curated template registry,
neutral visual overlays, hard validation, separated hidden answers, and one CLI
that can produce a usable evaluation set.

Read this together with `BENCHMARK_QUALITY_CONTRACT.md` and
`UNIVERSAL_EVALSET_FORMAT_CONTRACT.md`. The quality contract defines benchmark
validity, this file defines runtime surfaces and CLI shape, and the universal
format contract defines the audit format plus Stage5 package projection.

## Required Role

Generate code that turns Stage3 evidence plus the compiled Stage4 manifests into
real benchmark items. The generated code may be dataset-specific, but it must be
thin: field adapters, template bindings, deterministic answer functions, media
packaging, and validation. It must not fork the Stage4 pipeline or loosen gates.

## Required Files

The `data_20_template_metric_code_bundle` must contain these runtime surfaces:

```text
scripts/generate_items.py
scripts/score_predictions.py
scripts/package_evalset.py
scripts/audit_evalset_quality.py
scripts/check_difficulty_mix.py
scripts/validate_bundle.py
qwen_one_click_synthesizer_prompt.md
synthesizer_contract.json
contrib/gt_adapter/adapter_contract.json
contrib/asset_builder/asset_builder_contract.json
contrib/template_registry/template_registry.json
contrib/metric_registry/metric_registry.json
contrib/item_validator/item_validator_contract.json
```

`generate_items.py` is the canonical one-click item generator. A separate
`one_click_generate_evalset.py` wrapper is allowed when useful, but it must call
the canonical scripts instead of reimplementing hidden behavior.

## CLI Contract

`generate_items.py` must support:

```bash
python scripts/generate_items.py \
  --bundle data_20_template_metric_code_bundle \
  --evidence-index data_20_template_metric_code_bundle/evidence_index.jsonl \
  --out out/items.jsonl \
  --limit 100 \
  --seed 20260624 \
  --template-id TEMPLATE_ID \
  --filtered-output out/filtered_items.jsonl
```

It may also support:

```text
--asset-dir
--report
--package-out
--template-set
--difficulty-target easy|medium|hard|all
--strict
--dry-run
```

## Code Shape

The generated `generate_items.py` should use this shape:

1. Constants for capability dimensions, question types, retained template ids,
   and deterministic metric ids.
2. Small dataclasses for normalized evidence records, objects, media, and
   generated items.
3. A `GeneratedDatasetAdapter` or equivalent thin adapter that maps Stage3 field
   names into canonical fields.
4. A strict template registry whose rows mirror `template_manifest.jsonl`.
5. One deterministic generator function per enabled template.
6. Shared helpers for options, interval bins, ordering margins, duplicate
   prevention, media resolution, and neutral overlay generation.
7. `validate_item_contract()` called before every item is accepted.
8. Writers for full audit items, filtered/rejected items, and a generation
   report.

Avoid a broad 100-template package. Prefer a small set of enabled templates that
are actually supported by GT and image manifests.

## Item Contract

Every generated audit item must include:

```json
{
  "item_id": "stable id",
  "media": ["bundle-relative or workspace path"],
  "question": "natural model-facing text",
  "options": {"A": "..."},
  "answer": "A",
  "answer_type": "single_choice",
  "metric_id": "accuracy",
  "template_id": "template id",
  "capability_tags": [],
  "difficulty_level": "easy|medium|hard",
  "evidence_refs": [],
  "answerability_proof": {
    "visible_media": ["./images/..."],
    "visible_anchor_type": "safe_rgb|rgb_depth_pair|bbox_label_overlay|pose_map_overlay|trajectory_panel|candidate_panel",
    "question_references_visible_anchor": true,
    "private_gt_fields_used_for_answer": [],
    "why_visible_anchor_is_sufficient": "..."
  },
  "metadata": {
    "audit_only": true
  }
}
```

`package_evalset.py` must then write model-visible `data/test.jsonl` without
`answer`, `metadata`, `evidence_refs`, object ids, bbox, depth, area, GT fields,
or provenance. Hidden answers and audit evidence go to
`ground_truth/answers.jsonl` and `ground_truth/audit_items_with_answers.jsonl`.

It must also support an audit-format projection:

```bash
python scripts/package_evalset.py \
  --bundle data_20_template_metric_code_bundle \
  --items full_audit_items.jsonl \
  --out EVALSET_DATASET \
  --audit-format-out data_22_full_benchmark_dataset/audit_format
```

The audit-format directory must contain `benchmark_items.jsonl`,
`template_registry.json`, `generation_report.json`, and `benchmark_assets/`.
This is a format contract, not a requirement to reuse LIBERO-specific temporal
templates.

## Hard Constraints

- No unanswerable or three-way questions.
- No "无法判断", "信息不足", "cannot determine", or equivalent options.
- No bare numeric final answers; convert numbers to interval choices or
  deterministic tolerance metrics.
- No duplicated option display text.
- No malformed or incomplete option display text. In particular, no choice may
  end with dangling spatial phrases such as `to the left of`, `to the right of`,
  `in front of`, or `behind`.
- No option-set shortcut where the gold answer is identifiable from a unique
  surface-form defect. Options must also remain distinct after normalizing away
  filler phrases such as `the target`.
- No `object_id`, bbox, mask, depth field names, metadata, annotation paths, or
  GT terms in model-facing text.
- Instance-level relation questions must use neutral A/B/C/D overlays or
  neutral image panels.
- Questions whose answer is computed from simulator pose, camera coordinate,
  navigation state, depth, bbox/mask, area, trajectory, object id, frame id, or
  other private GT must expose the relevant evidence through a model-visible
  processed asset. Raw RGB-only is not a valid anchor for these private fields.
- Templates that compare, ground, identify, order, count among candidates,
  localize, track, or reason about GT objects/regions/views/steps must declare
  `visual_marker_policy` and consume processed question images with neutral
  markers, panels, crops, grids, or trajectory drawings. The model-facing
  question and/or options must reference those visible anchors, not raw object
  ids, bbox/depth field names, or unmarked hidden GT object names.
- The answer must be computed from Stage3 GT or deterministic transforms only.
- A local LLM may write code, but it must not inspect images to guess answers.
- Scoring must be deterministic and offline; no LLM judge as the primary metric.
- Scoring must require exactly one prediction for every item, reject duplicate or
  unknown item ids, and divide by the full benchmark item count rather than the
  number of submitted predictions.
- Packaged evalsets must pass `scripts/audit_evalset_quality.py`, including
  checks for audit sidecars, missing manifest/checksums, malformed-choice
  shortcuts, identical image bytes assigned to multiple scene identities,
  answer-bearing files at `EVALSET_DATASET` root, blank/near-empty media, and
  missing model-visible answerability proof.
- `WORKSPACE_ROOT/EVALSET_DATASET` must not contain root-level answer-bearing
  `dataset.jsonl`, `items.jsonl`, or similar audit files. `data/test.jsonl` is
  the only model-visible item file; answers and audits live under
  `ground_truth/`.
- `cards/benchmark_card.md` must include enough operational metadata for a
  reader to reproduce and judge the benchmark: source, collection/synthesis
  settings, tasks, visible/hidden boundary, scorer CLI, limitations, license or
  usage boundary, and item/template/difficulty distribution.

## Local Qwen Generation Rules

When using local Qwen to draft runtime code:

1. Feed only `BENCHMARK_QUALITY_CONTRACT.md`, this contract, the Stage4 plan,
   `UNIVERSAL_EVALSET_FORMAT_CONTRACT.md`, contributor contracts,
   template/metric manifests, `gt_kinship` summaries, image manifest schema, and
   compact field samples.
2. Ask Qwen for complete files, not prose. The main generated file must be
   executable and importable.
3. Reject any output that creates placeholders, random answers, subjective
   scoring, hidden answer leakage, broad unsupported templates, or a separate
   pipeline.
4. Run `py_compile`, `generate_items.py --limit 1`, positive/negative scoring,
   packaging smoke, `audit_evalset_quality.py`, and model-visible leakage checks
   before accepting code.

## Acceptance Checklist

The generated one-click runtime is acceptable only when:

- `py_compile` passes for all generated scripts.
- `generate_items.py --limit 1` emits at least one real item.
- Perfect predictions score 1.0 or full score.
- Negative predictions score lower than perfect predictions.
- A partial prediction file with fewer predictions than items is rejected or
  scores below full score.
- `package_evalset.py` emits `data/test.jsonl`, `images/`,
  `ground_truth/answers.jsonl`, and `metrics/score_predictions.py`.
- `package_evalset.py` emits `ground_truth/audit_items_with_answers.jsonl`,
  `manifest.json`, `checksums.json`, and `cards/benchmark_card.md`.
- `package_evalset.py --audit-format-out <dir>` emits nonempty
  `benchmark_items.jsonl`, `template_registry.json`, `generation_report.json`,
  and `benchmark_assets/`.
- `audit_evalset_quality.py --evalset <package>` returns PASS.
- `data/test.jsonl` has only model-visible fields and media paths are relative
  `./images/...`.
- Every hidden audit row contains an `answerability_proof`, and the proof is
  consistent with the model-visible media.
- No blank, all-black/all-white, near-empty, tiny placeholder-like, symlink, or
  answer-leaking image enters the package.
- No answer-bearing JSONL is present at the evalset root.
- Difficulty mix is checked and either passes or blocks with evidence.
