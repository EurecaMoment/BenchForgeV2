# Composable production tools

Install `python -m pip install -e ".[production,research]"`. Run
`python examples/production_demo.py --workspace runs/production` for a four-image
visual example, including consumed design bindings, generation, screening,
positive/negative/missing scoring controls and a portable release. This is a
synthetic example, not simulator or model acceptance.

In DSH select BenchForge, call `benchforge_catalog` and use its `requests` examples.
The same operations are available as `benchforge OP --workspace runs/task --input request.json`.
There is no mandatory phase order. Each operation saves its request, result and
logs in a new directory; `status` locates existing artifacts for continuation.

| Intent | Callable tools | Consumed artifacts |
|---|---|---|
| Primary-source research | literature, research_review, method | downloaded full text, exact source passages, reference methods |
| Capability design | design | objective, capability/source/template/metric bindings, Q-matrix |
| Materialize sources | acquire, normalize, adapt_capture | JSONL/JSON/CSV/Parquet/images; native Habitat/LIBERO/CARLA manifests |
| Annotation and cleaning | annotate, clean | candidate masks/depth/labels and review queue; original authority retained |
| Reusable compilation | compile, kinship, images | design, evidence, executable templates/metrics, visible image assets, GT graph |
| Pilot or full synthesis | synthesize, screen | generated items, rejection reasons, distribution and scorer controls |
| Evaluate and diagnose | model_eval, score, baselines, diagnose, report | public-only API inputs, predictions, per-item scores, strata, model/item matrix |
| Reproduce and account | package, usage | separate public/authority archives, generator and scorer, native replay, DSH provider counters |

`compile` takes normalized evidence. `spec` optionally consumes a validated design
file and rejects missing template/metric bindings. `templates` selects bundled
template IDs. A dataset `adapter` accepts `--input JSONL --out JSONL`; its code and
outputs are retained. `image_requests` selects the original image composers.
`generator` can supply a task-specific executable with the same CLI as the bundled
generator. Source-specific code remains reviewable in the portable bundle.

`recipes` is a list or JSONL path for declarative deterministic templates:

```json
{
  "template_id": "visible_count",
  "question": "How many blue squares are visible?",
  "answer_type": "number", "metric_id": "numeric_tolerance",
  "difficulty_level": "easy", "capability_tags": ["count"],
  "answer_program": {"op": "count", "inputs": ["/objects_visible"]},
  "visible_anchor": {"type": "whole_image", "description": "All squares are visible."}
}
```

Programs support field lookup, count/count_where, compare, difference, distance,
order, argmin/argmax, lookup and numeric intervals. Inputs are JSON pointers.
Sequence recipes can require `sequence_semantics: "ordered_sequence"`.
Missing fields/media, ties and nonfinite results reject an item. Declaring a
visible anchor does not prove that an arbitrary private field is observable;
retain the source method and inspect the actual image. Model reviewers must not
create or replace answers.

Metrics include exact/normalized match, multi-choice F1, ordered exact/pairwise
order, numerical tolerance, CARLA counting partial credit, pose range, traffic
action and JSON-field accuracy. Unknown metrics fail explicitly. Missing
responses score zero; unknown and duplicate IDs fail. The installed and portable
scorers share implementation and are checked during synthesis.

Habitat geometric adapters sample continuous surface patches. They do not invent
semantic object identities. Native forward-Z depth is converted to Euclidean
camera range with saved intrinsics, then replayed from raw arrays. CARLA actor
origin distance is a different measurement; it is not silently substituted for
visible-surface range. Speed, future trajectory and route-optimal action require
additional observable sequence/context contracts. T1–T12 CARLA design methods
are searchable through `method`; this does not mean every family is answerable
from a single captured RGB image.

`synthesize mode=full` enforces requested minimum difficulty ratios. Difficulty
labels describe template complexity. `diagnose` retains the original Rasch proxy,
item discrimination and capability summaries; it is not a full statistical IRT
fit. Baselines are proxy controls and must not be reported as real model runs.

The complete package includes private authority, original referenced inputs,
template code and native replay. Send only the public package to respondents.
Use the supplied README commands to regenerate and score after extraction.
