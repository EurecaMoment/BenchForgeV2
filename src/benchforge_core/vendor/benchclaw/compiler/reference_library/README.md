# reference_library

本目录是 `template-metric-code-generation` skill 的外挂参考库，用于将统一模板包中的候选模板过滤/适配到 BenchClaw 的图像/视频 + 仿真器或半监督 GT 制造范式。

文件：

- `BENCHCLAW_IMAGE_VIDEO_TEMPLATE_METRIC_LIBRARY.md`：完整人类可读参考，包含 10 类保留模板、schema、GT 规则、指标和准入规则。
- `template_family_registry.yaml`：机器可读的保留模板族、允许媒体、GT 来源、answer type 和主指标映射。
- `answer_type_metric_registry.json`：机器可读的 answer type 与 deterministic evaluator registry。
- `BENCHMARK_QUALITY_CONTRACT.md`：通用 benchmark 质量契约，定义证据到模型可见锚点、确定性答案、隐藏审计和质量门的完整生命周期；小 Qwen 生成 runtime 时必须读取。
- `ONE_CLICK_SYNTHESIZER_CONTRACT.md`：本地 Qwen 或其他代码生成器必须遵守的一键评测集合成器契约，抽取 `a strict standalone benchmark synthesizer` 的严格生成器模式。
- `UNIVERSAL_EVALSET_FORMAT_CONTRACT.md`：通用审计格式与 Stage5 安全交付格式契约，参考 `an earlier LIBERO temporal benchmark` 的文件组织，但不复制其任务 taxonomy。
- `schema_patch_notes.md`：对 stage item schema 的适配说明和 provenance/题面约束。

使用原则：

1. 本目录不替代 `BENCHCLAW_ROOT/templates/` 统一模板包。
2. 本目录用于过滤和适配：只有能映射到保留模板族、保留 answer type、deterministic metric 和可审计 GT 的模板，才允许 enabled。
3. 与 stage schema 或统一模板包硬契约冲突时，不能擅自绕过硬契约；应 blocked/disabled 并记录原因。
4. 使用本地 Qwen 生成 runtime 代码时，必须把 `BENCHMARK_QUALITY_CONTRACT.md`、`ONE_CLICK_SYNTHESIZER_CONTRACT.md`、`UNIVERSAL_EVALSET_FORMAT_CONTRACT.md`、Stage4 plan、contrib contracts、template/metric manifests、GT kinship 摘要和 image manifest schema 一起作为提示上下文；生成结果必须通过 contract-checking 后才可进入灰度。
