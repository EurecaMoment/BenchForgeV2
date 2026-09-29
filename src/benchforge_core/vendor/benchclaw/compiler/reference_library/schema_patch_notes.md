# Schema Patch Notes — BenchClaw 图像/视频适配层

此文件说明本外挂参考库对 `benchmark_item.schema.json` 和运行时模板定义的建议约束。它不替代 stage schema；当 stage schema 更严格时，以 stage schema 为准。

## 1. 推荐必备字段

每个 item 至少应有：

```text
id 或 item_id
media
task
prompt 或 question
answer
eval 或 metric_id
provenance
template_id
capability_tags
evidence_refs
```

## 2. Provenance 必须可审计

`provenance` 至少应记录：

```json
{
  "gt_source": "simulator_state | simulator_depth | simulator_segmentation | simulator_action_log | simulator_camera_pose | semi_supervised_bbox | semi_supervised_mask | semi_supervised_depth | calibrated_measurement | tracking_annotation",
  "gt_evidence": {},
  "generation_rule": "rule_id_or_template_id",
  "scene_id": null,
  "frame_ids": []
}
```

## 3. 真实图像边界

真实图像可以稳定生成 left/right、above/below、bbox/mask grounding、visible count、relative depth、area comparison、occlusion relation。绝对距离、房间大小、相机轨迹长度、3D orientation 必须有 calibrated depth、SLAM、尺度标定、人工测量或可靠 3D reconstruction。

## 4. 题面约束

题面不得暴露 object_id、depth_median、privileged_gt、simulator hidden state 字段名。正确做法是将隐藏 GT 编译为可观察的自然语言题面。

## 5. 主指标约束

正式主指标只能使用 deterministic metric。LLM judge、captioning metric、主观 rating 不进入 BenchClaw 图像/视频适配主库。
