# Original skill mapping

All 55 original skill files are mapped below. `implemented_with_limits` means a callable business operation and its professional method are present; it does not mean every simulator, dataset or task family passed real acceptance. See [validation](VALIDATION.md).

| Original skill | Tool mapping | Validation / limits |
|---|---|---|
| benchclaw-carla-data-collection | method, carla, adapt_capture, design, compile, synthesize, score | Real Town01 RGB/instance/actor-state capture and native adapter; complete T1-T12 task families not all accepted |
| benchclaw-carla-intent-understanding | method, carla, adapt_capture, design, compile, synthesize, score | Real Town01 RGB/instance/actor-state capture and native adapter; complete T1-T12 task families not all accepted |
| benchclaw-carla-metric-code-build | method, carla, adapt_capture, design, compile, synthesize, score | Real Town01 RGB/instance/actor-state capture and native adapter; complete T1-T12 task families not all accepted |
| benchclaw-carla-simulator-benchmark | method, carla, adapt_capture, design, compile, synthesize, score | Real Town01 RGB/instance/actor-state capture and native adapter; complete T1-T12 task families not all accepted |
| benchclaw-pipeline | DSH orchestration | Live DSH + Qwen composition |
| benchclaw-stage1-draft | DSH orchestration | Live DSH + Qwen composition |
| benchclaw-stage1-benchmark-draft-generation | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage1-capability-dimension-planning | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage1-execution-plan-generation | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage1-intent-understanding | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage1-literature-review | research_review | Actual source passage matched; semantic interpretation is not automatically certified |
| benchclaw-stage1-literature-search | literature | Actual Habitat primary paper download and full-text extraction |
| benchclaw-stage1-scope-preprocess-analysis | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage1-template-metric-draft-generation | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage2-data-collect | DSH orchestration | Live DSH + Qwen composition |
| benchclaw-stage2-existing-benchmark-collection-analysis | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-existing-benchmark-content-label-analysis | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-existing-benchmark-data-materialization | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-real-image-collection-analysis | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-real-image-content-analysis | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-real-image-data-structure-normalization | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-simulator-collection-analysis | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-simulator-data-acquisition | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-simulator-gt-materialization | method, acquire, normalize, clean, adapt_capture | Actual ERQA Parquet and Habitat/LIBERO/CARLA source materialization |
| benchclaw-stage2-plan-generation | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage3-evidence-compiler | DSH orchestration | Live DSH + Qwen composition |
| benchclaw-stage3-existing-benchmark-evidence-compilation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage3-existing-benchmark-annotation | annotate, sam3, yoloe, depthanything3, llm_local | Actual annotation chain acceptance is recorded separately in VALIDATION.md |
| benchclaw-stage3-existing-benchmark-cleaning | clean | Actual Data-Juicer cleaning/filtering preserved original answers; native readable-image checks |
| benchclaw-stage3-real-image-evidence-compilation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage3-real-image-annotation | annotate, sam3, yoloe, depthanything3, llm_local | Actual annotation chain acceptance is recorded separately in VALIDATION.md |
| benchclaw-stage3-real-image-cleaning | clean | Actual Data-Juicer cleaning/filtering preserved original answers; native readable-image checks |
| benchclaw-stage3-simulator-evidence-compilation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage3-simulator-annotation | annotate, sam3, yoloe, depthanything3, llm_local | Actual annotation chain acceptance is recorded separately in VALIDATION.md |
| benchclaw-stage3-simulator-cleaning | clean | Actual Data-Juicer cleaning/filtering preserved original answers; native readable-image checks |
| benchclaw-stage3-plan-generation | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage4-build | DSH orchestration | Live DSH + Qwen composition |
| benchclaw-stage4-full-synthesis | synthesize, screen, model_eval, diagnose, package | Pilot/full real Habitat synthesis, scorer controls and package regeneration |
| benchclaw-stage4-grey-batch-validation | synthesize, screen, model_eval, diagnose, package | Pilot/full real Habitat synthesis, scorer controls and package regeneration |
| benchclaw-stage4-cdm-irt-analysis | diagnose | Real/proxy score matrix consumed; small-sample diagnostics emitted |
| benchclaw-stage4-invalid-item-screening | screen | Original programmatic gate runs on generated real/synthetic items |
| benchclaw-stage4-per-template-batch-synthesis | synthesize, screen, model_eval, diagnose, package | Pilot/full real Habitat synthesis, scorer controls and package regeneration |
| benchclaw-stage4-small-batch-result-evaluation | model_eval, score, baselines, report, diagnose | Real Qwen API responses, missing/duplicate controls and stratified scoring |
| benchclaw-stage4-plan-generation | method, design, plan | Binding validation, consumed compiler spec and Q-matrix exercised by production demo |
| benchclaw-stage4-template-metric-code-generation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage4-answer-image-processing | images | Original composers produced inspected actual images; generic and item markers no longer overlap |
| benchclaw-stage4-answer-program-generation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage4-contract-checking | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage4-gt-kinship-analysis | kinship | Original graph algorithm consumed real Habitat evidence and compiler bundle |
| benchclaw-stage4-metric-compilation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage4-template-compilation | compile, kinship, images, synthesize, score | Executable original algorithms and declarative recipes exercised with real/synthetic evidence |
| benchclaw-stage5-eval | DSH orchestration | Live DSH + Qwen composition |
| benchclaw-stage5-full-evaluation | model_eval, score, baselines, report, diagnose | Real Qwen API responses, missing/duplicate controls and stratified scoring |
| benchclaw-stage5-opencode-usage-report | usage | DSH exported events contain input/output/total counters; subtree coverage is explicit |
| benchclaw-root | DSH orchestration | Live DSH + Qwen composition |
