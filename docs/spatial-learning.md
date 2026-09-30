# 空间能力图谱、数据和课程训练

核心提供 27 个能力节点、每节点 120 个可执行模板规格，以及定位 LOC、跨视角预测 XVP、地图 MAP、反馈操作 INS 的配对课程。模板由问题算子与场景构造组合；随机种子是实例参数，不计作新模板。

图谱依据用户提供的 12 页《空间能力知识图谱_周报汇报》和 2026-09-30 训练计划。节点名称及可辨认支撑边保留来源。PPT 提及的完整 v0.4 JSON 未随材料提供，因此没有把未知的 155 条边或 44 个任务身份补写成原始数据；本库的新模板标注 `engineering_extension`。

## 安装与运行

```bash
python -m pip install -e ".[production,datasets,training]"
python -m benchforge_core.cli spatial_catalog --workspace runs/catalog
python -m benchforge_core.cli spatial_generate --workspace runs/spatial --input examples/spatial/generate.json
```

生成结果会返回 `dataset` 路径。默认每个场景构造生成 20 个世界，再生成同世界的问题变体。完整默认集超过 6 万题；图片仅按世界、能力和帧保存一次，相关题复用观察。`groups_per_profile` 控制规模；正式掌握度评估应增加独立开发世界数量。120 个规格可以在 catalog 中分页检索、按能力和 query 筛选。

输入 JSON 可使用 `capability` 或 `template_ids` 选择课程，`conditions` 选择 `natural`、`supplied_intermediate`、`isolated`。默认只给四个案例的匹配题扩展配对条件。`heldout_profiles` 把指定场景构造完整留给封存测试，其他构造继续按世界划分。图像任务必须保留渲染观察；纯结构任务可以使用 `render:false`。

每个分区包括：

- `questions.jsonl`：公开题目、输入和相对图片路径。
- `authority.jsonl`：独立程序答案、环境状态和来源，交给评分器。
- `sft.jsonl`：只有训练分区包含监督样本，执行题逐步包含观察、动作和实际反馈。
- `manifest.json`：模板覆盖、分区、答案分布和排除的失败示范。

世界及其所有题型、提示对照始终属于同一分区。划分为 train 60%、curriculum_dev 15%、selection_dev 10%、sealed_test 15%。生成器不把开发答案写入 SFT。封存集不进入训练或课程反馈。

导出时创建 `export.json`：

```json
{"dataset":"/absolute/path/to/dataset"}
```

```bash
python -m benchforge_core.cli spatial_export --workspace runs/export --input export.json
```

Parquet 的 `images` 是 PNG 字节列表，`inputs_json` 是可见输入。私有评分来源在单独的 `authority/` 目录。仅发布题目时不包含该目录。原始 JSONL 数据集整体复制后仍能训练，图片路径在加载时相对 dataset 根目录解析。

## 小模型训练

先复制 `examples/spatial/train.json`，填写本地模型路径、数据集路径和可用设备。视觉题选支持多图输入的 Transformers 图文模型并设 `multimodal:true`；纯文本模型选择结构化题子集。`lora` 可以填写 PEFT 的 `r`、`lora_alpha` 和 `target_modules`。默认只读取本地权重，不调用推理服务 API。

```bash
python -m benchforge_core.spatial_learning.training --config train.local.json --run runs/training
python -m benchforge_core.spatial_learning.monitor --run runs/training --port 8767
```

第二条命令在另一个终端运行；浏览器打开 `http://127.0.0.1:8767`，查看每次参数更新的损失、时间、token、提示条件，以及开发成功率、覆盖、课程分配、保持情况和 checkpoint。Harness 的 `training_monitor` 工具读取同一事件流。

监控页可暂停、继续更新或在当前窗口结束后保存并停止。`training_monitor` 的 `guidance` 参数还可调整 `learning_rate`、`hint_fraction` 和 `difficulty`；训练器在下一批前记录并应用指令。`spatial_train` 使用 `action:"start"` 可后台启动并返回 PID、日志和运行目录，随后用监控工具跟踪。

BenchForgeV2 新生成的模式自动包含这些核心工具。现有自定义 SpatialForge 模式可显式安装：

```bash
python integrations/dsh/install_learning.py --preset /path/to/custom.patch.yml --python /path/to/venv/bin/python --dsh-root /path/to/deepseek-harness
```

安装器保存原文件，只向该自定义模式添加学习工具；不修改 DSH 官方预设。待会话空闲时重载 Harness 即生效。

训练按窗口执行：参数更新 → 在 curriculum_dev 上程序评分 → 更新条件化掌握度 → 选择下一窗口样本。在 selection_dev 上逐能力比较初始参考；超过配置的保持退化量则恢复已接受模型及优化器。参考不会随退化下调。`resume` 指向 checkpoint 目录，可恢复模型、优化器、随机数、采样器及课程状态。

提示条件与自然条件分别计分。下一批的提示比例随无提示成功率从 100% 降到 50%、20%、0%；难度升级要求有效场景数、样本数和连续达标窗口。默认门槛来自计划的初始建议，尚须在目标模型上校准，不把少量题的高分称作稳定掌握。

可选 `stages` 指定 S1–S5 窗口类别预算；不设置时允许全部已选能力自主分支调度。类别为单项、联合离线、闭环，比例分别为 85/15/0、60/40/0、30/60/10、25/25/50、25/15/60。调度记录缺失类别并按可用类别归一化，不用离线动作字符串替代环境执行。初始成本未知时等成本，随后使用实测更新时间校准。更新步预算保持确定；真实时间和 token 单独报告。

内置执行环境是可重复的符号状态环境：动作改变位置、持有、姿态、门、插入和释放等状态，反馈失败会改变后续决策。它适合接口和课程机制训练。Isaac、Habitat、LIBERO 的真实观测应通过仓库既有 collector 和 `adapt_capture` 接入；符号成功率不代表机器人或真实三维渲染能力。

## 可复现训练与对照

无需下载权重的 CPU 示例会创建并训练一个小 Transformer，完成开发评分、保存和续训：

```bash
python examples/spatial_learning_demo.py --workspace runs/cpu-training
```

它验证参数更新和课程接口，只训练一个受控关系任务。完整小模型训练需要在 `train.local.json` 明确模型和算力。

`spatial_experiment` 从同一个初始模型、相同池和更新预算依次运行 A 固定、B 无图谱自适应、C 条件图谱自适应。请求格式：

```json
{"config":"train.local.json","run":"runs/abc","seeds":[11,29,71]}
```

配置中的 `initial_checkpoint`（或 `model`）必须是同一份本地初始权重；每个 arm 都从它独立加载，避免先运行的 arm 污染后续 arm。

比较报告包括更新步、实际时间、token 和选择集表现。候选支撑边只是调度先验；需要独立对照证明迁移收益，不能从共同任务或图谱连线宣称因果。SFT 后的 RL 不自动启动，应先有可归因残余错误、可验证程序奖励及继续 SFT 的对照。

评分保存的预测时，每行使用 `{"id":"题目ID","prediction":...}`，调用 `spatial_evaluate`。等价最短路径和满足约束的不同坐标解会被接受。交互预测列表是离线回放；训练开发评估则逐步调用本地模型、推进环境再提供反馈。

模板编译源在 `spatial_learning/build_registry.py`；修改问题算子或场景构造后运行 `python -m benchforge_core.spatial_learning.build_registry` 重建注册表。增加新任务只需连接共同世界、公开观察、程序真值和 scorer，无须重排固定流水线。
